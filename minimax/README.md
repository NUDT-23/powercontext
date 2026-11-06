# MiniMax × OceanBase：Spec-Driven Development 上下文管理

本目录是参赛材料。方案把 **规格（specs）→ 代码（code）→ 测试（tests）** 作为上下文源，
用 **seekdb（pyseekdb 嵌入式模式）** 做真实入库与检索，用 **PowerContext 1.5.0** 保存任务状态，
再让 **MiniMax-M2.5** 基于检索到的上下文生成代码补丁，最后用测试证明改动有效。

示例业务工程是 `demo_project/` 下的 BookVault 搜索模块；规格 `specs/search-requirements.md`
要求实现多标签 AND 过滤、大小写不敏感、空标签忽略和 `limit` 校验。改动前目标测试失败，
改动后目标测试与回归测试全部通过。

## 1. 数据流

```
demo_project/specs/*.md ─┐
demo_project/**/*.py  ───┼─> chunking.py ─> seekdb (pyseekdb embedded)
demo_project/tests/*.py ─┘                        │
                                                  v
 task description ───────────────> retrieval.py (keyword + vector + component + requirement)
                                                  │
                                                  v
                                     ContextBundle (real paths / lines / hashes)
                                                  │
                      ┌───────────────────────────┼───────────────────────────┐
                      v                           v                           v
              PowerContext Atomic Memory    MiniMax-M2.5               tests (pytest)
              (task state / resume)         (patch + dev record)       (before/after)
```

## 2. 目录结构

| 路径 | 说明 |
| --- | --- |
| `sdd_context/config.py` | 从 `.env` / 环境变量加载配置 |
| `sdd_context/chunking.py` | 规格按 Markdown 标题、Python 按 AST 切分，生成稳定 ID 和内容哈希 |
| `sdd_context/store.py` | seekdb 入库、全文过滤、向量检索、查询日志、过期清理 |
| `sdd_context/retrieval.py` | 任务关键词抽取、三路检索、上下文哈希 |
| `sdd_context/powercontext_client.py` | PowerContext v1 HTTP 客户端（Scope / Atomic Memory） |
| `sdd_context/state.py` | 任务状态保存、按 `task_id` 读取、状态列表 |
| `sdd_context/minimax_client.py` | MiniMax OpenAI 兼容客户端与响应解析 |
| `sdd_context/patchgen.py` | 组织提示词、调用 MiniMax、生成 unified diff 与开发记录 |
| `sdd_context/ingestion.py` | 一键入库并写 `artifacts/run/ingest.json` |
| `sdd_context/cli.py` | 命令行入口 |
| `sdd_context/verify.py` | 一键验收与证据链生成 |
| `demo_project/` | 示例业务工程、规格、目标测试与回归测试 |
| `artifacts/before/` | 改动前的代码快照 |
| `artifacts/after/` | MiniMax 生成的改动后代码快照 |
| `artifacts/changes.patch` | 由模型输出生成的统一 diff |
| `artifacts/dev_record/` | 提示词、原始响应、模型元数据、可读开发记录 |
| `artifacts/run/` | 入库、上下文、状态复用、验收报告与测试日志 |

## 3. 环境与依赖

推荐环境：**Linux（含 WSL2 Ubuntu）**。示例在 WSL2 Ubuntu 26.04 上验证。

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.12.16 | 运行时 |
| uv | 0.13.7 | 依赖与虚拟环境管理 |
| pyseekdb | 1.4.0.post1 | 嵌入式 seekdb，无需 Docker 或独立数据库进程 |
| openai | 2.54.0 | 调用 MiniMax 的 OpenAI 兼容接口 |
| httpx | 0.28.1 | 调用 PowerContext HTTP API |
| pytest | 8.4.2 | 目标测试与回归测试 |
| PowerContext | 1.5.0 | 任务状态持久化与恢复 |
| MiniMax 模型 | `MiniMax-M2.5` | 生成代码补丁 |

安装：

```bash
cd minimax
uv sync --extra dev

# PowerContext CLI（只需一次）
uv tool install powercontext==1.5.0
export PATH="$HOME/.local/bin:$PATH"   # uv tool 的默认安装目录
```

## 4. 配置

### 4.1 项目配置

```bash
cd minimax
cp .env.example .env
```

编辑 `.env`：

```dotenv
POWERCONTEXT_URL=http://127.0.0.1:18080
POWERCONTEXT_SCOPE_ID=

MINIMAX_API_KEY=<你的 MiniMax API Key>
MINIMAX_BASE_URL=https://api.minimax.io/v1   # 中国区可改为 https://api.minimax.cn/v1
MINIMAX_MODEL=MiniMax-M2.5
MINIMAX_TEMPERATURE=0.2

SDD_DB_PATH=artifacts/seekdb
SDD_DB_NAME=sdd_context
SDD_COLLECTION=sdd_documents
SDD_PROJECT_DIR=demo_project
SDD_ARTIFACTS_DIR=artifacts
```

