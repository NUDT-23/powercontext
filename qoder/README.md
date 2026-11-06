# PaperLens · 文澜

> 面向科研文献的**混合检索 + 记忆增强综述**工作台  
> Qoder × OceanBase 2026 参赛作品

PaperLens 解决科研人员在大量文献中「找不准、比不快、写不成」的问题：

1. **混合检索**：seekdb 在**同一次查询**内完成向量语义检索、全文关键词检索与元数据过滤，再用 RRF 融合排序；每条结果带回命中的原文片段与页码。
2. **长期记忆**：PowerContext 保存你的语言/风格偏好、研究关注点、已读进度与「相关/不相关」反馈，在检索与综述前自动召回；界面上提供**记忆开关**做 A/B 对比。
3. **综述生成**：勾选多篇文献，生成「问题—方法—数据—结论—局限」对比与综述初稿，每条结论强制标注 `[P#]` 文献引用；生成后自动校验引用编号并提示越界引用，支持 SSE 流式输出与 Markdown 导出。
4. **证据留痕**：每次检索与记忆读写都写入 JSONL trace，使用事件与反馈进入 SQL 表，可一键导出验收证据。

---

## 一键启动

### 环境要求

| 依赖 | 说明 |
|---|---|
| Docker Desktop（启用 WSL2 后端） | seekdb 嵌入式引擎与 PowerContext 服务均为 Linux 运行时，**Windows 必须通过 Docker/WSL2** |
| 8 GB+ 可用内存 | 首次构建需要下载 Node、Python 与模型依赖 |
| OpenAI 兼容 API Key（可选） | 不配置时自动降级为本地嵌入模型 + 离线抽取式综述，全链路仍可运行 |

### 步骤

```bash
cp .env.example .env       # Windows 可在 Git Bash / WSL 中执行
# 编辑 .env，填入 OPENAI_API_KEY（DashScope、DeepSeek、OpenAI 均可，需兼容 /chat/completions 与 /embeddings）

docker compose up --build -d
```

首次构建约 5–10 分钟。启动完成后：

| 地址 | 用途 |
|---|---|
| http://localhost:8080 | PaperLens 主应用 |
| http://localhost:8080/api/health | 健康状态（seekdb / PowerContext / LLM） |
| http://localhost:8001 | PowerContext 服务（诊断用，前端不直接访问） |

### 载入演示语料

```bash
make seed        # 导入 20 篇 arXiv 公开文献（LLM Agent × 因果推断主题）到 demo 项目
```

### 自动验收

```bash
make verify      # 跑通全链路断言，输出 evidence/verification/
make evidence    # 导出使用统计、反馈、记忆快照与 trace 到 evidence/
```

> 没有 `make`（例如 Windows Git Bash 默认不带）时，使用等价命令：
> `docker compose exec -T app python -m app.seed`、`python -m app.verify`、`python -m app.export_evidence`。

`make verify` 断言的内容：

1. 健康检查通过，seekdb 中论文数 ≥ 20、分块索引可查
2. 混合检索返回带引用片段的结果，RRF 排序生效
3. 标量过滤（`year >= 2025`）确实收窄候选集
4. 向 PowerContext 写入记忆后，`atomic-memory/search` 能召回
5. 综述 SSE 依次返回 `meta → delta → done`，且带引用
6. `seekdb_search_trace.jsonl` 与 `powercontext_trace.jsonl` 字段完整，包含 `remember` 与 `search_memory` 操作

---

## 项目网站（Qoder Sites）

展示站源码在 `site/`，纯静态 HTML/CSS/JS，无外部 CDN 依赖，可由 Qoder Sites 直接发布：

```bash
python -m http.server 8090 --directory site
# 打开 http://localhost:8090
```

站点包含项目简介、解决的痛点、核心功能、真实界面截图、seekdb / PowerContext 分工、验收数据、运行说明、Qoder 开发记录与仓库链接。发布后的公开地址填写在此处：`<待发布>`。

---

## 配置说明

关键环境变量（完整见 `.env.example`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `OPENAI_BASE_URL` | DashScope 兼容端点 | OpenAI 兼容 API 基址 |
| `OPENAI_API_KEY` | 空 | 留空则进入离线模式 |
| `LLM_MODEL` | `qwen-plus` | 综述生成模型 |
| `EMBEDDING_MODEL` | `text-embedding-v3` | 嵌入模型 |
| `EMBEDDING_DIM` | `1024` | **必须与模型维度一致**；更换模型需 `make reset` 重建 collection |
| `EMBEDDING_PROVIDER` | `auto` | `openai` / `local`（all-MiniLM-L6-v2，384 维）/ `auto` |
| `POWERCONTEXT_URL` | `http://powercontext:8000` | 容器内服务地址 |
| `DATA_DIR` | `/data` | seekdb 数据、嵌入缓存与 trace 的根目录 |

> 离线模式（`EMBEDDING_PROVIDER=local` 或不填 Key）使用 `sentence-transformers/all-MiniLM-L6-v2`，首次启动会通过 `HF_ENDPOINT` 镜像下载模型；综述退化为**确定性抽取式**结果，仍带引用与记忆注入，便于无 Key 场景演示。

---

## 架构

```
React 18 + Vite（构建后由 FastAPI 托管静态资源）
        │  REST / SSE
FastAPI 后端
   ├── seekdb（pyseekdb 嵌入式）    论文元数据、分块、向量/全文/标量混合检索
   ├── PowerContext Server（Docker）Scope / Memory / PreparedContext
   └── OpenAI 兼容 API               LLM 生成 + Embedding
Docker Compose：app + powercontext
```

