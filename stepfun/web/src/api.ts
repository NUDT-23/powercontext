import type {
  BenchmarkPayload,
  CollectionState,
  HealthResponse,
  ImportResponse,
  Qrel,
  SearchResponse,
} from "@shared/types";

export interface WireDoc {
  id: string;
  text: string;
  metadata?: Record<string, string | number | boolean>;
  embedding: string;
}

export interface EvalResponse {
  collection: string;
  nResults: number;
  metrics: {
    recallAt5: number;
    recallAt10: number;
    ndcgAt5: number;
    ndcgAt10: number;
    evaluatedQueries: number;
  };
  rankings: Array<{ queryId: string; ids: string[] }>;
  timing: {
    queries: number;
    timingsMs: number[];
    medianMs: number;
    p95Ms: number;
    totalMs: number;
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // keep status-only message
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),

  corpus: () =>
    request<{
      docs: Array<{ id: string; title: string; text: string; tags: string[] }>;
      queries: Array<{ id: string; query: string }>;
      qrels: Qrel[];
    }>("/api/corpus"),

  createCollection: (name: string) =>
    request<{ ok: boolean; name: string }>("/api/collections", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  deleteCollection: (name: string) =>
    request<{ ok: boolean }>(`/api/collections/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  collectionState: (name: string) =>
    request<CollectionState>(`/api/collections/${encodeURIComponent(name)}/state`),

  refreshCollection: (name: string) =>
    request<{
      ok: boolean;
      refreshMs: number;
      count: number;
      lastRefreshAt: string | null;
    }>(`/api/collections/${encodeURIComponent(name)}/refresh`, {
      method: "POST",
    }),

  importDocs: (payload: {
    collection: string;
    docs: WireDoc[];
    refresh: boolean;
  }) =>
    request<ImportResponse & { totalMs: number }>("/api/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  search: (payload: {
    collection: string;
    queryText: string;
    queryEmbedding: string;
    nResults: number;
  }) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  evaluate: (payload: {
    collection: string;
    queries: Array<{ id: string; text: string; embedding: string }>;
    qrels: Qrel[];
    nResults?: number;
  }) =>
    request<EvalResponse>("/api/eval", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  saveBenchmark: (payload: BenchmarkPayload) =>
    request<{ ok: boolean; path: string }>("/api/bench", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  benchResults: () =>
    request<{ payload: BenchmarkPayload | null }>("/api/bench/results"),

  lastHybrid: () =>
    request<{
      callCount: number;
      last: {
        collection: string;
        queryText: string;
        resultIds: string[];
        durationMs: number;
        callCount: number;
      } | null;
    }>("/api/debug/hybrid"),
};
