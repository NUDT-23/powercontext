# 记仇酒馆 · Grudge Tavern

> 2026 OceanBase 大赛 · Dify 赛道参赛作品
> 编排：**Dify 1.17.1 Chatflow**　长期记忆：**PowerContext 1.5.0**

---

## 1. 创意：一间会跨会话记仇的酒馆

酒馆卡在时空裂缝里，客人来来去去，但**账本从不清零**。三位常驻 NPC：

| NPC | 人设 | 记得什么 |
| --- | --- | --- |
| **格罗姆** | 贪财记仇的矮人老板娘 | 欠账、赖账、偷酒、赊账时的嘴脸 |
| **莉拉** | 八卦的精灵吟游诗人 | 糗事、外号、被她编进歌里的荒唐事 |
| **老K** | 戴兜帽的神秘客 | 秘密、承诺、把柄 |

玩家可以赊账、吹牛、恶作剧、许诺、挑衅。每轮对话结束后，值得记住的事会被写进
PowerContext；**关掉页面、换一个新会话、明天再来**，NPC 仍会主动翻出旧账：

> 玩家（新会话）：还认得我吗？
>
> 格罗姆：认得。你上回赊了一壶最贵的招牌酒，十二个银币，账本上还按着你的手印。
> 莉拉：而且我的琴弦是你弄断的，"手滑"？这借口我都编不进歌里。

这不是普通的对话历史：记忆存放在 Dify 之外，由 PowerContext 持久化，因此**跨会话**成立。

---

## 2. 架构

```
玩家
 │  HTTP
 ▼
Dify Web / 服务 API（端口 8088）
 │
 ▼
Dify Chatflow「记仇酒馆」
 start ─▶ build_query ─▶ prepare_memory ─▶ list_memories ─▶ merge_memory
                                                                  │
                                                                  ▼
                                                              narrate (LLM)
                                                                  │
                                                                  ▼
                                                             parse_reply
                                                                  │
                                                                  ▼
                                                               decide
                                                        yes ──────┴────── no
                                                         │                │
                                                    remember            answer
                                                         └──────▶ answer ◀┘
 │
 ▼
PowerContext HTTP API（compose 服务名 powercontext:8000）
  POST /v1/context/prepare      相关性召回
  POST /v1/atomic-memory/list   最近旧账兜底
  POST /v1/memory/remember      写入新记忆
```

**分工**

- Dify 负责：对话入口、流程编排、LLM 演出、JSON 解析、写入判定、状态展示。
- PowerContext 负责：长期记忆的创建、检索、持久化；跨 Dify 会话共享。
- 两者通过 Dify **HTTP Request 节点**直连，不使用任何私有插件，接入方式完全可见、可审计。

### 为什么同时用 prepare + list？

PowerContext 1.5 的 `context/prepare` 使用 Jieba 分词 + FTS5 词法召回，短问句
（例如"还认得我吗"）可能因为覆盖度阈值返回空。为了保证"跨会话记得"这一核心体验
稳定成立，流程同时调用 `atomic-memory/list` 拉取最近旧账，再在 code 节点里合并、
去重、按与玩家输入的重合度排序。所有记忆文本都带固定锚点
`酒馆记忆｜玩家：…｜涉及：…`，进一步提升词法命中的稳定性。

---

## 3. 环境要求

| 组件 | 版本 / 要求 |
| --- | --- |
| Docker | 24+，Compose v2 |
| Dify | 1.17.1（本作品在该版本验证） |
| PowerContext | 1.5.0（镜像内通过 PyPI 安装，无需源码） |
| Python（辅助脚本） | 3.10+，仅标准库 |
| 内存 | 建议 ≥ 8 GB；Dify 全栈 + PowerContext 约占 4–5 GB |
| 模型 | 任意 Anthropic 兼容端点；或 OpenAI 兼容端点（见第 6 节） |

> 提交分支是 orphan 快照，不含 PowerContext 源码，因此 PowerContext 通过 PyPI 包部署。

---

## 4. 快速开始

以下命令以 Linux/macOS shell 为例；Windows 请在 Git Bash 或 WSL 中执行。
设提交仓库路径为 `$REPO`，Dify 1.17.1 源码目录为 `$DIFY`。
本作品位于提交仓库的 `dify/grudge-tavern/` 子目录（`dify/` 下可能还有其他参赛作品）。

### 4.1 启动 Dify 并接入 PowerContext

