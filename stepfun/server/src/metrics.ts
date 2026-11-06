import type { Qrel } from "../../shared/types.js";

export interface RankingMetrics {
  recallAt5: number;
  recallAt10: number;
  ndcgAt5: number;
  ndcgAt10: number;
  evaluatedQueries: number;
}

export function relevantByQuery(qrels: Qrel[]): Map<string, Map<string, number>> {
  const map = new Map<string, Map<string, number>>();
  for (const qrel of qrels) {
    if (!qrel || !qrel.queryId) continue;
    let docs = map.get(qrel.queryId);
    if (!docs) {
      docs = new Map();
      map.set(qrel.queryId, docs);
    }
    if (qrel.relevance > 0) docs.set(qrel.docId, qrel.relevance);
  }
  return map;
}

export function recallAt(ranked: string[], relevant: Map<string, number>, k: number) {
  if (relevant.size === 0) return null;
  let hits = 0;
  for (const id of ranked.slice(0, k)) {
    if (relevant.has(id)) hits += 1;
  }
  return hits / relevant.size;
}

export function ndcgAt(ranked: string[], relevant: Map<string, number>, k: number) {
  const gains = [...relevant.values()].sort((a, b) => b - a);
  if (gains.length === 0) return null;
  let dcg = 0;
  for (let i = 0; i < Math.min(k, ranked.length); i += 1) {
    const rel = relevant.get(ranked[i]);
    if (!rel) continue;
    dcg += (2 ** rel - 1) / Math.log2(i + 2);
  }
  let idcg = 0;
  for (let i = 0; i < Math.min(k, gains.length); i += 1) {
    idcg += (2 ** gains[i] - 1) / Math.log2(i + 2);
  }
  return idcg === 0 ? null : dcg / idcg;
}

export function aggregateQuality(
  rankings: Array<{ queryId: string; ids: string[] }>,
  qrels: Qrel[]
): RankingMetrics {
  const relevant = relevantByQuery(qrels);
  const buckets = {
    recallAt5: [] as number[],
    recallAt10: [] as number[],
    ndcgAt5: [] as number[],
    ndcgAt10: [] as number[],
  };
  for (const ranking of rankings) {
    const rel = relevant.get(ranking.queryId);
    if (!rel || rel.size === 0) continue;
    const r5 = recallAt(ranking.ids, rel, 5);
    const r10 = recallAt(ranking.ids, rel, 10);
    const n5 = ndcgAt(ranking.ids, rel, 5);
    const n10 = ndcgAt(ranking.ids, rel, 10);
    if (r5 !== null) buckets.recallAt5.push(r5);
    if (r10 !== null) buckets.recallAt10.push(r10);
    if (n5 !== null) buckets.ndcgAt5.push(n5);
    if (n10 !== null) buckets.ndcgAt10.push(n10);
  }
  return {
    recallAt5: mean(buckets.recallAt5),
    recallAt10: mean(buckets.recallAt10),
    ndcgAt5: mean(buckets.ndcgAt5),
    ndcgAt10: mean(buckets.ndcgAt10),
    evaluatedQueries: buckets.recallAt5.length,
  };
}

export function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)
  );
  return sorted[index];
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}
