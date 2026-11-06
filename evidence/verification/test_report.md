# PaperLens 测试结果报告

- 报告日期：2026-11-06
- 测试版本：`9973c13`（`2026-competition-ecosystem`）
- 自动验收结论：**8 / 8 PASS**
- 真实用户试用：**待执行**（当前有效真人样本 0，本报告不包含虚构的问卷与耗时数据）

## 一、测试环境

| 项目 | 配置 |
| --- | --- |
| 操作系统 | Windows 11 Home China 10.0.26200，Docker Desktop（WSL2 后端） |
| 应用服务 | `paperlens-app-1`：FastAPI + 静态前端，监听 8080 |
| 记忆服务 | `paperlens-powercontext-1`：PowerContext Server，监听 8001 |
| 检索底座 | pyseekdb 嵌入式 seekdb，collection `paper_chunks` |
| 嵌入模型 | 本地 `all-MiniLM-L6-v2`（384 维，CPU） |
| 生成模型 | OpenAI 兼容 LLM（DeepSeek `deepseek-chat`，流式） |
| 演示语料 | 20 篇 arXiv 公开文献，40 个分块 |
| 试用项目 | `trial-01`–`trial-12`，每人 20 篇 / 40 分块，共 260 篇 |

## 二、自动验收（`python -m app.verify`）

执行时间：2026-11-06 10:49（UTC+8）。

| # | 检查项 | 结果 | 实测数据 |
| --- | --- | --- | --- |
| 1 | 健康检查 | PASS | `seekdb` / `powercontext` / `llm` 均为 true，嵌入 `local:all-MiniLM-L6-v2` |
| 2 | 语料与索引 | PASS | demo 项目 20 篇文献，分块可查 |
| 3 | 混合检索 | PASS | 返回 7 条结果，耗时 372.7 ms |
| 4 | 标量过滤 | PASS | `year >= 2025` 后收窄为 6 条，年份分布 2026×4、2025×2 |
| 5 | 记忆写入 | PASS | 作用域内 5 条记忆 |
| 6 | 记忆召回 | PASS | 检索召回 2 条记忆，含检索偏好 |
| 7 | 综述流式生成 | PASS | 1,165 个 SSE 事件，1,953 字符，LLM 在线 |
| 8 | 审计 trace | PASS | seekdb 35 条、PowerContext 240 条；覆盖 `ensure_scope / remember / search_memory / prepare_context / forget_memory / list_memory / capture_source` |

原始输出：`evidence/verification/verify_report.md`、`verify_output.json`、`synthesis_events.json`。

## 三、功能与界面冒烟测试

使用无头 Edge（Chrome DevTools Protocol，1440×900）从真实界面操作，不是仅调接口。

| 场景 | 预期 | 实测 | 结论 |
| --- | --- | --- | --- |
| 普通入口 `/` | 默认进入 demo，且不暴露试用项目 | 项目列表仅 1 项，选中 `demo` | PASS |
| 试用入口 `/?u=U02` | 自动填入编号并选中对应项目 | 输入框 `U02`、localStorage `U02`、选中 `trial-02` | PASS |
| 界面混合检索 | 带年份过滤返回结果并展示召回记忆 | 7 条结果，“本次召回的记忆”区域可见，无错误提示 | PASS |
| 按人归属 | 检索与反馈写入 `user_name` | 以 `U01` 检索并反馈后，`stats.users=1`，事件 2 条、反馈 1 条 | PASS |
| 试用项目初始化 | 12 人各自独立项目与 Scope | 12 个项目各 20 篇 / 40 分块，`warnings=[]` | PASS |
| 证据导出 | 汇总 demo 与 trial 数据 | `manifest.json` 记录 71 条事件、0 反馈、试用用户 0（冒烟数据已主动清空） | PASS |

> 说明：冒烟测试产生的 U01/U02 记录已通过 `/api/dev/trial_reset` 清除，避免与真实试用数据混在一起。

## 四、性能数据（demo 项目，来自应用事件表）

| 指标 | 次数 | 平均耗时 | 备注 |
| --- | --- | --- | --- |
| 混合检索 | 33 | 489.1 ms | 本地 CPU 嵌入 + 向量/全文/RRF |
| 综述生成 | 23 | 4,156.7 ms | 依赖 LLM 网络，近期单次 5.8–12.8 s |
| 记忆写入 | 7 | - | PowerContext 显式写入 |
| 记忆遗忘 | 7 | - | 生命周期操作 |
| 用户反馈 | 0 | - | 真实试用阶段采集 |

解读：

- 检索延迟稳定在亚秒级，主要成本是本地嵌入；验收中单次 372.7 ms。
- 综述耗时波动来自外部 LLM，不代表检索链路；SSE 首包与增量输出正常。
- 当前 0 条反馈是尚未开展真人试用的直接结果，不是功能失败；接口与界面按钮均已在冒烟中验证。

## 五、技术生效证据

- **seekdb**：同一次请求内执行向量 KNN、全文关键词与元数据过滤，并用 RRF 融合；`seekdb_search_trace.jsonl` 记录查询、过滤条件、结果 id 与耗时。
- **PowerContext**：项目级 Scope；检索前召回偏好，综述前 `prepare_context`；`powercontext_trace.jsonl` 记录 `remember / search_memory / prepare_context / forget_memory`。
- **引用校验**：综述 SSE `done` 事件返回 `invalid_citations`；界面可提示越界 `[P#]`。
- **可复现**：`docker compose up --build -d` 一键启动，`python -m app.verify` 自动断言，`python -m app.export_evidence` 导出证据。

## 六、已知限制与待补项

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 10+ 名真实用户试用 | 待执行 | 试用入口、编号归属、独立项目已就绪；需按 `evidence/usage/trial/plan.md` 约人 |
| 问卷与前后耗时 | 待采集 | 模板见 `questionnaire.md` 与 `timing.csv` |
| 演示视频 | 待录制 | 建议按导入 → 检索 → 记忆开关 → 综述 → 导出 录制 3 分钟 |
| LLM 延迟 | 已知风险 | 外部网络波动会导致 5–13 s 等待，现场需记录并重试一次 |
| 局域网访问 | 待现场确认 | 本机通过 `192.168.220.55:8080` 访问正常；其他设备若失败需放行防火墙 8080 |

## 七、结论

- 功能链路、seekdb 混合检索、PowerContext 记忆读写、SSE 综述与证据导出均通过自动与界面测试。
- 当前材料可以证明**技术结合与完成度**；**使用效果**证据仍需 10 名以上真实用户完成后补齐。
- 本报告中的所有数字均可在对应 JSON / CSV / trace 文件中复核，未使用估算或虚构数据。

## 八、证据索引

| 文件 | 内容 |
| --- | --- |
| `evidence/verification/verify_report.md` | 自动验收 8 项结果 |
| `evidence/verification/synthesis_events.json` | 综述 SSE 原始事件 |
| `evidence/seekdb/seekdb_search_trace.jsonl` | 混合检索 trace |
| `evidence/powercontext/powercontext_trace.jsonl` | 记忆读写 trace |
| `evidence/usage/stats.json` | 使用统计 |
| `evidence/usage/events.csv` / `feedback.csv` | 事件与反馈明细 |
| `evidence/usage/trial/trial_summary.json` | 试用用户汇总（当前为空，待真人试用） |