`POWERCONTEXT_SCOPE_ID` 留空时自动使用 PowerContext 的 default Scope。

### 4.2 启动 PowerContext

```bash
cp powercontext.env.example powercontext.env
powercontext server run --env-file powercontext.env
```

默认监听 `127.0.0.1:18080`，数据保存在 PowerContext 自己的 home 目录
（Linux 默认 `~/.local/share/powercontext/powercontext.db`）。健康检查：

```bash
curl http://127.0.0.1:18080/health/live
# {"status":"ok"}
```

### 4.3 数据库路径

默认 `SDD_DB_PATH=artifacts/seekdb`。嵌入式 seekdb 会对数据文件执行 `fallocate`，
因此数据库目录必须位于支持该操作的文件系统上：

- 正常 Linux 文件系统（ext4/xfs/btrfs 等）直接用默认值即可；
- 如果仓库放在 WSL 的 `/mnt/c`、`/mnt/z` 等 Windows 挂载盘上，需要把数据库放到 Linux 原生路径：

```bash
export SDD_DB_PATH="$HOME/.sdd_context/seekdb"
```

## 5. 数据初始化与入口

所有命令均在 `minimax/` 目录执行。

```bash
# 1) 入库：规格、代码、测试 -> seekdb
uv run python -m sdd_context ingest

# 2) 查看库内统计
uv run python -m sdd_context stats

# 3) 检索任务上下文（不依赖 PowerContext）
uv run python -m sdd_context context \
  --task "Implement tag filtering and limit validation in search_books per R2-R5" \
  --task-id demo-task

# 4) 入库 + 检索 + 把任务状态写入 PowerContext
uv run python -m sdd_context run \
  --task "Implement tag filtering and limit validation in search_books per R2-R5" \
  --task-id demo-task

# 5) 在一个全新的进程中恢复状态并重建上下文
uv run python -m sdd_context resume --task-id demo-task

# 6) 让 MiniMax 基于 before 快照生成补丁并写回项目
uv run python -m sdd_context generate \
  --task "Implement tag filtering and limit validation in search_books per R2-R5" \
  --task-id demo-task \
  --base artifacts/before/search.py \
  --apply
```

`run` / `resume` 需要 PowerContext 正在运行；`generate` 需要 `MINIMAX_API_KEY`。
`context` 与 `ingest` 只依赖 seekdb。

### 一键验收

```bash
./verify.sh
```

`verify.sh` 会依次执行：干净入库 → 改动前测试 → 上下文检索 → 规格更新/重新入库 →
PowerContext 状态保存与跨进程恢复 → MiniMax 生成补丁 → 改动后测试 → 证据链落盘。
如果第一次生成的代码没有通过测试，脚本会把失败日志回传给 MiniMax 再试一次
（默认最多 2 次，可用 `--max-attempts N` 调整）。
没有配置 MiniMax Key 时可执行 `./verify.sh --skip-minimax`，此时 MiniMax 相关项会标记为失败。

验收脚本使用独立的 seekdb 目录：文件系统支持 `fallocate` 时使用
`artifacts/run/verify/seekdb`，否则回退到系统临时目录；每次运行前清空，保证“从空入库”。

## 6. 测试命令

```bash
# 全部测试（13 个）
uv run --extra dev pytest -q demo_project

# 单独运行
uv run --extra dev pytest -q demo_project/tests/test_search_target.py
uv run --extra dev pytest -q demo_project/tests/test_search_regression.py
```

复现“改动前失败”：

```bash
cp artifacts/before/search.py demo_project/bookvault/search.py
uv run --extra dev pytest -q demo_project/tests/test_search_target.py      # 6 failed
uv run --extra dev pytest -q demo_project/tests/test_search_regression.py  # 6 passed
cp artifacts/after/search.py demo_project/bookvault/search.py
```

目标测试的失败原因都是 `AssertionError`（行为不符合规格），不是导入错误或环境错误。

## 7. 验收证据