```bash
# 1) Dify 环境变量
cd "$DIFY/docker"
cp .env.example .env
# 编辑 .env，至少设置：
#   EXPOSE_NGINX_PORT=8088
#   SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=powercontext
#   INIT_PASSWORD=（留空）

# 2) 构建 PowerContext 镜像（只做一次）
docker build -f "$REPO/dify/grudge-tavern/compose/powercontext.Dockerfile" \
             -t powercontext:1.5.0 "$REPO/dify/grudge-tavern/compose"

# 3) 启动 Dify 全栈 + PowerContext
docker compose -f docker-compose.yaml \
               -f "$REPO/dify/grudge-tavern/compose/docker-compose.override.yaml" up -d

# 4) 健康检查
curl -fsS http://127.0.0.1:8010/health/ready
```

Dify 控制台：<http://127.0.0.1:8088>　PowerContext：<http://127.0.0.1:8010>

### 4.2 配置辅助脚本

```bash
cd "$REPO/dify/grudge-tavern"
cp compose/.env.example .env
# 编辑 .env：
#   PC_URL=http://127.0.0.1:8010
#   PC_URL_IN_DOCKER=http://powercontext:8000
#   DIFY_BASE_URL=http://127.0.0.1:8088
#   DIFY_CONSOLE_EMAIL=admin@grudge.local
#   DIFY_CONSOLE_PASSWORD=<至少 8 位>
# 并导出模型凭据（不要写进仓库）：
export ANTHROPIC_BASE_URL="https://api.anthropic.com"   # 或兼容代理地址
export ANTHROPIC_AUTH_TOKEN="<your-key>"
```

### 4.3 创建记忆分区（scope）

```bash
python scripts/01_create_scope.py --seed
```

`--seed` 会写入两条种子旧闻（老猫赊账、地下室月圆开门），让第一次对话就有"旧账"。
scope id 保存到 `.local/scope.json`。

### 4.4 渲染 DSL

```bash
python scripts/02_render_dsl.py
```

把 `app/grudge-tavern.dsl.yaml` 中的占位符替换为真实 scope id / 容器内 URL / token，
输出 `.local/app.local.yaml`（**不提交**）。

### 4.5 导入、发布、生成 API Key

```bash
python scripts/03_bootstrap_dify.py
```

脚本会：初始化管理员（首次）→ 登录 → 安装 Anthropic 模型插件 → 保存模型凭据 →
导入 DSL → 发布 workflow → 创建服务 API Key，结果写入 `.local/dify.json`。
若 Anthropic 插件不可用，会自动回退到 OpenAI-API-compatible 插件（配合
`OPENAI_COMPAT_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN`），并自动改写 DSL 中的模型字段。

### 4.6 跨会话验证

```bash
python scripts/04_verify.py
```

两段**互相独立**的会话：

1. 赊一壶最贵的酒（十二银币），并弄断莉拉的琴弦；
2. 全新会话只问"还认得我吗？我欠多少、弄坏谁的琴弦？"

断言第二段回答至少命中两个关键词（金额 / 莉拉 / 琴），并把脱敏证据写到
`evidence/`。随后可收集节点级追踪：

```bash
python scripts/05_collect_trace.py
```

### 4.7 在 Dify 界面体验

打开 <http://127.0.0.1:8088>，用 `.env` 中的管理员账号登录，进入
「记仇酒馆」应用即可对话。脚本导入的应用已发布；也可以手动导入
`.local/app.local.yaml`（已替换占位符的版本）。

> 直接导入仓库中的 `app/grudge-tavern.dsl.yaml` 也可以，但需要先把三个环境变量
> 改成真实值：`PC_URL=http://powercontext:8000`、`PC_SCOPE_ID`、`PC_TOKEN`（可空）。

---

## 5. 手动部署要点（不使用辅助脚本）

1. 按 4.1 启动 Dify 与 PowerContext。
2. 创建 scope（可用 `scripts/01_create_scope.py`，或直接 `POST /v1/scopes`）。
3. Dify 控制台 → 导入 DSL → 在「环境变量」中填写 `PC_URL` / `PC_SCOPE_ID` / `PC_TOKEN`。
4. 设置 → 模型供应商 → Anthropic（或 OpenAI-API-compatible）→ 填 API Key。
5. 发布应用 → 创建 API Key（如需服务 API 调用）。
6. 开两个新会话，按第 4.6 节的两句话复现。

---

## 6. 模型配置说明

- 默认 DSL：`langgenius/anthropic/anthropic` + `claude-sonnet-4-6`。
- Anthropic 插件（`langgenius/anthropic`）允许自定义 `anthropic_api_url`，因此可以接
  Anthropic 官方或任何兼容代理。
