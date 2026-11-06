# 验证样例

本文件记录一次完整的 `npm run verify` 实际输出，供评审对照。原始数据见 `artifacts/evidence/`。

- 执行时间：2026-11-06T22:40:05Z ～ 22:42:43Z（约 2 分 38 秒）
- 环境：Windows 11 · Node v24.14.1 · Docker 29.7.2 · Edge 156
- 结论：**VERIFY PASS（8/8 项通过）**，浏览器后端 `WebGPU · FP16 · intel gen-12lp`

## 1. 总览

| 步骤 | 结果 | 耗时 |
| --- | --- | ---: |
| 环境检查 | ok | 91 ms |
| 模型与 ORT 静态资源检查 | ok | 2 ms |
| 单元测试（切块 + 指标） | 9/9 通过 | 206 ms |
| seekdb 冒烟（中文双路 + 库内 RRF） | ok | 67.3 s |
| 混合检索集成测试（单次 hybridSearch 与 HNSW 回归） | ok | 65.4 s |
| 构建前端与服务端 | ok | 3.9 s |
| 启动生产服务并等待健康检查 | ok | 8.1 s |
| 浏览器端到端验收 | 11/11 通过 | 12.4 s |

> 冒烟与集成两步各约 1 分钟，主要是容器启动、seekdb 索引管理器预热（约 5.6 s）与退出清理；不是检索本身耗时。

## 2. seekdb 冒烟（`artifacts/evidence/smoke-seekdb.json`）

- 平台：`linux-x64`（容器），Node v20.20.2，seekdb 1.4.0；
- 分析器：`ik`；写入 6 篇中文文档；
- 关键结果：

```text
count              6
analyzerUsed       ik
hybridIds          d1, d2, d4
vectorIds          d1, d4, d2      ← 与 hybrid 排序不同
fulltextIds        d1, d2, d4
hybridDiffersFromVector    true
hybridHasScores            true
```

- 单步耗时：建集合 211.1 ms、预热 4921.9 ms、写入 864.6 ms、刷新 302.3 ms、混合检索 204.1 ms、纯向量 3.6 ms、全文 32.5 ms。
- 说明：混合排序与纯向量排序不同，证明向量通道参与了 RRF 融合；全文通道在强关键词命中时排序可与混合一致，这是正常现象，集成测试只要求「至少与单通道之一不同」且本次两种差异情形均被覆盖。

## 3. 混合检索集成测试（`artifacts/evidence/hybrid-test.json`）

9 项检查全部通过：

```text
create collection                       3868 ms   analyzer=ik
warm up index manager                   5730 ms
import documents                         158 ms   count=6
refresh publishes vectors                401 ms
hybridSearch returns RRF results          31 ms   ids=h1,h3,h2 scores=0.0325,0.0325,0.0317
vector channel is queryable                2 ms   ids=h3,h1,h2
fulltext channel is queryable              1 ms   ids=h1,h3,h2
hybrid differs from at least one channel   0 ms   hybrid=h1,h3,h2 vector=h3,h1,h2 fulltext=h1,h3,h2
incremental upsert + refresh searchable  412 ms   ids=h7
```

覆盖点：新建集合预热、导入后刷新确实发布 HNSW 向量、混合排序由库内 RRF 产生、增量 upsert 后刷新可立即检索。

## 4. 浏览器端到端（`artifacts/evidence/e2e.json`）

服务地址 `http://127.0.0.1:8799`，独立数据目录 `/data/verify-20261106224005`，集合 `e2e_1794004950552`。

| 检查 | 结果 | 关键值 |
| --- | --- | --- |
| 健康检查 | ok | seekdb 1.4.0 / linux-x64 / database=test |
| 集合创建 | ok | `e2e_1794004950552` |
| 完整流程：本地向量化 → 入库 → 混合检索 | ok | 新增 1；查询向量化 9.9 ms；seekdb 41.75 ms；端到端 52.1 ms；`RRF 在库内执行 (k=60, analyzer=ik)` |
| seekdb 数据层：单次 hybridSearch | ok | 每次检索调用计数 **+1**；`rankWindowSize=40, rankConstant=60`；analyzer=ik |
| 增量导入 | ok | 重复内容跳过 1；新增后集合计数 1 → 2；新标记可检索 |
| 量化模型 | ok | fp32 94,851,877 B；fp16 47,497,427 B（2.00×）；int8 24,010,842 B（3.95×）；fp16/int8 文件由本机静态服务提供 |
| 本地推理 | ok | 共 45 个请求，其中模型 8 个、ORT 5 个，全部指向本机；无任何外部域名 |
| 会话状态 | ok | 刷新后集合选择与 localStorage 记录保留（不含文档/向量） |
| 强制降级路径 | ok | `?forceWasm=1` → 徽标 `WASM · INT8`，原因包含 `forceWasm`，检索返回 2 条 |
| 自动降级路径 | ok | 注入 `navigator.gpu=undefined` → 徽标 `WASM · INT8`，原因为「当前浏览器未暴露 WebGPU (navigator.gpu)」，检索返回 2 条 |
| 页面运行时无 JS 错误 | ok | 4 条无害告警（favicon / ONNX 节点分配提示）被白名单过滤，无未处理异常 |

截图：

- `artifacts/screenshots/e2e-search.png`：WebGPU/FP16 路径的检索结果与耗时；
- `artifacts/screenshots/e2e-wasm.png`：强制 WASM/INT8 路径，徽标与检索结果。

## 4.1 容器镜像复验

除 Node 路径外，交付的 Docker 镜像也完成了同一套浏览器验收：

```bash
NPM_REGISTRY=https://registry.npmmirror.com docker compose build
docker compose up -d
BASE_URL=http://127.0.0.1:8787 node tests/e2e.spec.mjs
```

- 镜像 `stepfun-kb:local` 约 606 MB，基于 `node:20-slim`，安装 `libaio1`，预下载 seekdb 绑定；
- `/api/health` 返回 `seekdb 1.4.0 · linux-x64`；
- E2E 11/11 通过（证据：`artifacts/evidence/e2e-docker.json`），后端仍为 `WebGPU · FP16 · intel gen-12lp`，自动降级与强制降级均返回检索结果；
- 构建期设置 `ONNXRUNTIME_NODE_INSTALL_CUDA=skip`，避免从 GitHub 拉取用不到的 CUDA 二进制。

## 5. 基准数据（`artifacts/bench/results.json`）

同一台机器、Edge 156、WebGPU Intel Gen-12LP、20 线程；56 篇文档 / 30 条查询。

| 精度 | 后端 | 体积 | 压缩比 | Recall@5 | nDCG@10 | 文档向量化 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| FP32 | WASM | 90.46 MiB | 1.00× | 0.711 | 0.879 | 29.7 docs/s |
| INT8 | WASM | 22.90 MiB | 3.95× | 0.700 | 0.880 | 47.7 docs/s |
| FP16 | WebGPU | 45.30 MiB | 2.00× | 0.711 | 0.879 | 201.7 docs/s |

端到端检索中位数 13.1 ms、p95 18.3 ms；纯 seekdb 检索中位数 3.11 ms、p95 4.14 ms。

## 6. 复跑

```bash
cd stepfun
npm install
npm run verify
```

如需无浏览器环境的最小验证：`STEPFUN_SKIP_E2E=1 npm run verify`。
完整步骤、端口与故障排查见 [reproduction.md](reproduction.md)。
