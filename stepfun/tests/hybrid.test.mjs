import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const DIM = 512;
const dbPath = path.resolve(process.env.STEPFUN_TEST_DB || "data/hybrid-test");
const dbName = process.env.STEPFUN_DB_NAME || "test";
const collectionName = "hybrid_test_docs";
const evidence = { startedAt: new Date().toISOString(), checks: [], ok: false };

fs.rmSync(dbPath, { recursive: true, force: true });

function embed(text) {
  const v = new Float32Array(DIM);
  const s = `#${text}`;
  for (let i = 0; i < s.length; i += 1) {
    for (let n = 1; n <= 2; n += 1) {
      const piece = s.slice(i, i + n);
      if (!piece) continue;
      const h = createHash("md5").update(piece).digest();
      const idx = h.readUInt32LE(0) % DIM;
      v[idx] += (h[4] & 1) === 1 ? 1 : -1;
    }
  }
  let norm = 0;
  for (const x of v) norm += x * x;
  norm = Math.sqrt(norm) || 1;
  return Array.from(v, (x) => x / norm);
}

async function refreshIndexReliably(collection) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await collection.refresh_index();
      return;
    } catch (error) {
      if (attempt >= 2 || !/timeout|ret=-4012/i.test(String(error?.message || error))) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
}

function check(name, fn) {
  const start = Date.now();
  return Promise.resolve()
    .then(fn)
    .then((value) => {
      evidence.checks.push({ name, ok: true, ms: Date.now() - start, value });
      console.log(`[ok] ${name}`);
      return value;
    })
    .catch((error) => {
      evidence.checks.push({
        name,
        ok: false,
        ms: Date.now() - start,
        error: String(error?.stack || error),
      });
      throw error;
    });
}

const docs = [
  ["h1", "seekdb 是 OceanBase 推出的轻量级向量数据库，支持向量检索和全文检索。"],
  ["h2", "全文检索使用倒排索引与分词器，适合精确关键词匹配。"],
  ["h3", "向量检索依赖 HNSW 近似最近邻索引与余弦距离。"],
  ["h4", "WebGPU 让浏览器可以利用显卡加速 ONNX 推理。"],
  ["h5", "INT8 量化压缩模型体积，可能改变少量排序结果。"],
  ["h6", "RRF 倒数排名融合把多路检索结果按名次合并。"],
];

let client;
try {
  client = new SeekdbClient({ path: dbPath, database: dbName });

  let analyzer = "ik";
  const makeSchema = (name, props) =>
    new Schema({
      vectorIndex: new VectorIndexConfig({
        hnsw: { dimension: DIM, distance: "cosine" },
        embeddingFunction: null,
      }),
      fulltextIndex: new FulltextIndexConfig(name, props),
    });

  let collection;
  await check("create collection", async () => {
    try {
      await client.createCollection({
        name: collectionName,
        schema: makeSchema("ik", { ik_mode: "smart" }),
      });
    } catch {
      analyzer = "ngram2";
      await client.createCollection({
        name: collectionName,
        schema: makeSchema("ngram2", { min_ngram_size: 1, max_ngram_size: 2 }),
      });
    }
    collection = await client.getCollection({
      name: collectionName,
      embeddingFunction: null,
    });
    return { analyzer };
  });

  await check("warm up index manager", async () => {
    const start = Date.now();
    await refreshIndexReliably(collection);
    return { ms: Date.now() - start };
  });

  await check("import documents", async () => {
    await collection.add({
      ids: docs.map(([id]) => id),
      documents: docs.map(([, text]) => text),
      metadatas: docs.map(() => ({ suite: "hybrid" })),
      embeddings: docs.map(([, text]) => embed(text)),
    });
    const count = await collection.count();
    assert.equal(count, docs.length);
    return { count };
  });

  await check("refresh publishes vectors", async () => {
    const start = Date.now();
    await refreshIndexReliably(collection);
    return { ms: Date.now() - start };
  });

  const queryText = "向量检索";
  const queryEmbedding = embed(queryText);

  const hybrid = await check("hybridSearch returns RRF results", async () => {
    const result = await collection.hybridSearch({
      query: { whereDocument: { $contains: queryText } },
      knn: { queryEmbeddings: [queryEmbedding], nResults: 6 },
      rank: { rrf: { rankWindowSize: 40, rankConstant: 60 } },
      nResults: 3,
      include: ["documents", "metadatas", "distances"],
    });
    const ids = (result.ids?.[0] || []).filter(Boolean);
    assert.ok(ids.length > 0, "hybrid returned no ids");
    assert.ok(ids.length <= 3, "hybrid ignored nResults");
    const scores = result.distances?.[0] || [];
    assert.equal(scores.length, ids.length);
    for (const score of scores) {
      assert.ok(typeof score === "number" && score > 0, "missing RRF score");
    }
    return { ids, scores };
  });

  const vectorIds = await check("vector channel is queryable", async () => {
    const result = await collection.query({
      queryEmbeddings: [queryEmbedding],
      nResults: 3,
      include: ["documents"],
    });
    const ids = (result.ids?.[0] || []).filter(Boolean);
    assert.ok(ids.length > 0, "HNSW vector index returned no results");
    return ids;
  });

  const fulltextIds = await check("fulltext channel is queryable", async () => {
    const result = await collection.get({
      whereDocument: { $contains: queryText },
      limit: 3,
      include: ["documents"],
    });
    assert.ok(result.ids.length > 0, "fulltext search returned no results");
    return result.ids;
  });

  await check("hybrid differs from at least one single channel", async () => {
    const hybridOrder = hybrid.ids.join(",");
    const vectorOrder = vectorIds.join(",");
    const fulltextOrder = fulltextIds.join(",");
    assert.ok(
      hybridOrder !== vectorOrder || hybridOrder !== fulltextOrder,
      `hybrid order (${hybridOrder}) equals both vector (${vectorOrder}) and fulltext (${fulltextOrder})`
    );
    return { hybridOrder, vectorOrder, fulltextOrder };
  });

  await check("incremental upsert + refresh is searchable", async () => {
    const text = "新增文档讨论量子纠缠与量子计算。";
    await collection.upsert({
      ids: ["h7"],
      documents: [text],
      metadatas: [{ suite: "hybrid", incremental: true }],
      embeddings: [embed(text)],
    });
    assert.equal(await collection.count(), docs.length + 1);
    await refreshIndexReliably(collection);
    const found = await collection.get({
      whereDocument: { $contains: "量子纠缠" },
      limit: 5,
      include: ["documents"],
    });
    assert.deepEqual(found.ids, ["h7"]);
    await assert.rejects(() =>
      collection.query({ queryEmbeddings: [embed("x").slice(0, 10)], nResults: 1 })
    );
    return { ids: found.ids };
  });

  evidence.ok = evidence.checks.every((item) => item.ok);
  console.log("HYBRID TEST PASS");
} catch (error) {
  evidence.error = String(error?.stack || error);
  console.error("HYBRID TEST FAIL:", error?.message || error);
} finally {
  try {
    await client?.close();
  } catch {}
  evidence.finishedAt = new Date().toISOString();
  const dir = path.resolve("artifacts/evidence");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, "hybrid-test.json"),
    `${JSON.stringify(evidence, null, 2)}\n`
  );
  setTimeout(() => process.exit(evidence.ok ? 0 : 1), 200);
}
