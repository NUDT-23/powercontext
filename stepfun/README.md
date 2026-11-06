# 端侧知识库 · 浏览器本地向量化 + seekdb 混合检索

OceanBase 2026 大赛「阶跃星辰」赛道作品。

文档切分与 embedding **全部在浏览器内完成**（Transformers.js + ONNX Runtime Web，优先 WebGPU/FP16，失败自动降级 WASM/INT8）；向量、原文与元数据由 **seekdb 嵌入式数据库**存储；检索时前端只发一次请求，向量通道与全文通道的 **RRF 融合在 seekdb 内一次 `hybridSearch` 完成**，不存在前端拼接两路结果的路径。没有任何云端推理 API。

## 验收点对照

| 赛题要求 | 本作品实现 |
| --- | --- |
| 端侧推理，禁止云端 embedding | 模型与 ORT WASM 均为同源静态文件，`allowRemoteModels=false`；E2E 断言页面请求只落在本机 |
| 优先 WebGPU，自动降级 WASM | 顶栏徽标显示 `WebGPU · FP16` / `WASM · INT8` 与降级原因；`?forceWasm=1` 可复现降级路径 |
| INT8 / FP16 量化与质量报告 | 仓库内置 INT8（22.90 MiB，3.95×）与 FP16（45.30 MiB，2.00×），FP32 由脚本下载作基线；Recall@K / nDCG@K 实测 |
| seekdb 存储与混合检索 | 向量 HNSW（512 维、cosine）+ 全文索引（ik 分词），单次 `collection.hybridSearch()`，RRF 在库内执行 |
| 增量导入 / 索引刷新 / 集合 / 会话 | 内容哈希判重后 upsert；导入后 `refresh_index()`；多集合管理；localStorage 只存集合名与计数 |
| 性能实测与技术说明 | 3 轮预热 + 7 轮测量的基准页、`artifacts/bench/results.md`、一页技术说明 |
| 可复现验收 | `npm run verify` 一条命令跑完单元测试、seekdb 冒烟、混合检索集成、构建、生产服务与浏览器 E2E |

## 架构

```
Browser（Vite + TypeScript）
  file/text ─▶ 中文分句切块（~200 字，重叠 50）
            ─▶ 本地 embedding（WebGPU/FP16，失败降级 WASM/INT8）
                 │ POST /api/import  { docs: [{ text, metadata, embedding(base64 f32) }] }
                 │ POST /api/search  { queryText, queryEmbedding(base64 f32) }
                 ▼
Node 服务（:8787，同源托管前端）
  ├─ 只解码客户端传来的 Float32 向量，绝不做 embedding
  ├─ seekdb 嵌入式引擎：collection.hybridSearch() × 1 → RRF 融合
  └─ 导入 → refresh_index() → 搜索开放
```

- 模型：`Xenova/bge-small-zh-v1.5`，512 维，CLS pooling + L2 归一化。
- 集合 schema：`VectorIndexConfig({ hnsw: { dimension: 512, distance: "cosine" } })` + `FulltextIndexConfig("ik", { ik_mode: "smart" })`；ik 不可用时自动回退 `ngram2`，仍是库内全文检索。
- 融合参数：`rank: { rrf: { rankWindowSize: 40, rankConstant: 60 } }`，服务端把每次调用的入参、结果与耗时写入 `/api/debug/hybrid` 供验收核对。

## 快速开始

前置：Node.js ≥ 20；Windows 上需要正在运行的 Docker Desktop（seekdb 的原生绑定是 Linux 版，本项目在容器中运行它）；推荐使用 Microsoft Edge / Chromium 验证 WebGPU 路径。

```bash
cd stepfun
npm install
npm run fetch-models      # 校验/补齐仓库内 INT8 + FP16 模型（内置时仅校验）
npm run build
npm start                 # http://127.0.0.1:8787
```

首次启动空数据库时，服务端会执行一次约 5.6 s 的索引管理器预热（seekdb HNSW 的已知行为），之后刷新正常。

FP32 基线不入库，需要时单独下载：

```bash
npm run fetch-models:fp32
```

无 Node 环境或希望一键容器化：

```bash
docker compose up --build -d     # http://localhost:8787
docker compose down
# 网络受限时：NPM_REGISTRY=https://registry.npmmirror.com docker compose up --build -d
```

compose 已包含 seekdb 所需的 `seccomp=unconfined`、64 MiB 线程栈、`LD_PRELOAD` 与持久化数据卷。

## 使用

