import type {
  BenchmarkPayload,
  BenchmarkSample,
  QualityMetrics,
} from "@shared/types";
import { api } from "./api";
import type { Precision } from "./backend";
import { Embedder, vectorToBase64 } from "./embedder";

interface ManifestVariant {
  bytes: number;
  compressionRatio?: number;
  sha256: string | null;
}

interface ModelManifest {
  repo: string;
  dimension: number;
  files: Record<string, { bytes: number; sha256: string }>;
  variants: Record<Precision, ManifestVariant | null>;
}

export interface BenchResult {
  payload: BenchmarkPayload;
  notes: string[];
  savedPath: string;
}

const WARMUP_ROUNDS = 3;
const MEASURE_ROUNDS = 7;

export async function runBenchmark(
  current: Embedder,
  onProgress: (message: string) => void
): Promise<BenchResult> {
  const [corpus, manifest] = await Promise.all([
    api.corpus(),
    loadManifest(),
  ]);
  if (corpus.docs.length === 0) {
    throw new Error("语料为空，请先运行 scripts 中的语料生成或检查 corpus/");
  }

  const notes: string[] = [];
  const variants: Precision[] = ["int8"];
  if (manifest.variants.fp32 === null) {
    notes.push("FP32 基线缺失：先运行 npm run fetch-models:fp32 以获得完整压缩比与质量对照");
  } else if (await modelFileAvailable("onnx/model.onnx")) {
    variants.unshift("fp32");
  } else {
    notes.push(
      "FP32 基线文件未随仓库分发：本次跳过 FP32 质量对照；压缩比仍按模型清单记录"
    );
  }
  try {
    const { probeWebGPU } = await import("./backend");
    const probe = await probeWebGPU();
    if (probe.available) variants.push("fp16");
    else notes.push(`FP16 未评测：${probe.reason ?? "WebGPU 不可用"}`);
  } catch (error) {
    notes.push(`FP16 未评测：${String(error)}`);
  }

  const samples: BenchmarkSample[] = [];
  const quality: QualityMetrics[] = [];
  let primaryEval: Awaited<ReturnType<typeof evaluateVariant>> | null = null;

  for (const precision of variants) {
    onProgress(`基准：${precision.toUpperCase()} 开始`);
    let embedder = current;
    let owned = false;
    if (current.precision !== precision) {
      try {
        embedder = await Embedder.createVariant(precision, {
          onProgress: (message) => onProgress(`基准：${message}`),
        });
        owned = true;
      } catch (error) {
        notes.push(`${precision.toUpperCase()} 未评测：${String(error)}`);
        continue;
      }
    }
    try {
      const result = await evaluateVariant(
        embedder,
        precision,
        corpus,
        manifest,
        onProgress
      );
      samples.push(result.sample);
      quality.push(result.quality);
      if (current.precision === precision || primaryEval === null) {
        primaryEval = result;
      }
    } finally {
      if (owned) await embedder.dispose();
    }
  }

  if (!primaryEval) throw new Error("没有可用的基准变体");

  const qMedian = median(primaryEval.queryEmbedMs);
  const qP95 = percentile(primaryEval.queryEmbedMs, 95);
  const payload: BenchmarkPayload = {
    runAt: new Date().toISOString(),
    device: {
      backend: current.info.label as BenchmarkPayload["device"]["backend"],
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency ?? null,
      gpuAdapter: current.info.gpuAdapter,
      reason: current.info.reason,
    },
    model: {
      id: current.modelId,
      dimension: 512,
      files: Object.fromEntries(
        Object.entries(manifest.files).map(([name, meta]) => [name, meta.bytes])
      ),
    },
    corpus: { docs: corpus.docs.length, queries: corpus.queries.length },
    samples,
    quality,
    search: {
      seekdbMedianMs: primaryEval.eval.timing.medianMs,
      seekdbP95Ms: primaryEval.eval.timing.p95Ms,
      endToEndMedianMs: round(qMedian + primaryEval.eval.timing.medianMs),
      endToEndP95Ms: round(qP95 + primaryEval.eval.timing.p95Ms),
    },
  };

  onProgress("保存基准结果…");
  const saved = await api.saveBenchmark(payload);
  return { payload, notes, savedPath: saved.path };
}

