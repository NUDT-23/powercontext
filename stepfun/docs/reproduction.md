# 复现手册

## 1. 环境

本作品在以下环境完整验证：

| 项目 | 版本 / 说明 |
| --- | --- |
| 操作系统 | Windows 11（10.0.26200） |
| Node.js | v24.14.1（宿主机）；容器内 v20.20.2 |
| npm | 11.11.0 |
| Docker Desktop | 29.7.2（Linux 容器） |
| 浏览器 | Microsoft Edge 156（`msedge.exe`，Playwright 驱动） |
| 模型 | `Xenova/bge-small-zh-v1.5`，512 维 |
| seekdb | 1.4.0（`seekdb` npm 包，嵌入式） |

Linux / macOS 可直接使用原生 seekdb 绑定；Windows 的 seekdb 原生绑定是 Linux 版，本项目的 `scripts/run-with-seekdb.mjs` 会自动把测试与服务放进容器执行。

## 2. 安装与启动（Node 路径）

```bash
cd stepfun
npm install
npm run fetch-models       # 仓库已内置 INT8/FP16；此命令只校验或补齐缺失文件
npm run build
npm start                  # http://127.0.0.1:8787
```

- `npm run fetch-models` 从 `hf-mirror.com` 下载缺失文件，可用 `HF_MIRROR` 覆盖镜像地址。模型清单 `model-manifest.json` 会记录每个 ONNX 的字节数与 SHA-256。
- FP32 基线约 90 MiB，默认不提交；需要精确压缩比或运行完整三档基准时执行 `npm run fetch-models:fp32`。
- Windows 首次启动会构建 `stepfun-seekdb:local` 运行镜像；数据卷为 `stepfun-seekdb-data`。
- 开发模式：`npm run dev` 启动 Vite（5173，代理 `/api` 到 8787）与 API。

## 3. 一条命令验收

```bash
npm run verify             # 等价于 ./verify.sh
```

执行顺序与耗时参考：

1. 环境检查（Node ≥ 20、`@seekdb/js-bindings`、Docker、Edge 路径）；
2. 模型与 ORT 静态资源校验（体积与 manifest 一致，ORT wasm 存在）；
3. 单元测试（切块与指标，`node --test`）；
4. seekdb 冒烟：中文入库 → ik 全文 → 向量 → 库内 RRF 混合检索 → 刷新 → 计数；
5. 混合检索集成测试：预热、HNSW 向量通道、单次 `hybridSearch`、增量 upsert；
6. 构建前端（Vite）与服务端（esbuild）；
7. 以独立数据目录 `/data/verify-<runId>` 启动生产服务，端口 8799，等待健康检查；
8. Edge 无头 E2E：导入检索、本地推理、量化、强制降级与自动降级、单次 hybrid 调用、增量、会话恢复、JS 错误检查（11 项）。

结果写入 `artifacts/evidence/verify.json`，截图在 `artifacts/screenshots/`。全部通过时打印 `VERIFY PASS` 且退出码为 0。

按需跳过或改端口：

```bash
STEPFUN_VERIFY_PORT=8800 npm run verify
STEPFUN_SKIP_E2E=1 npm run verify       # 无浏览器环境时只跑后端
EDGE_PATH="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" npm run verify
```

单独执行各环节：

```bash
npm run test:unit
npm run smoke:seekdb
npm run test:hybrid
npm run build && npm start              # 终端 A
npm run test:e2e                        # 终端 B
npm run typecheck
```

## 4. Docker Compose 部署

```bash
docker compose up --build -d
# 打开 http://localhost:8787
docker compose down
```

镜像基于 `node:20-slim`，构建时通过 npm 安装依赖。网络受限时可用镜像源覆盖构建参数：

```bash
NPM_REGISTRY=https://registry.npmmirror.com docker compose up --build -d
```