1. 「知识库」页创建或选择集合；导入完成后才能检索。
2. 粘贴中文文本、选择 `.txt/.md/.jsonl` 文件，或点击「导入示例语料（56 篇）」。
3. 观察进度：切块 → 本地向量化（显示 batch 进度）→ 入库 → `refresh_index()`。
4. 切到「检索」页输入问题；结果下方显示查询向量化、seekdb 混合检索与端到端耗时。
5. 「基准与报告」页运行完整基准：先测 FP32 基线（若已下载），再测 INT8，WebGPU 可用时追加 FP16；质量指标基于 30 条人工查询与 89 条 qrels。
6. 生成 Markdown 报告：

```bash
npm run generate:report   # 写入 artifacts/bench/results.md 与 docs/benchmark.md
```

## 基准结果

环境：Windows 11 · Edge 156（WebGPU，Intel Gen-12LP，20 线程）· 56 篇文档 / 30 条查询。3 轮预热 + 7 轮测量，batch=8。

| 精度 | 后端 | 模型体积 | 压缩比 | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | 文档向量化 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 | WASM | 90.46 MiB | 1.00× | 0.711 | 0.856 | 0.845 | 0.879 | 29.7 docs/s |
| INT8 | WASM | 22.90 MiB | 3.95× | 0.700 | 0.856 | 0.844 | 0.880 | 47.7 docs/s |
| FP16 | WebGPU | 45.30 MiB | 2.00× | 0.711 | 0.856 | 0.846 | 0.879 | 201.7 docs/s |

端到端（查询向量化 + seekdb 混合检索）中位数 **13.1 ms**、p95 18.3 ms；纯 seekdb 检索中位数 3.11 ms。INT8 相对 FP32：Recall@5 下降 1.1 个百分点、nDCG@5 下降 0.1 个百分点，但体积缩小到 1/3.95、加载快约 3 倍、WASM 吞吐高 60%。完整数据见 [docs/benchmark.md](docs/benchmark.md)。

## 验证

```bash
npm run verify            # 或 ./verify.sh
```

依次执行：环境检查 → 模型/ORT 静态资源校验 → 单元测试 → seekdb 冒烟（中文双路 + 库内 RRF）→ 混合检索集成测试 → 前端/服务端构建 → 独立数据目录启动生产服务 → Edge 端到端验收。结果写入 `artifacts/evidence/verify.json`，截图在 `artifacts/screenshots/`。失败时退出码非零。

E2E 覆盖：完整导入检索流程、本地推理（无外部请求）、量化体积与压缩比、强制与自动 WASM 降级、seekdb 单次 hybridSearch 与调用计数、增量导入与刷新、刷新后会话恢复、页面无 JS 错误。

单独运行：

```bash
npm run test:unit
npm run smoke:seekdb
npm run test:hybrid
npm run build && npm start      # 另开终端
npm run test:e2e                # BASE_URL 默认 http://127.0.0.1:8787
npm run typecheck
```

## 目录

```
stepfun/
  server/src/            Express API 与 seekdb 封装（唯一 hybridSearch 入口）
  shared/types.ts        前后端共享类型（向量以 base64 Float32 传输）
  web/src/               前端：embedder / backend 探测 / 切块 / UI / 基准
  web/public/models/     内置 bge-small-zh-v1.5（INT8 + FP16，FP32 不入库）
  web/public/ort/        ONNX Runtime WASM（由脚本从 node_modules 复制）
  corpus/                56 篇示例文档、30 条查询、89 条 qrels
  scripts/               fetch-models / prepare-ort / verify / 报告生成 / 容器运行器
  tests/                 单元、混合检索集成、Playwright E2E
  docs/                  技术说明、复现手册、验证样例、基准报告
  Dockerfile             docker-compose.yml   verify.sh
```

## 已知限制

- **FP32 基线不提交**：体积约 90 MiB，按赛题要求由 `npm run fetch-models:fp32` 下载；未下载时基准页会注明压缩比不可得。
- **Windows 运行 seekdb 依赖 Docker**：官方原生绑定为 Linux 版；`scripts/run-with-seekdb.mjs` 在 Windows 自动使用容器，并注入 `LD_PRELOAD`、seccomp 与线程栈设置。Linux/macOS 可直接原生运行。
- **嵌入式 seekdb 不是多进程/并发安全的**：服务端已把所有数据库操作串行化，同一数据目录也不要同时启动两个服务进程。
- **WebGPU 取决于评测机**：无 GPU 时自动走 WASM/INT8，功能完整；FP16 数据仅在可用时报告，不伪造通过。
- **Git Bash 路径转换**：手动设置 `STEPFUN_*=/data/...` 环境变量时需加 `MSYS_NO_PATHCONV=1`；`npm run verify` 在 Node 内部设置变量，不受影响。

## 文档

- [一页技术说明](docs/technical-note.md)
- [复现手册](docs/reproduction.md)
- [验证样例](docs/verification-sample.md)
- [基准报告](docs/benchmark.md)
