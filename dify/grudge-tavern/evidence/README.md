# 证据目录

本目录保存实际运行结果的脱敏副本。所有文件由脚本生成，不包含真实 API Key、
PowerContext token 或未脱敏的 scope id。

| 文件 | 生成脚本 | 内容 |
| --- | --- | --- |
| `session1.request.json` | `04_verify.py` | 第一段会话的请求（含原文 query） |
| `session1.response.json` | `04_verify.py` | 第一段会话的完整回复、会话 id、耗时 |
| `session2.request.json` | `04_verify.py` | 第二段全新会话的请求 |
| `session2.response.json` | `04_verify.py` | 第二段回复、命中的记忆关键词 |
| `powercontext.memory-list.json` | `04_verify.py` | 第一段前后记忆数量、新增条目全文 |
| `powercontext.prepare-session2.json` | `04_verify.py` | 第二段会话的 `context/prepare` 原始返回 |
| `verify.summary.json` | `04_verify.py` | 断言汇总（`passed`、会话 id、关键词） |
| `workflow-run-*.json` | `05_collect_trace.py` | Dify workflow run 详情 |
| `workflow-run-*.nodes.json` | `05_collect_trace.py` | 节点级执行记录（顺序、输入输出、耗时） |

## 本次实测结果（2026-11-07）

- Dify 1.17.1 + PowerContext 1.5.0，模型 `langgenius/anthropic/anthropic` /
  `claude-sonnet-4-6`（经 Anthropic 兼容代理）；
- 会话 1 用 11.1 s，PowerContext 记忆数 2 → 3；
- 会话 2 是新的 `conversation_id`，用 4.2 s，命中全部四个关键词
  （`12` / `十二` / `琴` / `莉拉`）；
- 两次 workflow run 的 10 个节点全部 `succeeded`，顺序为
  start → build_query → prepare_memory → list_memories → merge_memory →
  narrate → parse_reply → decide → remember → answer；
- `verify.summary.json` 中 `passed: true`。

## 如何复核

1. 打开 `verify.summary.json`，确认 `passed: true`；
2. 对照 `session2.response.json` 的 `answer` 与 `recall_markers`；
3. 打开 `powercontext.memory-list.json`，确认 `new_items` 中出现了第一段会话的事实；
4. 打开 `workflow-run-*.nodes.json`，确认
   `prepare_memory` / `list_memories` / `remember` 都出现在执行记录中，
   且 `remember` 在 `narrate` 之后。

## 重新生成

```bash
python scripts/04_verify.py
python scripts/05_collect_trace.py
```

## 脱敏规则

- `app-…` API Key → `app-***REDACTED***`
- scope id → `scp-***PUBLIC-DEMO***`
- 不保存 Dify 登录 cookie、模型 API Key、PowerContext token