### seekdb 数据设计

- SQL 表：`projects`、`papers`、`events`（使用日志）、`feedback`
- 检索集合 `paper_chunks`：
  - `id = {paper_id}#{chunk_idx}`
  - `document` = 段落正文
  - `metadata` = `paper_id, project_id, title, authors, year, venue, arxiv_id, section, page, read_status, tags`
- 检索核心：`collection.hybrid_search(query={where_document, where, n_results}, knn={query_texts, where, n_results}, rank={"rrf": {}}, n_results)`

### PowerContext 记忆设计

- 每个项目一个 Scope，`scope_id` 存回应用库
- 记忆类型：`preference / interest / negative-interest / progress / focus / decision`
- 写入：`/v1/memory/remember`；检索：`/v1/atomic-memory/search`；生成前召回：`/v1/context/prepare`
- 记忆可查看、修正、遗忘（`/v1/atomic-memory/lifecycle`），所有操作留 trace

### 证据链

| 评分项 | 证据位置 |
|---|---|
| 技术结合 | `evidence/seekdb/seekdb_search_trace.jsonl`、`evidence/powercontext/powercontext_trace.jsonl` |
| 使用效果 | `evidence/usage/events.csv`、`feedback.csv`、`stats.json`，以及应用内「使用统计」页 |
| 完成度 | `evidence/verification/verify_report.md`、`evidence/demo/ui-*.png`（各页面截图）、演示视频 |
| 工程质量 | 本 README、`docker compose up` 一键启动、`make verify` 自动断言 |
| Qoder 开发实践 | `evidence/qoder/`（对话截图、录屏、UID、commit 对应表） |

---

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/projects` | 创建项目并初始化 PowerContext Scope |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/papers?project_id=` | 文献列表 |
| POST | `/api/papers/import_arxiv` | 通过 arXiv 链接/编号导入 |
| POST | `/api/papers/upload` | 上传 PDF，自动解析分块入库 |
| PATCH | `/api/papers/{id}/read` | 标记阅读进度（写入记忆） |
| POST | `/api/search` | 混合检索，返回 chunks + `used_memories` |
| POST | `/api/synthesize` | SSE 流式综述/对比 |
| GET | `/api/memory?project_id=` | 列出长期记忆 |
| POST | `/api/memory/remember` | 写入记忆 |
| POST | `/api/memory/forget` | 遗忘记忆 |
| POST | `/api/feedback` | 提交相关/不相关反馈 |
| GET | `/api/stats?project_id=` | 使用统计 |
| GET | `/api/health` | 健康状态 |

---

## 目录结构

```
qoder/
├── docker-compose.yml
├── .env.example
├── Makefile                    # up / seed / verify / evidence / reset
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI 入口、静态站点托管
│       ├── routes.py           # REST + SSE 路由
│       ├── seekdb_store.py     # pyseekdb 封装、混合检索、trace
│       ├── powercontext.py     # PowerContext HTTP 客户端、trace
│       ├── embedding.py        # OpenAI 兼容 / 本地嵌入
│       ├── llm.py              # LLM 客户端（流式）
│       ├── ingest.py           # arXiv 抓取、PDF 解析、分块
│       ├── search_service.py   # 记忆增强检索编排
│       ├── synth_service.py    # 记忆增强综述编排
│       ├── seed_data.py        # 演示语料导入
│       ├── verify.py           # 自动验收
│       └── export_evidence.py  # 证据导出
├── frontend/
│   └── src/{App.tsx, api.ts, styles.css}
├── seed/papers.json            # 20 篇 arXiv 公开文献元数据
├── scripts/                    # 语料抓取等辅助脚本
├── site/                       # Qoder Sites 展示站（静态）
└── evidence/                   # 验收证据输出
```

---

## 常见问题

**Q：拉取 `python:3.11-slim` / `node:20-slim` 超时或失败？**  
Docker Hub 在部分网络不可达。可先从镜像站拉取并改回原名，再执行 `docker compose up --build`：

```bash
docker pull docker.m.daocloud.io/library/python:3.11-slim
docker pull docker.m.daocloud.io/library/node:20-slim
docker tag docker.m.daocloud.io/library/python:3.11-slim python:3.11-slim
docker tag docker.m.daocloud.io/library/node:20-slim node:20-slim
```

**Q：`docker compose up` 后应用一直重启？**  
看 `docker compose logs app`。常见原因是 `.env` 中 `EMBEDDING_DIM` 与实际模型不符，或 `OPENAI_BASE_URL` 不可达。可先置空 `OPENAI_API_KEY` 使用离线模式验证链路。

**Q：Windows 上能直接 `pip install` 运行吗？**  
不能。seekdb 嵌入式后端与 PowerContext 服务均依赖 Linux 运行时，请使用 Docker Desktop（WSL2 后端）。

**Q：换了嵌入模型后检索结果异常？**  
向量维度与旧 collection 不一致。执行 `make reset` 清空数据卷后重新 `make seed`。

**Q：没有 API Key 能验收吗？**  
可以。离线模式使用本地嵌入模型与抽取式综述，混合检索、记忆读写、trace、统计全部可用；只是综述文本质量不如 LLM 模式。

**Q：如何重置所有数据？**  
`make reset`（会删除 Docker 数据卷）。

---

## 参赛信息

- 赛题：OceanBase 2026「Qoder × OceanBase」
- 提交分支：`2026-competition-ecosystem`，作品目录 `qoder/`
- 开发工具：Qoder（核心功能开发记录见 `evidence/qoder/`）
- 技术底座：seekdb（混合检索）+ PowerContext（长期记忆）
