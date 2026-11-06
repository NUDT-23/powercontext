import {
  env,
  pipeline,
  type FeatureExtractionPipeline,
} from "@huggingface/transformers";
import {
  backendLabel,
  errorMessage,
  forcedWasm,
  probeWebGPU,
  type BackendInfo,
  type BackendKind,
  type Precision,
} from "./backend";

export const MODEL_ID = "Xenova/bge-small-zh-v1.5";
export const EMBEDDING_DIMENSION = 512;

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.useBrowserCache = true;
env.localModelPath = "/models/";
(env.backends.onnx.wasm as { wasmPaths?: string }).wasmPaths = "/ort/";

export interface EmbedderOptions {
  forceWasm?: boolean;
  onProgress?: (message: string) => void;
}

const DTYPE_BY_PRECISION: Record<Precision, "fp32" | "fp16" | "q8"> = {
  fp32: "fp32",
  fp16: "fp16",
  int8: "q8",
};

export class Embedder {
  readonly info: BackendInfo;
  readonly modelId = MODEL_ID;
  modelLoadMs = 0;
  firstEmbedMs = 0;
  private readonly extractor: FeatureExtractionPipeline;

  private constructor(info: BackendInfo, extractor: FeatureExtractionPipeline) {
    this.info = info;
    this.extractor = extractor;
  }

  static async create(options: EmbedderOptions = {}): Promise<Embedder> {
    const report = options.onProgress ?? (() => undefined);
    configureRuntime();
    const forceWasmMode = options.forceWasm ?? forcedWasm();

    let reason: string | null = null;
    if (forceWasmMode) {
      reason = "已通过 ?forceWasm=1 强制使用 WASM";
    } else {
      report("检测 WebGPU…");
      const probe = await probeWebGPU();
      if (probe.available) {
        try {
          report(`WebGPU 可用 (${probe.adapter})，加载 FP16 模型…`);
          return await Embedder.build("webgpu", "fp16", probe.adapter, report, null);
        } catch (error) {
          reason = `WebGPU/FP16 初始化失败，已降级到 WASM/INT8：${errorMessage(error)}`;
        }
      } else {
        reason = probe.reason;
      }
    }

    report(`${reason ?? "使用 WASM"}；加载 INT8 量化模型…`);
    return Embedder.build("wasm", "int8", null, report, reason);
  }

  static async createVariant(
    precision: Precision,
    options: { onProgress?: (message: string) => void } = {}
  ): Promise<Embedder> {
    const report = options.onProgress ?? (() => undefined);
    configureRuntime();
    if (precision === "fp16") {
      const probe = await probeWebGPU();
      if (!probe.available) {
        throw new Error(probe.reason ?? "WebGPU 不可用，无法加载 FP16");
      }
      return Embedder.build("webgpu", "fp16", probe.adapter, report, null);
    }
    return Embedder.build("wasm", precision, null, report, null);
  }

  private static async build(
    backend: BackendKind,
    precision: Precision,
    gpuAdapter: string | null,
    report: (message: string) => void,
    reason: string | null
  ): Promise<Embedder> {
    report(`加载 ${MODEL_ID} (${precision}, ${backend})…`);
    const started = performance.now();
    const extractor = await pipeline("feature-extraction", MODEL_ID, {
      device: backend,
      dtype: DTYPE_BY_PRECISION[precision],
    });
    const embedder = new Embedder(
      {
        backend,
        precision,
        label: backendLabel(backend, precision),
        reason,
        gpuAdapter,
      },
      extractor
    );
    embedder.modelLoadMs = performance.now() - started;
    await embedder.embed(["预热"], { batchSize: 1 });
    return embedder;
  }

  async embed(
    texts: string[],
    options: {
      batchSize?: number;
      onProgress?: (done: number, total: number) => void;
    } = {}
  ): Promise<number[][]> {
    const batchSize = Math.max(1, options.batchSize ?? 8);
    const vectors: number[][] = [];
    const started = performance.now();
    for (let start = 0; start < texts.length; start += batchSize) {
      const batch = texts.slice(start, start + batchSize);
      const tensor = await this.extractor(batch, {
        pooling: "cls",
        normalize: true,
      });
      const rows = tensor.tolist() as number[][];
      for (const row of rows) {
        if (row.length !== EMBEDDING_DIMENSION) {
          throw new Error(
            `模型输出维度 ${row.length}，预期 ${EMBEDDING_DIMENSION}`
          );
        }
        vectors.push(row);
      }
      options.onProgress?.(vectors.length, texts.length);
    }
    if (this.firstEmbedMs === 0) {
      this.firstEmbedMs = performance.now() - started;
    }
    return vectors;
  }

  async embedOne(text: string): Promise<number[]> {
    const [vector] = await this.embed([text], { batchSize: 1 });
    return vector;
  }

  async dispose(): Promise<void> {
    await this.extractor.dispose();
  }

  get precision(): Precision {
    return this.info.precision;
  }
}

function configureRuntime(): void {
  const threads =
    typeof crossOriginIsolated !== "undefined" && crossOriginIsolated
      ? Math.max(1, Math.min(4, navigator.hardwareConcurrency || 1))
      : 1;
  const wasm = env.backends.onnx.wasm;
  if (wasm) {
    wasm.numThreads = threads;
    wasm.proxy = false;
  }
}

export function vectorToBase64(vector: number[]): string {
  const floats = new Float32Array(vector);
  const bytes = new Uint8Array(
    floats.buffer,
    floats.byteOffset,
    floats.byteLength
  );
  let binary = "";
  const step = 0x8000;
  for (let index = 0; index < bytes.length; index += step) {
    binary += String.fromCharCode(...bytes.subarray(index, index + step));
  }
  return btoa(binary);
}
