# Qoder 开发记录（截图版）

赛题接受“对话截图**或**录屏”，本项目采用截图。每张截图需能看出 Qoder 界面、会话内容和实际效果，不要裁剪掉账号与时间信息。

## 截图要求

- 截整个 Qoder 窗口：能同时看到会话标题/时间、你的输入、Qoder 的回答或代码 diff
- 每张图对应一个真实开发动作，最好带可验证结果（运行输出、页面效果、终端报错修复前后）
- 不要出现真实 API Key；如出现请打码
- 命名：`qoder-01-<功能>.png`，按开发时间顺序编号

## 建议清单

| # | 功能 | 截图里应包含 | 文件名 | 状态 |
| --- | --- | --- | --- | --- |
| 01 | 项目与 PowerContext Scope | 创建项目的需求 + Qoder 生成的初始化代码/接口调用 | `qoder-01-project-scope-1.png`、`qoder-01-project-scope-2.png` | 已拍 |
| 02 | PDF / arXiv 导入 | 解析、分块、入库的实现过程或运行结果 | `qoder-02-ingest-1.png`、`qoder-02-ingest-2.png`、`qoder-02-ingest-3.png` | 已拍 |
| 03 | seekdb 混合检索 | `hybrid_search` + RRF 的实现对话，或检索结果与 trace | `qoder-03-hybrid-search-1.png`、`qoder-03-hybrid-search-2.png`、`qoder-03-hybrid-search-3.png` | 已拍 |
| 04 | 记忆召回 | 检索前召回偏好、界面展示“本次召回的记忆” | `qoder-04-memory-recall-1.png`、`qoder-04-memory-recall-2.png`、`qoder-04-memory-recall-3.png` | 已拍 |
| 05 | 记忆开关对比 | 同一问题开/关记忆的输出差异 | `qoder-05-memory-toggle-1.png`、`qoder-05-memory-toggle-2.png` | 已拍 |
| 06 | 综述与引用 | 生成对比表、`[P#]` 引用、SSE 流式输出 | `qoder-06-synthesis-1.png`、`qoder-06-synthesis-2.png`、`qoder-06-synthesis-3.png`、`qoder-06-synthesis-4.png` | 已拍 |
| 07 | 反馈与使用统计 | 反馈写入、统计页或 events 表 | `qoder-07-stats-1.png`、`qoder-07-stats-2.png`、`qoder-07-stats-3.png`、`qoder-07-stats-4.png` | 已拍 |
| 08 | 架构分析与改动清单 | 阅读 README/前后端源码，输出职责边界与 P0/P1 改动清单 | `qoder-08-analysis.png`、`qoder-08-analysis-changes.png`、`qoder-08-analysis-session.png` | 已拍 |
| 09 | 引用校验 | 解析 `[P#]`、越界引用提示的实现对话 | `qoder-09-citation-check.png`、`qoder-09-citation-check-plan.png`、`qoder-09-citation-check-plan-detail.png` | 已拍 |
| 10 | Markdown 导出 | 导出按钮实现与下载结果 | `qoder-10-export.png`、`qoder-10-export-plan.png` | 已拍 |
| 11 | Qoder Sites 发布 | 在 Qoder 中发布 `site/`，设为公开并拿到域名 | `qoder-11-site-publish.png` | 已拍 |
| 12 | 联调与修复 | 一个真实 bug（如并发 500）的定位与修复对话 | `qoder-12-fix-1.png`、`qoder-12-fix-2.png`、`qoder-12-fix-3.png` | 已拍 |

## 对应关系