async function evaluateVariant(
  embedder: Embedder,
  precision: Precision,
  corpus: Awaited<ReturnType<typeof api.corpus>>,
  manifest: ModelManifest,
  onProgress: (message: string) => void
) {
  const collection = `bench_${precision}`;
  await api.deleteCollection(collection).catch(() => undefined);
  await api.createCollection(collection);

  const texts = corpus.docs.map((doc) => `${doc.title}\n${doc.text}`);
  const vectors = await embedder.embed(texts, {
    batchSize: 8,
    onProgress: (done, total) =>
      onProgress(`基准：${precision.toUpperCase()} 文档向量化 ${done}/${total}`),
  });

  let inserted = 0;
  const importTimings = { decodeMs: 0, writeMs: 0, refreshMs: 0 };
  const batchSize = 32;
  for (let start = 0; start < corpus.docs.length; start += batchSize) {
    const slice = corpus.docs.slice(start, start + batchSize);
    const isLast = start + batchSize >= corpus.docs.length;
    const response = await api.importDocs({
      collection,
      docs: slice.map((doc, offset) => ({
        id: doc.id,
        text: texts[start + offset],
        metadata: { title: doc.title, tags: doc.tags.join(","), variant: precision },
        embedding: vectorToBase64(vectors[start + offset]),
      })),
      refresh: isLast,
    });
    inserted += response.inserted;
    importTimings.decodeMs += response.timing.decodeMs;
    importTimings.writeMs += response.timing.writeMs;
    importTimings.refreshMs += response.timing.refreshMs;
    onProgress(
      `基准：${precision.toUpperCase()} 导入 ${Math.min(start + batchSize, corpus.docs.length)}/${corpus.docs.length}`
    );
  }

  const warmTimes: number[] = [];
  for (let round = 0; round < WARMUP_ROUNDS + MEASURE_ROUNDS; round += 1) {
    const start = (round * 8) % Math.max(1, texts.length);
    const batch = texts.slice(start, start + 8);
    if (batch.length === 0) break;
    const t0 = performance.now();
    await embedder.embed(batch, { batchSize: 8 });
    const elapsed = performance.now() - t0;
    if (round >= WARMUP_ROUNDS) warmTimes.push(elapsed);
  }

  const queryEmbedMs: number[] = [];
  const queryPayload = [];
  for (const query of corpus.queries) {
    const t0 = performance.now();
    const vector = await embedder.embedOne(query.query);
    queryEmbedMs.push(performance.now() - t0);
    queryPayload.push({
      id: query.id,
      text: query.query,
      embedding: vectorToBase64(vector),
    });
  }
  onProgress(`基准：${precision.toUpperCase()} 混合检索评测 ${corpus.queries.length} 条查询`);
  const evaluated = await api.evaluate({
    collection,
    queries: queryPayload,
    qrels: corpus.qrels,
    nResults: 10,
  });

  const warmMedian = median(warmTimes);
  const sample: BenchmarkSample = {
    label: `${precision.toUpperCase()} (${embedder.info.backend})`,
    backend: embedder.info.label as BenchmarkSample["backend"],
    batchSize: 8,
    docs: corpus.docs.length,
    cold: {
      modelLoadMs: round(embedder.modelLoadMs),
      firstEmbedMs: round(embedder.firstEmbedMs),
    },
    warm: {
      embedMs: warmTimes.map((value) => round(value)),
      medianMs: round(warmMedian),
      p95Ms: round(percentile(warmTimes, 95)),
      docsPerSecond: round((8 / warmMedian) * 1000),
    },
    searchMs: evaluated.timing.timingsMs,
    searchMedianMs: evaluated.timing.medianMs,
    searchP95Ms: evaluated.timing.p95Ms,
  };

  const variant = manifest.variants[precision];
  const quality: QualityMetrics = {
    precision,
    modelBytes: variant?.bytes ?? 0,
    compressionRatio: variant?.compressionRatio ?? 0,
    recallAt5: round(evaluated.metrics.recallAt5, 4),
    recallAt10: round(evaluated.metrics.recallAt10, 4),
    ndcgAt5: round(evaluated.metrics.ndcgAt5, 4),
    ndcgAt10: round(evaluated.metrics.ndcgAt10, 4),
    backend: embedder.info.backend,
  };

  return {
    sample,
    quality,
    eval: evaluated,
    queryEmbedMs,
    inserted,
    importTimings,
  };
}

async function modelFileAvailable(file: string): Promise<boolean> {
  try {
    const response = await fetch(`/models/Xenova/bge-small-zh-v1.5/${file}`, {
      method: "HEAD",
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function loadManifest(): Promise<ModelManifest> {
  const response = await fetch(
    `/models/${"Xenova/bge-small-zh-v1.5"}/model-manifest.json`
  );
  if (!response.ok) {
    throw new Error(`读取模型清单失败：HTTP ${response.status}`);
  }
  return (await response.json()) as ModelManifest;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)
  );
  return sorted[index];
}

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}