- 回退方案：OpenAI-API-compatible 插件 + `endpoint_url=https://api.deepseek.com/v1`
  + `deepseek-chat`。脚本 `03_bootstrap_dify.py --provider openai-compatible` 可强制使用。
- 也可以把 LLM 节点换成任何已配置的 Chat 模型；本作品的记忆能力与模型无关。

**LLM 输出契约**（`parse_reply` 节点负责稳健解析）：

```json
{
  "lines": [{"speaker": "格罗姆", "text": "……"}],
  "status": "格罗姆：怒气+1｜欠账：12银币",
  "memory": "阿远赊了一壶招牌酒，欠格罗姆十二银币。",
  "memorable": "yes"
}
```

`memorable=yes` 且 `memory` 非空时才写入 PowerContext；解析失败会把原文当回复，
并**不写记忆**，保证流程不中断。

---

## 7. 验证样例与证据

样例与预期表现见 [`docs/verification-sample.md`](docs/verification-sample.md)。
技术细节见 [`docs/technical-note.md`](docs/technical-note.md)。
证据文件说明见 [`evidence/README.md`](evidence/README.md)。

`04_verify.py` / `05_collect_trace.py` 生成的证据包括：

- 两段会话的请求与完整回复；
- PowerContext 会话前后的 memory list、`context/prepare` 返回；
- 两次 workflow run 的节点执行顺序（prepare → list → merge → LLM → parse → decide → remember）；
- 汇总断言结果（`verify.summary.json`）。

所有证据在保存前会替换 API Key 与 scope id；仓库不包含任何真实密钥。

---

## 8. 评分自检

| 评分维度 | 本作品的对应实现 |
| --- | --- |
| 可运行 | Docker Compose 一键起 Dify + PowerContext；辅助脚本全自动初始化 |
| 可体验 | 打开 Dify 聊天页即可玩；三位 NPC 有人设与状态脚注 |
| 技术有效 | 记忆真实写入 PowerContext，跨会话读取成功；证据可核对 |
| 可复现 | 版本固定、脚本幂等、文档从零可操作 |
| 创意 | "记仇"把长期记忆变成玩法：旧账会反过来影响 NPC 态度 |
| 趣味 | 贪财老板娘、八卦诗人、神秘客的差异化演出 |
| 完整度 | 完整闭环：创建 scope → 召回 → 演出 → 写入 → 验证 |
| 技术结合 | 记忆不是外挂文本：写入判定、锚点、双路召回、冲突兜底都在流程内 |
| 工程 | 幂等 scope、错误兜底、脱敏证据、无第三方 Python 依赖 |

---

## 9. 已知限制

1. **单 scope 共享记忆**：演示版所有 Dify 会话共享同一个 scope，这是为了让"跨会话"
   在单机演示中直观成立；生产环境应按玩家/租户划分 scope（见技术说明）。
2. **默认关闭鉴权**：PowerContext 以 `ACCESS_MODE=disabled` 运行，仅适合本地演示。
   开启方式：在 override 中设置
   `POWERCONTEXT_SERVER_ACCESS_MODE=enforced`、
   `POWERCONTEXT_SERVER_AUTH_ENABLED=true`、
   `POWERCONTEXT_SERVER_AUTH_TOKEN=<随机长 token>`，
   并把同一个 token 写入 Dify 环境变量 `PC_TOKEN`。详见 `docs/technical-note.md`。
3. **词法召回**：PowerContext 1.5 的文本召回对短问句不敏感，因此流程使用固定锚点 +
   最近旧账兜底；不依赖向量模型。
4. **LLM 输出为 JSON**：极端情况下模型可能输出非法 JSON，此时降级为原文回复且不写记忆。
5. **模型可替换**：默认的 `claude-sonnet-4-6` 需要对应端点；换模型只需改 LLM 节点。

---

## 10. 目录结构

```
dify/grudge-tavern/
├── app/grudge-tavern.dsl.yaml        # Chatflow DSL 0.7.0（含占位符）
├── compose/
│   ├── powercontext.Dockerfile       # PyPI 固定版本 1.5.0
│   ├── docker-compose.override.yaml  # 挂到 Dify compose 网络
│   └── .env.example
├── scripts/
│   ├── pc_client.py                  # 标准库 PowerContext 客户端
│   ├── dify_client.py                # 标准库 Dify 控制台客户端
│   ├── 01_create_scope.py
│   ├── 02_render_dsl.py
│   ├── 03_bootstrap_dify.py
│   ├── 04_verify.py
│   └── 05_collect_trace.py
├── docs/
│   ├── technical-note.md
│   └── verification-sample.md
└── evidence/README.md
```