| 日期 | 功能 | 我的需求（Qoder 输入摘要） | Qoder 完成的工作 | 对应 commit | 截图 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-06 | 架构分析 | 不改代码，阅读 README、`backend/app/`、`frontend/src/`，输出架构与请求数据流、两项技术的职责边界、最薄弱的 3 个点、最小改动清单 | 并行阅读前后端源码，梳理 seekdb 检索与 PowerContext 记忆的调用链，给出按 P0/P1 排序的改动清单 | `0ee6ac9` | `qoder-08-analysis.png`、`qoder-08-analysis-changes.png`、`qoder-08-analysis-session.png` |
| 2026-11-06 | 引用校验 | 解析最终答案里的 `[P#]`，只允许 `1..所选文献数`；非法编号通过 SSE `done` 的 `invalid_citations` 返回，前端在结果上方提示 | `synth_service.py` 增加 `validate_citations`，`api.ts` 扩展事件类型，`App.tsx` 渲染警告；验证 `[P0]`、`[P4]` 被正确判为越界 | `0ee6ac9` | `qoder-09-citation-check.png`、`qoder-09-citation-check-plan.png`、`qoder-09-citation-check-plan-detail.png` |
| 2026-11-06 | Markdown 导出 | 在综述结果区域增加「导出 Markdown」按钮，把当前 output 下载为带时间戳的 `.md`；纯前端实现，不改后端 | 先给出改动范围与导出内容结构，再在 `App.tsx` 实现 `exportMarkdown`：拼装问题、时间、耗时、引用文献与正文，通过 Blob 触发下载 | `0ee6ac9` | `qoder-10-export.png`、`qoder-10-export-plan.png` |
| 2026-11-06 | Qoder Sites 发布 | 用 Qoder Sites 发布 `site/` 静态站点，保持内容与视觉不变，设为「任何人都可访问」，返回公开网址 | 读取 `site/` 目录与发布参考，复制到会话目录、生成预览草稿、设为 public 后发布 | `3aeb48c` | `qoder-11-site-publish.png` |
| 2026-11-06 | 项目与 Scope 核验 | 只读核验创建项目时如何初始化 PowerContext Scope、`scope_id` 写回哪里，并实际查询 demo 项目与记忆 | 读取 `routes.py`，执行 `curl /api/projects` 与 `/api/memory?project_id=demo`，确认 `scope_id=scp_33fe…` 且 4 条偏好记忆挂在同一 Scope 下 | —（只读核验） | `qoder-01-project-scope-1.png`、`qoder-01-project-scope-2.png` |
| 2026-11-06 | 导入链路核验 | 只读核验 arXiv/PDF 从下载、解析、分块、embedding 到 `collection.add` 的链路，并实际查询健康状态与 demo 文献 | 读取 `ingest.py`、`routes.py`、`seekdb_store.py`，执行 `/api/health` 与 `/api/papers?project_id=demo`，确认 `paper_chunks`、`text-embedding-v3`、demo 20 篇/全局 260 篇 | —（只读核验） | `qoder-02-ingest-1.png`、`qoder-02-ingest-2.png`、`qoder-02-ingest-3.png` |
| 2026-11-06 | 混合检索核验 | 只读核验 `hybrid_search` 的 query/knn/where/RRF 分工，并对比带关键词/年份过滤与不带过滤的两次检索 | 实际执行两次 `/api/search`，对比 Request A（keyword+year_min）与 B 的结果与耗时；读取 `seekdb_store.py:220-251` 解释 RRF 融合 | —（只读核验） | `qoder-03-hybrid-search-1.png`、`qoder-03-hybrid-search-2.png`、`qoder-03-hybrid-search-3.png` |
| 2026-11-06 | 记忆召回核验 | 只读核验检索前如何用 `search_memory` + `prepare` 召回记忆，并实际查询 demo 记忆与带记忆检索的结果 | 读取 `search_service.py`，执行 `/api/memory` 与带 `memory_enabled:true` 的 `/api/search`；遇到 Windows curl 引号问题后改用临时文件重试成功，展示 `used_memories` 与 `<powercontext_prepared_context>` | —（只读核验） | `qoder-04-memory-recall-1.png`、`qoder-04-memory-recall-2.png`、`qoder-04-memory-recall-3.png` |
| 2026-11-06 | 记忆开关 A/B | 同一 query 分别关闭/开启 `memory_enabled`，比较召回与输出差异 | 实际执行两次 `/api/search`；首次因中文 body 编码失败改用文件传递 JSON 后成功。A 召回 0 条、B 召回 1 条偏好，耗时 15.51ms → 120.39ms，排序不变 | —（只读核验） | `qoder-05-memory-toggle-1.png`、`qoder-05-memory-toggle-2.png` |
| 2026-11-06 | 综述与引用核验 | 只读核验：从 `/api/papers` 取前 3 篇 id，读 `synth_service.py` 说明 meta/delta/done 字段与 `validate_citations` 合法范围，再实际调用 `/api/synthesize` 取 meta、正文引用与 done | 读取 `synth_service.py:145-154/160-165/196-201` 并给出三类事件字段；`validate_citations:103-108` 合法范围为 `1..paper_count`。实际调用返回 meta 的 P1 `d0b484aa…`、P2 `3a24c0d0…`、P3 `cac9d294…`，`used_memories=[]`、`memory_context=""`；正文 2584 字含 `[P1][P2][P3]`；done 为 `latency_ms=11308, chars=2584, invalid_citations=[]` | —（只读核验） | `qoder-06-synthesis-1.png`、`qoder-06-synthesis-2.png`、`qoder-06-synthesis-3.png`、`qoder-06-synthesis-4.png` |
| 2026-11-06 | 反馈与使用统计核验 | 只读核验反馈写入链路：读 `routes.py` 的 feedback/stats 与 `seekdb_store.py` 的 add_feedback/log_event/stats，实际 POST 一条反馈后对比 `/api/stats` 与 `/api/memory` | 给出写入路径：`feedback` 表（routes.py:320-327 / seekdb_store.py:354-367）、`events` 表（routes.py:328-330 / seekdb_store.py:339-352）、PowerContext `kind=feedback`（routes.py:331-347）。实测反馈前 `feedback.count=0`；POST 评分 5、relevant=true 后返回 `{"ok": true}`，`events` 新增 `action=feedback` 一条、`feedback.count` 0→1，`recent_events[0]` 即本次反馈，`users=1`（qoder-review）；`/api/memory` 新增 kind=feedback 记忆「用户认为该结果相关；反馈：对比表清晰，引用可追溯，希望补充数据集规模对比」 | —（只读核验） | `qoder-07-stats-1.png`、`qoder-07-stats-2.png`、`qoder-07-stats-3.png`、`qoder-07-stats-4.png` |
| 2026-11-06 | 联调与修复（跨项目文献泄漏） | 真实 bug：`POST /api/synthesize` 的 `paper_ids` 混入其他项目文献时仍被接受，`meta.papers` 返回不属于 `project_id` 的论文。要求 Qoder 定位根因、最小改动、重建并验证 | 根因：`synth_service.py:140` 调 `get_papers_by_ids(paper_ids)` 未按项目过滤。修复：`seekdb_store.py:178-192` 增加可选 `project_id` 参数并在 SQL 追加 `AND project_id = %s`，`synth_service.py:140` 传入 `project_id`，无匹配时返回「文献不属于该项目」。实测：混合请求（2 篇 demo + trial-01 的 AgentLAB）meta 只剩 2 篇 demo；3 篇 demo 正常请求仍返回 3 篇；`python -m app.verify` 8 项 PASS | `待填` | `qoder-12-fix-1.png`、`qoder-12-fix-2.png`、`qoder-12-fix-3.png` |

补充：

- Qoder 账号 UID：`nick049570947`
- Qoder 使用版本：`桌面端（Qoder CN）`
- Qoder Sites 站点：<https://paperlens-5efj7ylekjq.qoder.zone/>（未登录可访问）

## 拍摄建议

- 在 Qoder 里实际做这些功能时顺手截图，比事后集中补拍更真实
- 一张图只讲一件事；关键提示词和 Qoder 的关键回答要同框
- 截完立刻填上面的对应表，避免之后对不上 commit
