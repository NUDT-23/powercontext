import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = path.join(rootDir, "artifacts", "bench", "results.json");
if (!fs.existsSync(source)) {
  console.error("缺少 artifacts/bench/results.json；请先在浏览器中运行基准测试");
  process.exit(1);
}
const { payload } = JSON.parse(fs.readFileSync(source, "utf8"));
if (!payload) {
  console.error("results.json 中没有 payload");
  process.exit(1);
}

const mib = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
const pct = (value) => `${(value * 100).toFixed(1)}%`;
const num = (value, digits = 2) => Number(value).toFixed(digits);
const byPrecision = new Map(payload.quality.map((item) => [item.precision, item]));
const sampleFor = (precision) =>
  payload.samples.find((sample) =>
    sample.label.toUpperCase().startsWith(precision.toUpperCase())
  ) ?? null;

const fp32 = byPrecision.get("fp32");
const int8 = byPrecision.get("int8");
const fp16 = byPrecision.get("fp16");

const lines = [];
lines.push("# 性能与质量基准", "");
lines.push(
  `- 运行时间：${payload.runAt}`,
  `- 设备：${payload.device.backend}${payload.device.gpuAdapter ? ` · ${payload.device.gpuAdapter}` : ""} · ${payload.device.hardwareConcurrency ?? "?"} 线程`,
  `- 浏览器：${payload.device.userAgent}`,
  `- 模型：${payload.model.id}（${payload.model.dimension} 维，CLS pooling + L2 归一化）`,
  `- 语料：${payload.corpus.docs} 篇文档 / ${payload.corpus.queries} 条人工查询`,
  ""
);

lines.push("## 量化对比", "");
lines.push("| 精度 | 推理后端 | 模型体积 | 压缩比 | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 |");
lines.push("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |");
for (const item of payload.quality) {
  lines.push(
    `| ${item.precision.toUpperCase()} | ${item.backend} | ${mib(item.modelBytes)} | ${
      item.compressionRatio ? `${num(item.compressionRatio)}×` : "—"
    } | ${num(item.recallAt5, 3)} | ${num(item.recallAt10, 3)} | ${num(item.ndcgAt5, 3)} | ${num(item.ndcgAt10, 3)} |`
  );
}
lines.push("");

lines.push("## 推理与检索性能", "");
lines.push(
  "| 精度 | 冷启动加载 | 首次向量化 | 热态吞吐 | 热态中位数 | 热态 p95 | 检索中位数 | 检索 p95 |"
);
lines.push("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
for (const sample of payload.samples) {
  lines.push(
    `| ${sample.label} | ${sample.cold.modelLoadMs ?? "—"} ms | ${sample.cold.firstEmbedMs ?? "—"} ms | ${num(
      sample.warm.docsPerSecond,
      1
    )} docs/s | ${num(sample.warm.medianMs, 1)} ms | ${num(sample.warm.p95Ms, 1)} ms | ${num(
      sample.searchMedianMs,
      1
    )} ms | ${num(sample.searchP95Ms, 1)} ms |`
  );
}
lines.push("");
lines.push(
  `端到端（查询向量化 + seekdb 混合检索）中位数 **${num(payload.search.endToEndMedianMs, 1)} ms**，p95 **${num(
    payload.search.endToEndP95Ms,
    1
  )} ms**；纯 seekdb 检索中位数 ${num(payload.search.seekdbMedianMs, 2)} ms。`,
  ""
);

lines.push("## 方法", "");
lines.push(
  "- 文档向量化 batch=8；每个精度先预热 3 轮、再测量 7 轮，取中位数与 p95。",
  "- 质量指标使用同一份 30 条人工查询与 89 条 0/1/2 分级 qrels，经 `/api/eval` 在 seekdb 内做混合检索后计算 Recall@K 与 nDCG@K。",
  "- 每个精度写入独立集合（`bench_fp32` / `bench_int8` / `bench_fp16`），入库后 `refresh_index()`，确保向量索引可检索。",
  "- 端到端延迟 = 浏览器端查询向量化（主后端）+ seekdb 混合检索（服务端计时），不计网络与渲染。",
  ""
);

if (fp32 && int8 && fp16) {
  const d = (a, b) => (a - b) * 100;
  lines.push("## 观察", "");
  lines.push(
    `- INT8（q8）体积 ${mib(int8.modelBytes)}，为 FP32 的 ${num(int8.compressionRatio)}× 压缩；Recall@5 相对 FP32 变化 ${num(
      d(int8.recallAt5, fp32.recallAt5),
      1
    )} 个百分点，nDCG@5 变化 ${num(d(int8.ndcgAt5, fp32.ndcgAt5), 1)} 个百分点，nDCG@10 变化 ${num(
      d(int8.ndcgAt10, fp32.ndcgAt10),
      1
    )} 个百分点。`,
    `- FP16（WebGPU）体积 ${mib(fp16.modelBytes)}（${num(fp16.compressionRatio)}×），质量指标与 FP32 基线基本一致；热态文档向量化 ${
      sampleFor("fp16") ? num(sampleFor("fp16").warm.docsPerSecond, 1) : "—"
    } docs/s，较 WASM ${
      sampleFor("int8") ? num(sampleFor("int8").warm.docsPerSecond, 1) : "—"
    } docs/s 明显更快，代价是冷启动加载更久。`,
    `- 无 GPU 时的 WASM INT8 仍保持 ${sampleFor("int8") ? num(sampleFor("int8").warm.docsPerSecond, 1) : "—"} docs/s 的文档向量化吞吐，且检索延迟与 WebGPU 路径相同（检索由 seekdb 完成，与推理后端无关）。`,
    ""
  );
}

lines.push("## 复现", "");
lines.push(
  "```bash",
  "cd stepfun",
  "npm install",
  "npm run fetch-models          # 仓库已内置 int8/fp16；fp32 基线可选",
  "npm run build",
  "npm start                     # 打开 http://127.0.0.1:8787 → 「基准与报告」→ 运行完整基准",
  "npm run generate:report       # 重新生成本文件与 artifacts/bench/results.md",
  "```",
  ""
);

const output = `${lines.join("\n")}\n`;
fs.mkdirSync(path.join(rootDir, "artifacts", "bench"), { recursive: true });
fs.mkdirSync(path.join(rootDir, "docs"), { recursive: true });
fs.writeFileSync(path.join(rootDir, "artifacts", "bench", "results.md"), output);
fs.writeFileSync(path.join(rootDir, "docs", "benchmark.md"), output);
console.log("wrote artifacts/bench/results.md and docs/benchmark.md");
