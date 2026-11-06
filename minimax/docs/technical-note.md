# 技术说明（一页）：基于 seekdb 与 PowerContext 的 SDD 上下文闭环

## 问题

传统“把仓库丢给模型”的方式有两个问题：上下文不可追溯，任务状态不可恢复。
本次实现把规格、代码、测试切成带真实路径/行号/内容哈希的上下文单元，存入 seekdb，
按任务检索后交给 MiniMax；任务状态写入 PowerContext，进程或服务重启后仍可继续。

## 1. 上下文采集与切分

`sdd_context/chunking.py` 不做纯文本滑窗：

- 规格 Markdown 按 `##` 标题切分，优先提取 `R1`/`C1` 等需求编号作为稳定 ID；
- Python 代码用 `ast` 解析顶层函数/类，测试用顶层 `test_*` 函数；
- 每个 `SourceDoc` 携带 `path`、`symbol`、`line_start`、`line_end`、`content_hash`、
  `component`、`requirement_ids` / `covers` 元数据。

因此检索结果能直接回到真实文件和行号，内容哈希也是上下文是否变化的判据。

## 2. seekdb 存储与检索

`sdd_context/store.py` 使用 **pyseekdb 1.4.0.post1 嵌入式模式**，不需要 Docker 或独立
OceanBase 进程。数据落在 `artifacts/seekdb`（可配置），集合为 `sdd_documents`。

- 入库：`collection.upsert(ids, documents, metadatas)`，随后 `refresh_index()`；
- 全文：`collection.get(where={"kind": kind}, where_document={"$contains": term})`；
- 向量：`collection.query(query_texts=..., n_results=..., where={"kind": kind})`；
- 融合：关键词命中次数、向量排名、组件归并、需求编号加权共同打分；
- 证据：每次 `get` / `query` 写入 `SeekDBStore.query_log`，随上下文包落盘；
- 清理：`prune(valid_ids)` 删除重入库后已不存在的旧块。

`HashEmbeddingFunction` 用 SHA-256 有符号哈希生成 384 维向量，支持中英文 n-gram，
完全离线、确定性，不需要下载 ONNX 模型，适合干净环境复现。

## 3. 任务状态：PowerContext Atomic Memory

`powercontext_client.py` 调用 PowerContext 1.5.0 HTTP API：

- `GET /v1/scopes/default` 解析 Scope；
- `POST /v1/memory/remember` 以 kind=`sdd-task-state` 写入 `TaskState` JSON；
- `POST /v1/memory/entries/list` 读取并按 `saved_at` 选出同一 `task_id` 的最新状态。

`TaskState` 包含 `task_id`、`phase`、`completed`、`pending`、`verification`、`context_hash`、
`saved_at`。`verify.py` 先用一个从未出现过的 `task_id` 证明“从空保存”，再启动一个全新的
Python 进程执行 `sdd_context resume`，校验读出的状态与重新检索得到的 `context_hash` 一致。
2026-11-06 的实测还额外重启了 PowerContext 服务进程，状态仍可从 SQLite 恢复。

## 4. MiniMax 实际参与

`patchgen.py` 把任务、相关规格全文、目标测试全文、相关代码和当前文件拼成提示词，
要求 MiniMax 返回严格 JSON：

```json
{"analysis": "...", "changes": ["..."], "updated_file": "<完整文件>", "confidence": 0.0}
```

拿到 `updated_file` 后：

1. `ast.parse` 校验语法；
2. 用 `difflib.unified_diff` 生成 `artifacts/changes.patch`；
3. 保存原始响应、提示词、模型名、token 用量到 `artifacts/dev_record/`；
4. 校验 `updated_file` 哈希、patch 哈希，以及“patch == before/after 的精确 diff”；
5. 写回 `demo_project/bookvault/search.py` 并运行测试。

开发记录与 diff 的一致性由 `verify.py::_verify_patch_consistency` 自动检查，不是人工声明。

## 5. 验收方法

`./verify.sh` 是唯一的验收入口，按顺序执行：

1. 用新临时 seekdb 库完成干净入库；
2. 恢复 `before` 快照，目标测试 6 个失败（均为 `AssertionError`），回归测试 6 个通过；
3. 检索任务上下文，检查来源路径真实存在且覆盖 spec/code/test；
4. 临时追加 `R7` 规格段并重新入库，断言新块可检索；恢复规格并重入库，断言旧块被清理；
5. PowerContext 状态从空保存，新进程 `resume` 校验哈希；
6. MiniMax 生成补丁并写回，目标测试与回归测试全部通过；
7. 对比改动前后所有测试文件 SHA-256，证明测试集未变；
8. 汇总到 `artifacts/run/verification.json`，`overall_pass` 为最终结论。

## 6. 取舍

- 选择嵌入式 seekdb 而不是启动 OceanBase 服务，是为了让评审在干净环境里少依赖、少配置；
  存储与检索仍由 seekdb 真实完成，查询日志可审计。
- 选择确定性哈希向量而不是远程 embedding，是为了离线可复现；关键词与元数据加权弥补语义召回。
- 选择 Atomic Memory 而不是另建状态文件，是为了让“状态”真正由 PowerContext 托管，
  进程重启后仍可读取。
