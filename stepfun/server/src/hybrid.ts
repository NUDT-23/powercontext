import type { HybridInfo } from "../../shared/types.js";
import type { SeekdbStore } from "./seekdb.js";

const MAX_RESULTS = 50;

export interface HybridRunResult {
  hits: Awaited<ReturnType<SeekdbStore["hybridSearch"]>>["hits"];
  durationMs: number;
  hybrid: HybridInfo;
}

/**
 * The only ranking entry point in the application. Both retrieval legs are
 * combined by seekdb's DBMS_HYBRID_SEARCH (RRF); the client never merges
 * result lists.
 */
export async function runHybridSearch(
  store: SeekdbStore,
  collection: string,
  queryText: string,
  queryEmbedding: number[],
  nResults = 5
): Promise<HybridRunResult> {
  const text = queryText.trim();
  if (!text) throw new Error("queryText is empty");
  const limit = Math.max(1, Math.min(Math.trunc(nResults) || 5, MAX_RESULTS));
  const { hits, durationMs, rank } = await store.hybridSearch(
    collection,
    text,
    queryEmbedding,
    limit
  );
  return {
    hits,
    durationMs,
    hybrid: {
      executedInDb: true,
      rrf: rank,
      analyzer: store.analyzerFor(collection),
    },
  };
}