| 验收点 | 证据文件 |
| --- | --- |
| 可运行、依赖与步骤 | 本 README、`pyproject.toml`、`uv.lock` |
| MiniMax 实际参与且开发记录与 diff 一致 | `artifacts/dev_record/dev_record.md`、`minimax_request.json`、`minimax_response.json`、`minimax_meta.json`、`artifacts/changes.patch` |
| 上下文正确、真实来源、规格更新后重新入库生效 | `artifacts/run/context.json`、`artifacts/run/verification.json` 中的 `spec_update_reingest` |
| seekdb 真实存储与查询 | `artifacts/run/ingest.json`、`verification.json` 中的 `seekdb_ingest_before` 与 `context_retrieval.db_query_log` |
| 任务状态可从空保存并在模块重启后可读复用 | `artifacts/run/verification.json` 中的 `state_reuse`、`artifacts/run/resume.json`、`artifacts/run/resume_after_server_restart.json` |
| 目标测试改动前失败、改动后通过；回归测试前后通过；测试集不变 | `artifacts/run/verify/tests_*.log`、`artifacts/test_and_spec_hashes.txt`、`verification.json` 中的 `tests_before` / `tests_after` |

`artifacts/run/verification.json` 是总报告，`criteria` 下每一项都有 `pass` 布尔值；
`overall_pass=true` 表示六项验收全部满足。

## 8. 已知限制

1. **嵌入式 seekdb 的 `fallocate` 要求**：不要把数据库目录放在 WSL 的 Windows 挂载盘；
   如遇 `seekdb_open failed`，设置 `SDD_DB_PATH` 到 Linux 原生路径。
2. **MiniMax Key 必需**：没有 Key 时 `generate` 与完整 `verify.sh` 无法完成 MiniMax 验收项。
3. **离线哈希向量**：为了在干净环境零下载运行，检索使用 384 维确定性哈希向量，
   并与全文过滤、组件归并、需求编号加权组合；它不是语义模型向量，召回以关键词为主。
4. **单文件补丁**：当前生成流程面向单个目标文件（示例为 `bookvault/search.py`）。
   跨文件改动可以扩展 `patchgen.py`，但不在本次提交范围。
5. **本地 PowerContext 关闭鉴权**：`powercontext.env.example` 使用
   `POWERCONTEXT_SERVER_ACCESS_MODE=disabled`，仅用于本地演示；生产环境应开启鉴权。
6. **模型输出校验**：`updated_file` 必须是合法 Python；不合法会直接报错而不会写坏工程。
7. **模型版本**：竞赛说明中的 `MiniMax-M2.1` 已被 MiniMax 官方下线（聊天接口返回 2069），
   本次改用账号可用且输出稳定的 `MiniMax-M2.5`；生成流程、开发记录和一致性校验不变。

## 9. 评分自检

| # | 要求 | 实现 | 状态 |
| --- | --- | --- | --- |
| 1 | 按说明在干净环境可运行 | `uv sync` + `ingest` + `verify.sh`；依赖版本固定 | 已完成 |
| 2 | MiniMax 实际参与，开发记录与代码 diff 一致 | 模型响应原始文件、提示词、`updated_file` 哈希、patch 哈希、diff 一致性校验 | 已完成（真实调用 `MiniMax-M2.5`，1 次通过；四项一致性校验全为 true） |
| 3 | 上下文来源真实，规格更新后重新入库生效 | AST/Markdown 切分，路径与行号来自真实文件；`spec_update_reingest` 步骤 | 已完成（自动验证） |
| 4 | seekdb 真实存储和查询上下文材料 | 30 个文档入库；全文 `get` + 向量 `query`；查询日志落盘 | 已完成（自动验证） |
| 5 | 状态从空保存，模块重启后可读复用 | PowerContext Atomic Memory；全新进程 `resume` 校验上下文哈希 | 已完成（自动验证） |
| 6 | 目标测试前失败后通过；回归前后通过；测试集不变 | 改动前 6 个目标测试 `AssertionError`；改动后 13 个全通过；测试文件 SHA-256 前后一致 | 已完成（测试信号自动验证） |

## 10. 提交说明

- 开发基线：`https://github.com/oceanbase/powercontext`，分支 `2026-competition-ecosystem`
- 提测仓库：`https://github.com/NUDT-23/powercontext`，同名分支 `2026-competition-ecosystem`
- 提交目录：`minimax/`（本目录）
- 测评平台提交时填写**提测仓库同名分支上的 commit hash**。

不要提交以下本地文件：`.env`、`powercontext.env`、`.venv/`、`artifacts/seekdb/`、
`artifacts/run/verify/seekdb/`。它们已经在 `.gitignore` 中。

推送前建议执行：

```bash
cd <你的 NUDT-23/powercontext 克隆目录>
git status --short
cp -a <本目录> minimax/          # 或直接把 minimax/ 内容拷贝进来
git add minimax
git commit -m "feat(minimax): add SDD context module with seekdb and PowerContext"
git push origin 2026-competition-ecosystem
git rev-parse HEAD
```

最后把 `git rev-parse HEAD` 输出的 commit hash 填到测评平台。