镜像已设置 `ONNXRUNTIME_NODE_INSTALL_CUDA=skip`，避免 onnxruntime-node 的 postinstall 从 GitHub 拉取本项目用不到的 CUDA 二进制；CPU 二进制随 npm 包分发。构建仍需访问 npm 源与 seekdb 原生绑定下载地址，运行阶段完全离线。

`docker-compose.yml` 已配置：

- 端口 `8787:8787`，数据卷 `stepfun-data:/data`；
- `security_opt: seccomp:unconfined`（seekdb HNSW 建索引需要创建线程）；
- 线程栈 64 MiB；
- 健康检查请求 `/api/health`。

镜像内预下载 seekdb 绑定，并把 `libseekdb.so` 通过 `LD_PRELOAD` 暴露给运行时，因此容器启动无需外网。

## 5. 重新生成基准与报告

1. 打开「基准与报告」页，点击「运行完整基准」；
2. 结果保存为 `artifacts/bench/results.json`，界面显示体积、压缩比、Recall@K、nDCG@K、冷启动、吞吐与检索延迟；
3. 生成 Markdown：

```bash
npm run generate:report    # 同时写 artifacts/bench/results.md 和 docs/benchmark.md
```

基准使用 3 轮预热 + 7 轮测量，文档 batch=8；FP32 缺失时只评测 INT8，WebGPU 不可用时跳过 FP16 并注明原因。

## 6. 数据清理

```bash
# 容器路径的数据
docker volume rm stepfun-seekdb-data stepfun_stepfun-data

# 原生路径（Linux/macOS）
rm -rf data/seekdb data/state.json
```

`data/` 已被 `.gitignore` 忽略，不会进入提交。

## 7. 已知问题与排查

| 现象 | 原因与处理 |
| --- | --- |
| `port 8799 is already serving` | 上一次验收未退出，换 `STEPFUN_VERIFY_PORT` 或结束占用端口的进程 |
| 首次导入前的刷新约 5.6 s | seekdb 索引管理器冷启动预热，属预期行为 |
| 日志出现 `OB_ABORT`，但进程随后正常退出 | 嵌入式引擎关闭阶段的已知噪声；验收以退出码与证据 JSON 为准 |
| `pthread_create: Invalid argument` | 容器线程栈不足；`run-with-seekdb.mjs` 已设 `ulimit -s 65536`，保留该日志即可 |
| Windows 下手动运行出现 `D:/Git/data/...` 路径错误 | Git Bash 的 MSYS 路径转换；设置环境变量时加 `MSYS_NO_PATHCONV=1`，或改用 `npm run verify` |
| 页面徽标为 `WASM · INT8` 且提示原因 | 当前浏览器/设备无 WebGPU 或 FP16 初始化失败，属自动降级，功能不受影响 |
| E2E 报找不到 Edge | 设置 `EDGE_PATH`，或安装 Edge/Chromium；也可 `STEPFUN_SKIP_E2E=1` 只验证后端 |
| 同一数据目录启动两个服务后崩溃 | 嵌入式 seekdb 不支持多进程并发；每个进程使用独立 `STEPFUN_DB_PATH` |

## 8. 证据文件

| 文件 | 内容 |
| --- | --- |
| `artifacts/evidence/verify.json` | 完整验收步骤、耗时、环境与结论 |
| `artifacts/evidence/smoke-seekdb.json` | 中文入库、双通道与混合排序结果 |
| `artifacts/evidence/hybrid-test.json` | 预热、HNSW、单次 hybrid、增量 upsert |
| `artifacts/evidence/e2e.json` | 浏览器端 11 项检查与耗时（Node 路径） |
| `artifacts/evidence/e2e-docker.json` | 同一套 11 项检查在 Docker 镜像上的结果 |
| `artifacts/screenshots/e2e-search.png` | WebGPU 路径检索截图 |
| `artifacts/screenshots/e2e-wasm.png` | `?forceWasm=1` 降级截图 |
| `artifacts/bench/results.json` | 原始基准数据 |
| `docs/benchmark.md` | 由基准数据生成的报告 |
