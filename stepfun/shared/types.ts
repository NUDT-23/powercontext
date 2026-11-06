export type BackendKind = "webgpu" | "wasm";
export type ModelPrecision = "fp32" | "fp16" | "int8";
export type BackendLabel = `${BackendKind}/${ModelPrecision}`;

export interface DocInput {
  id: string;
  text: string;
  metadata?: Record<string, string | number | boolean>;
  /** base64-encoded little-endian Float32 array (512 dims = 2048 bytes) */
  embedding: string;
}

export interface ImportRequest {
  collection: string;
  docs: DocInput[];
  refresh?: boolean;
  sourceSummary?: string;
}

export interface ImportTiming {
  decodeMs: number;
  writeMs: number;
  refreshMs: number;
}

export interface ImportResponse {
  inserted: number;
  updated: number;
  skipped: number;
  count: number;
  lastRefreshAt: string | null;
  timing: ImportTiming;
}

export interface SearchRequest {
  collection: string;
  queryText: string;
  queryEmbedding: string;
  nResults?: number;
}

export interface SearchHit {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  score: number | null;
}

export interface SearchTiming {
  seekdbMs: number;
  totalMs: number;
}

export interface HybridInfo {
  executedInDb: true;
  rrf: { rankWindowSize: number; rankConstant: number };
  analyzer: string;
}

export interface SearchResponse {
  results: SearchHit[];
  timing: SearchTiming;
  hybrid: HybridInfo;
}

export interface CollectionInfo {
  name: string;
  count: number;
  dimensions: number;
  analyzer: string;
  lastRefreshAt: string | null;
  lastImportAt: string | null;
}

export interface HealthResponse {
  ok: boolean;
  seekdb: { version: string; platform: string; database: string };
  collections: CollectionInfo[];
  embedding: { location: "browser" };
  serverTime: string;
}

export interface CollectionState {
  name: string;
  count: number;
  lastRefreshAt: string | null;
  lastImportAt: string | null;
  ids: string[];
  analyzer: string;
}

export interface BenchmarkSample {
  label: string;
  backend: BackendLabel;
  batchSize: number;
  docs: number;
  cold: {
    modelLoadMs: number | null;
    firstEmbedMs: number | null;
  };
  warm: {
    embedMs: number[];
    medianMs: number;
    p95Ms: number;
    docsPerSecond: number;
  };
  searchMs: number[];
  searchMedianMs: number;
  searchP95Ms: number;
}

export interface QualityMetrics {
  precision: ModelPrecision;
  modelBytes: number;
  compressionRatio: number;
  recallAt5: number;
  recallAt10: number;
  ndcgAt5: number;
  ndcgAt10: number;
  backend: BackendKind | "reference";
}

export interface BenchmarkPayload {
  runAt: string;
  device: {
    backend: BackendLabel;
    userAgent: string;
    hardwareConcurrency: number | null;
    gpuAdapter: string | null;
    reason: string | null;
  };
  model: {
    id: string;
    dimension: number;
    files: Record<string, number>;
  };
  corpus: { docs: number; queries: number };
  samples: BenchmarkSample[];
  quality: QualityMetrics[];
  search: {
    seekdbMedianMs: number;
    seekdbP95Ms: number;
    endToEndMedianMs: number;
    endToEndP95Ms: number;
  };
}

export interface CorpusDoc {
  id: string;
  title: string;
  text: string;
  tags: string[];
}

export interface EvalQuery {
  id: string;
  query: string;
}

export interface Qrel {
  queryId: string;
  docId: string;
  relevance: 0 | 1 | 2;
}
