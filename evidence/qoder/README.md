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
| 01 | 项目与 PowerContext Scope | 创建项目的需求 + Qoder 生成的初始化代码/接口调用 | `qoder-01-project-scope.png` | 待拍 |
| 02 | PDF / arXiv 导入 | 解析、分块、入库的实现过程或运行结果 | `qoder-02-ingest.png` | 待拍 |
| 03 | seekdb 混合检索 | `hybrid_search` + RRF 的实现对话，或检索结果与 trace | `qoder-03-hybrid-search.png` | 待拍 |
| 04 | 记忆召回 | 检索前召回偏好、界面展示“本次召回的记忆” | `qoder-04-memory-recall.png` | 待拍 |
| 05 | 记忆开关对比 | 同一问题开/关记忆的输出差异 | `qoder-05-memory-toggle.png` | 待拍 |
| 06 | 综述与引用 | 生成对比表、`[P#]` 引用、SSE 流式输出 | `qoder-06-synthesis.png` | 待拍 |
| 07 | 反馈与使用统计 | 反馈写入、统计页或 events 表 | `qoder-07-stats.png` | 待拍 |
| 08 | 联调与修复 | 一个真实 bug（如并发 500）的定位与修复对话 | `qoder-08-fix.png` | 待拍 |
| 09 | 引用校验 | 解析 `[P#]`、越界引用提示的实现对话 | `qoder-09-citation-check.png` | 已拍 |
| 10 | Markdown 导出 | 导出按钮实现与下载结果 | `qoder-10-export.png` | 已拍 |

## 对应关系

| 日期 | 功能 | 我的需求（Qoder 输入摘要） | Qoder 完成的工作 | 对应 commit | 截图 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-06 | 架构分析 | 不改代码，阅读 README、`backend/app/`、`frontend/src/`，输出架构与请求数据流、两项技术的职责边界、最薄弱的 3 个点、最小改动清单 | 并行阅读前后端源码，梳理 seekdb 检索与 PowerContext 记忆的调用链，给出按 P0/P1 排序的改动清单 | `__BASELINE__` | `qoder-08-analysis.png` |
| 2026-11-06 | 引用校验 | 解析最终答案里的 `[P#]`，只允许 `1..所选文献数`；非法编号通过 SSE `done` 的 `invalid_citations` 返回，前端在结果上方提示 | `synth_service.py` 增加 `validate_citations`，`api.ts` 扩展事件类型，`App.tsx` 渲染警告；验证 `[P0]`、`[P4]` 被正确判为越界 | `__BASELINE__` | `qoder-09-citation-check.png`、`qoder-09-citation-check-plan.png` |
| 2026-11-06 | Markdown 导出 | 在综述结果区域增加「导出 Markdown」按钮，把当前 output 下载为带时间戳的 `.md`；纯前端实现，不改后端 | `App.tsx` 实现 `exportMarkdown`：拼装问题、时间、耗时、引用文献与正文，通过 Blob 触发下载 | `__BASELINE__` | `qoder-10-export.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-01-project-scope.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-02-ingest.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-03-hybrid-search.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-04-memory-recall.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-05-memory-toggle.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-06-synthesis.png` |
| 2026-11-__ |  |  |  | `<hash>` | `qoder-07-stats.png` |

补充：

- Qoder 账号 UID：`nick049570947`
- Qoder 使用版本：`桌面端（Qoder CN）`
- Qoder Sites 站点：`<公开链接>`

## 拍摄建议

- 在 Qoder 里实际做这些功能时顺手截图，比事后集中补拍更真实
- 一张图只讲一件事；关键提示词和 Qoder 的关键回答要同框
- 截完立刻填上面的对应表，避免之后对不上 commit
