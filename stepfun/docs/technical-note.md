# 技术说明：端侧知识库（浏览器本地向量化 + seekdb 混合检索）

## 1. 问题与约束

赛题要求：embedding 不得调用云端 API；优先 WebGPU、不可用自动降级 WASM；使用 INT8/FP16 量化并报告体积、压缩比与检索质量变化；向量与全文的混合检索必须在 seekdb 内完成；支持增量导入、索引刷新、集合与会话状态。

本作品把「计算」和「存储」彻底分开：浏览器独占推理，Node 服务独占 seekdb，二者仅通过本机 HTTP 交换文本、元数据和 Float32 向量。前端永远不接触数据库，服务端永远不接触模型。

## 2. 端侧推理

- 模型 `Xenova/bge-small-zh-v1.5`（512 维，CLS pooling + L2 归一化），Transformers.js 3.7.6 + ONNX Runtime Web。
- 模型与 ORT WASM 均为同源静态资源：`allowRemoteModels=false`、`localModelPath=/models/`、`wasmPaths=/ort/`；E2E 拦截页面请求，断言不存在本机以外的网络访问。
- 启动时探测 `navigator.gpu` 并请求 adapter。成功则以 WebGPU + FP16 加载；探测失败、模型加载失败或首次推理异常，任一步都回退到 WASM + INT8，并把原因显示在顶栏。`?forceWasm=1` 复现降级路径。
- COOP/COEP 响应头启用跨源隔离，WASM 后端最多 4 线程；不可隔离时自动单线程。

## 3. seekdb 混合检索

集合 schema：HNSW 向量索引（512 维、cosine）+ 全文索引（ik，`ik_mode=smart`）；ik 创建失败时回退 `ngram2`，仍由库内完成全文检索。检索路径只有一个：

```ts
collection.hybridSearch({
  query: { whereDocument: { $contains: queryText } },
  knn:   { queryEmbeddings: [embedding], nResults: nResults * 2 },
  rank:  { rrf: { rankWindowSize: 40, rankConstant: 60 } },
  nResults,
});
```

向量通道与关键词通道的 RRF 排序在 seekdb 内计算，服务端只取回最终 ids/原文/元数据/分数。`/api/debug/hybrid` 暴露最近一次调用的入参与结果；E2E 断言每点一次检索，调用计数恰好 +1，排除前端二次排序或两路合并。

导入使用 `upsert`：客户端按「来源 + 块序号 + 文本」生成稳定 ID，服务端再对「ID + 文本 + 元数据」做 SHA-256，内容未变则跳过，变化则更新。导入结束后调用 `refresh_index()`，刷新完成前搜索按钮保持关闭。

## 4. 量化权衡（实测）

56 篇中文文档、30 条人工查询、89 条 0/1/2 级 qrels；同一套查询分别打到 FP32/INT8/FP16 三个独立集合，指标由 seekdb 混合检索结果计算。

| 精度 | 体积 | 压缩比 | Recall@5 | nDCG@5 | 文档向量化吞吐 |
| --- | ---: | ---: | ---: | ---: | ---: |
| FP32 / WASM | 90.46 MiB | 1.00× | 0.711 | 0.845 | 29.7 docs/s |
| INT8 / WASM | 22.90 MiB | 3.95× | 0.700 | 0.844 | 47.7 docs/s |
| FP16 / WebGPU | 45.30 MiB | 2.00× | 0.711 | 0.846 | 201.7 docs/s |

INT8 用 1/3.95 的体积换到 Recall@5 下降 1.1 个百分点、nDCG@5 下降 0.1 个百分点，同时加载时间从 2.18 s 降到 0.70 s，WASM 吞吐提升 60%。FP16 的质量与 FP32 基本重合，WebGPU 吞吐约为 WASM INT8 的 4.2 倍。无 GPU 时 INT8 是默认且完全可用的路径。端到端检索（查询向量化 + 库内混合检索）中位数 13.1 ms、p95 18.3 ms，其中 seekdb 部分中位数 3.11 ms —— 检索开销与推理后端无关。

## 5. 工程风险与处理

- **HNSW 首次发布不稳定**：新建空集合后先执行一次 `refresh_index()` 预热索引管理器（约 5.6 s），后续刷新才能可靠发布向量索引；引擎刚启动时刷新仍可能偶发 30 s 超时（ret=-4012），服务端与测试对超时自动重试一次。
- **嵌入式引擎并发不安全**：多个 HTTP 请求并发访问同一 seekdb 实例会触发 `OB_ABORT`。`SeekdbStore` 用 Promise 队列串行化全部数据库操作，这是 E2E 稳定通过的关键修复。
- **Windows 运行环境**：官方绑定为 Linux 版，Windows 通过 Docker 运行；容器需要 `seccomp=unconfined`（HNSW 建索引要创建线程）、64 MiB 线程栈，以及 `LD_PRELOAD` 指向缓存中的 `libseekdb.so`。数据目录使用 Docker volume，避免 Windows 绑定挂载的 I/O 问题。
- **可复现性**：MSYS/Git Bash 会把 `/data/...` 环境变量改写成 Windows 路径；`verify` 在 Node 内部设置变量，规避该问题。

## 6. 验证

`npm run verify` 依次执行单元测试、seekdb 中文冒烟、混合检索集成测试、构建、独立数据目录启动生产服务、Edge E2E，结果落盘到 `artifacts/evidence/verify.json`。E2E 的 11 项检查覆盖完整流程、本地推理无外部请求、量化清单、强制与自动 WASM 降级、单次 hybridSearch、增量导入、会话恢复与页面错误检查；同一套检查也在 Docker 镜像上复验通过。WebGPU 正路径在本机实测；无 GPU 的评测机只会得到 WASM 路径，报告如实标注，不伪造 FP16 通过。

证据与复现步骤见 [verification-sample.md](verification-sample.md)、[reproduction.md](reproduction.md)。
