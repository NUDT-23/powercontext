# 性能与质量基准

- 运行时间：2026-11-06T16:05:37.342Z
- 设备：WebGPU · FP16 · intel gen-12lp · 20 线程
- 浏览器：Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0
- 模型：Xenova/bge-small-zh-v1.5（512 维，CLS pooling + L2 归一化）
- 语料：56 篇文档 / 30 条人工查询

## 量化对比

| 精度 | 推理后端 | 模型体积 | 压缩比 | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 | wasm | 90.46 MiB | 1.00× | 0.711 | 0.856 | 0.845 | 0.879 |
| INT8 | wasm | 22.90 MiB | 3.95× | 0.700 | 0.856 | 0.844 | 0.880 |
| FP16 | webgpu | 45.30 MiB | 2.00× | 0.711 | 0.856 | 0.846 | 0.879 |

## 推理与检索性能

| 精度 | 冷启动加载 | 首次向量化 | 热态吞吐 | 热态中位数 | 热态 p95 | 检索中位数 | 检索 p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 (wasm) | 2176.86 ms | 20.34 ms | 29.7 docs/s | 269.0 ms | 348.9 ms | 3.0 ms | 3.9 ms |
| INT8 (wasm) | 703.09 ms | 19 ms | 47.7 docs/s | 167.8 ms | 204.0 ms | 3.1 ms | 3.8 ms |
| FP16 (webgpu) | 1383.09 ms | 324.98 ms | 201.7 docs/s | 39.7 ms | 52.5 ms | 3.1 ms | 4.1 ms |

端到端（查询向量化 + seekdb 混合检索）中位数 **13.1 ms**，p95 **18.3 ms**；纯 seekdb 检索中位数 3.11 ms。

## 方法

- 文档向量化 batch=8；每个精度先预热 3 轮、再测量 7 轮，取中位数与 p95。
- 质量指标使用同一份 30 条人工查询与 89 条 0/1/2 分级 qrels，经 `/api/eval` 在 seekdb 内做混合检索后计算 Recall@K 与 nDCG@K。
- 每个精度写入独立集合（`bench_fp32` / `bench_int8` / `bench_fp16`），入库后 `refresh_index()`，确保向量索引可检索。
- 端到端延迟 = 浏览器端查询向量化（主后端）+ seekdb 混合检索（服务端计时），不计网络与渲染。

## 观察

- INT8（q8）体积 22.90 MiB，为 FP32 的 3.95× 压缩；Recall@5 相对 FP32 变化 -1.1 个百分点，nDCG@5 变化 -0.1 个百分点，nDCG@10 变化 0.1 个百分点。
- FP16（WebGPU）体积 45.30 MiB（2.00×），质量指标与 FP32 基线基本一致；热态文档向量化 201.7 docs/s，较 WASM 47.7 docs/s 明显更快，代价是冷启动加载更久。
- 无 GPU 时的 WASM INT8 仍保持 47.7 docs/s 的文档向量化吞吐，且检索延迟与 WebGPU 路径相同（检索由 seekdb 完成，与推理后端无关）。

## 复现

```bash
cd stepfun
npm install
npm run fetch-models          # 仓库已内置 int8/fp16；fp32 基线可选
npm run build
npm start                     # 打开 http://127.0.0.1:8787 → 「基准与报告」→ 运行完整基准
npm run generate:report       # 重新生成本文件与 artifacts/bench/results.md
```

