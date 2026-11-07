# Dify 赛道作品 · 设计方案

> 赛题：Just for Fun——用 Dify 做一个好玩的智能应用（20 分）。
> 硬性：必须用 Dify + **seekdb / PowerContext 至少一种实际发挥作用**；DSL + 运行说明 + 验证样例交付。
> 本目录为作品资产（`dify/`），开发分支 `2026-competition-ecosystem`。

## ✅ 状态（2026-11-07）：已实现并本地实测通过

- 交付物：`DSL/tavern.yml`（从运行实例导出，环境变量占位）+ `运行说明.md` + `验证样例.md` + 配套工具（`dify_api.sh`/`tavern_test.py`）
- 实测环境：Dify 1.11 自部署（WSL Docker）+ PowerContext Server（memory API）+ MiniMax-M3.1-Flash（MPlan）
- 五组验证样例全过：记忆写入 / **跨会话召回** / 矛盾拆穿（原话引用）/ 未记录拒绝编造 / 服务重启记忆存活

## 作品：《老板记性太好酒馆》

一个**永远不会忘记**的酒馆老板 NPC。玩家跟老板闲聊、许诺、吹牛、透秘密；无论隔多久再开新会话，老板都记得你说过的一切——并当场拆穿你前后矛盾的话。

一句话卖点：**测测你能不能骗过一个记性完美的老板。**

### 为什么好玩

- 普通聊天机器人转身就忘；这个老板**主动复述你三天前说过的话**，反差即乐趣。
- 玩法自然涌现：玩家会试探记忆边界（改名字、撒谎、编造从未说过的话），老板用真实记忆回击"这话你可没说过，你上次说的是……"。
- 跨会话记忆是核心机制而非噱头：每个新会话开始时从记忆里召回玩家档案与最近互动，"欢迎回来"。

### 技术架构（PowerContext 实际承担记忆职能）

```
玩家输入
  │
  ▼
Dify Chatflow
  ├─ [HTTP Request] POST {POWERCONTEXT_URL}/v1/memory/search
  │    body: {"scope_id": "tavern:{player_key}", "query": "<用户消息>",
  │           "limit": 8}
  │    → 召回相关记忆（老板的"回忆"）
  ├─ [LLM] 老板人设 system prompt + 注入记忆 + 用户消息
  │    规则：只用注入的记忆谈论过去；矛盾当场指出；没记录就说"这你倒没提过"
  ├─ [HTTP Request] POST {POWERCONTEXT_URL}/v1/memory/remember
  │    body: {"scope_id": "tavern:{player_key}",
  │           "kind": "tavern-turn",
  │           "text": "<本轮玩家说的话要点 + 老板回应要点>",
  │           "reason": "tavern conversation turn"}
  │    → 本轮写入记忆（跨会话持久的来源）
  └─ [Answer] 输出老板台词
```

- **PowerContext 的作用可核对**：memory/search 与 memory/remember 的每次调用都在 Dify 节点执行记录里；断电重启后记忆仍在（服务端持久化）。
- 玩家身份：会话变量 `player_key`，开局问一次名字后固定（`tavern:张三`），跨会话用同一 scope。
- LLM：智谱 GLM（Dify 内置 zhihu/zhipu provider，用户已有 bigmodel 账号）。

### PowerContext 服务部署（2026-11-07 凌晨已实测跑通）

- WSL2 内启动（venv 已装好，依赖 ~409M）：
  ```bash
  cd /root/powercontext
  setsid nohup .venv/bin/powercontext server run --host 127.0.0.1 --port 8000 \
    --no-env-file > /root/pc_server.log 2>&1 < /dev/null &
  ```
- 服务端点：`GET /health/live` → `{"status":"ok"}`
- **scope 由服务端生成 ID**（请求体不能自带 scope_id）：
  ```bash
  curl -X POST http://127.0.0.1:8000/v1/scopes -H 'Content-Type: application/json' \
    -d '{"title":"Tavern","summary":"酒馆记忆","idempotency_key":"tavern-1"}'
  # → {"scope_id":"scp_xxx", ...}  记下这个 id
  ```
- 记忆写入/检索（已实测，FTS 中文命中）：
  ```bash
  curl -X POST .../v1/memory/remember -d '{"scope_id":"scp_xxx","kind":"tavern-turn","text":"...","reason":"tavern turn"}'
  curl -X POST .../v1/memory/search  -d '{"scope_id":"scp_xxx","query":"酒钱","limit":8}'
  # search 返回 {"mode":"fts","hits":[{"text":...,"score":...}]}
  ```
- **重启持久化已验证**：kill 服务→重启→search 仍命中（SQLite WAL，数据在
  `/root/.local/share/powercontext/powercontext.db`；服务还内嵌 seekdb 目录，见 paths.py）。
- 公网隧道（cloudflared 已装 Windows）：
  ```bash
  "/c/Program Files (x86)/cloudflared/cloudflared" tunnel --url http://localhost:8000
  # → https://xxx.trycloudflare.com（临时 URL，重启即换；DSL 中用环境变量占位）
  ```
  2026-11-07 凌晨实测：公网 URL health + memory/search 全通（URL 会过期，重跑命令拿新的）。

### 验证样例（交付材料）

1. **新玩家记忆写入**：输入"我叫张三，我欠你一杯酒钱"；下一轮问"我欠你什么？"→ 老板答酒钱。
2. **跨会话召回**：新开会话，同一 player_key，输入"你还记得我吗？"→ 老板复述姓名+欠酒钱。
3. **矛盾拆穿**：新会话说"我从没欠过你钱" → 老板引用上次记录反驳。
4. **未记录信息拒绝编造**：问"我上次穿的什么衣服？"（记忆里没有）→ 老板明确说这没提过，不编。

每样例附：初始条件、输入、操作步骤、预期表现、节点执行截图（HTTP 节点 200 响应）。

### 交付物清单（明早/明天）

- [ ] `dify/DSL/tavern.yml`（Chatflow 导出）
- [ ] `dify/运行说明.md`（PowerContext 启动、tunnel、Dify 导入、模型/环境变量配置）
- [ ] `dify/验证样例.md`（上述 4 例 + 截图）
- [ ] README（本文件，补体验入口）

## 风险与备选

- cloud.dify.ai 在本网络不可达（2026-11-07 凌晨实测超时）：备选 ①用户开代理后云端构建；②Dify 社区版 docker-compose 自部署（WSL，localhost 直连 PowerContext，甚至可上 seekdb 作库拿双技术分）。
- PowerContext server 认证配置细节以服务启动输出为准（bearer→principal→scope-bindings 三步）。
