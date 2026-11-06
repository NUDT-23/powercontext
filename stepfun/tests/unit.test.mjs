import test from "node:test";
import assert from "node:assert/strict";
import { chunkText, hashChunkId } from "../web/src/chunker.ts";
import {
  aggregateQuality,
  mean,
  median,
  ndcgAt,
  percentile,
  recallAt,
  relevantByQuery,
} from "../server/src/metrics.ts";

test("chunkText returns no chunks for blank input", () => {
  assert.deepEqual(chunkText("   \n\t "), []);
});

test("chunkText keeps a short passage in one chunk", () => {
  const chunks = chunkText("seekdb 支持向量检索。混合检索使用 RRF 融合。");
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].index, 0);
  assert.match(chunks[0].text, /seekdb/);
});

test("chunkText splits long text with overlap and sequential indexes", () => {
  const sentence = "这是用于测试切分的一句中文字符串。";
  const text = Array.from({ length: 40 }, () => sentence).join("");
  const chunks = chunkText(text);
  assert.ok(chunks.length > 1, "expected multiple chunks");
  chunks.forEach((chunk, index) => {
    assert.equal(chunk.index, index);
    assert.ok(chunk.text.length <= 200 + 50);
  });
  const joined = chunks.map((chunk) => chunk.text).join("");
  assert.ok(joined.includes(sentence.slice(0, 6)));
});

test("chunkText hard-splits a sentence longer than the target", () => {
  const chunks = chunkText("一".repeat(520), 200, 50);
  assert.equal(chunks.length, 4);
  assert.equal(chunks[1].text.length, 200);
});

test("hashChunkId is deterministic and differs across content", async () => {
  const a = await hashChunkId("source", { index: 0, text: "alpha" });
  const b = await hashChunkId("source", { index: 0, text: "alpha" });
  const c = await hashChunkId("source", { index: 0, text: "beta" });
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.match(a, /^[0-9a-f]{32}$/);
});

test("recallAt and ndcgAt respect cutoffs and graded relevance", () => {
  const relevant = new Map([
    ["d1", 2],
    ["d3", 1],
  ]);
  assert.equal(recallAt(["d9", "d1"], relevant, 1), 0);
  assert.equal(recallAt(["d9", "d1", "d3"], relevant, 5), 1);
  assert.equal(recallAt(["d9"], relevant, 5), 0);
  assert.equal(ndcgAt(["d1", "d3"], relevant, 5), 1);
  assert.ok(
    Math.abs(ndcgAt(["d1", "d9"], relevant, 5) - 0.8262346571285599) < 1e-12
  );
  const gradedIdcg = 3 + 1 / Math.log2(3);
  assert.ok(
    Math.abs(ndcgAt(["d9", "d1"], relevant, 5) - 3 / Math.log2(3) / gradedIdcg) <
      1e-12
  );
  assert.equal(ndcgAt(["d1"], new Map(), 5), null);
});

test("aggregateQuality averages queries with graded labels", () => {
  const qrels = [
    { queryId: "q1", docId: "d1", relevance: 2 },
    { queryId: "q1", docId: "d2", relevance: 1 },
    { queryId: "q2", docId: "d3", relevance: 1 },
  ];
  const metrics = aggregateQuality(
    [
      { queryId: "q1", ids: ["d1", "d2", "d3"] },
      { queryId: "q2", ids: ["d9", "d3"] },
      { queryId: "q3", ids: ["d1"] },
    ],
    qrels
  );
  assert.equal(metrics.evaluatedQueries, 2);
  assert.equal(metrics.recallAt5, 1);
  assert.ok(metrics.ndcgAt5 > 0.7 && metrics.ndcgAt5 <= 1);
});

test("relevantByQuery ignores non-positive labels", () => {
  const map = relevantByQuery([
    { queryId: "q1", docId: "d1", relevance: 0 },
    { queryId: "q1", docId: "d2", relevance: 1 },
  ]);
  assert.deepEqual([...map.get("q1").keys()], ["d2"]);
});

test("mean, median, percentile handle empty and unsorted input", () => {
  assert.equal(mean([]), 0);
  assert.equal(mean([1, 2, 3]), 2);
  assert.equal(median([]), 0);
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 3, 2]), 2.5);
  assert.equal(percentile([], 95), 0);
  assert.equal(percentile([5, 1, 3, 2, 4], 100), 5);
  assert.equal(percentile([5, 1, 3, 2, 4], 50), 3);
});
