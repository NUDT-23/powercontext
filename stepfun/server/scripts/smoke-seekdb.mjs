import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const DIM = 512;
const dbPath = path.resolve(process.env.STEPFUN_SMOKE_DB || "data/smoke-seekdb");
const dbName = process.env.STEPFUN_DB_NAME || "test";
const collectionName = "smoke_docs";

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

function makeSchema(analyzer, properties) {
  return new Schema({
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension: DIM, distance: "cosine" },
      embeddingFunction: null,
    }),
    fulltextIndex: new FulltextIndexConfig(analyzer, properties),
  });
}

function elapsed(start) {
  return Number(process.hrtime.bigint() - start) / 1e6;
}

const docs = [
  ["d1", "seekdb 是 OceanBase 推出的轻量级向量数据库，支持向量检索和全文检索。", "seekdb"],
  ["d2", "混合检索把向量相似度和关键词匹配结合起来，常用 RRF 融合排序。", "hybrid"],
  ["d3", "WebGPU 允许浏览器使用显卡加速推理，不可用时可以降级到 WASM。", "webgpu"],
  ["d4", "模型量化为 INT8 后体积显著降低，但可能带来少量检索质量损失。", "quantization"],
  ["d5", "OceanBase 支持分布式部署和多租户，seekdb 可以理解为它的轻量版本。", "oceanbase"],
  ["d6", "RRF 是倒数排名融合算法，把多路检索结果按排名位置相加得到最终分数。", "rrf"],
];

const result = {
  startedAt: new Date().toISOString(),
  platform: process.platform,
  arch: process.arch,
  node: process.version,
  dbPath,
  steps: [],
  ok: false,
};

function step(name, fn) {
  const start = process.hrtime.bigint();
  return Promise.resolve()
    .then(fn)
    .then((value) => {
      result.steps.push({ name, ok: true, ms: elapsed(start), value });
      console.log(`[ok] ${name} (${elapsed(start).toFixed(1)} ms)`);
      return value;
    })
    .catch((error) => {
      result.steps.push({
        name,
        ok: false,
        ms: elapsed(start),
        error: error?.stack || String(error),
      });
      console.error(`[fail] ${name}: ${error?.message || error}`);
      throw error;
    });
}

let client;
let collection;
let analyzerUsed = "ik";

try {
  client = new SeekdbClient({ path: dbPath, database: dbName });
  await step("connect", async () => ({ connected: client.isConnected() }));

  async function createWith(analyzer, properties) {
    if (await client.hasCollection(collectionName)) {
      await client.deleteCollection(collectionName);
    }
    await step(`createCollection(${analyzer})`, async () => {
      const created = await client.createCollection({
        name: collectionName,
        schema: makeSchema(analyzer, properties),
      });
      return { name: created.name, dimension: created.dimension };
    });
    return client.getCollection({ name: collectionName, embeddingFunction: null });
  }

  try {
    collection = await createWith("ik", { ik_mode: "smart" });
  } catch (error) {
    analyzerUsed = "ngram2";
    console.warn(`ik analyzer failed, falling back to ngram2: ${error?.message || error}`);
    collection = await createWith("ngram2", { min_ngram_size: 1, max_ngram_size: 2 });
  }

  await step("warmup_refresh", async () => {
    await collection.refresh_index();
    return { warmed: true };
  });

  const embeddings = docs.map(([, text]) => embed(text));
  await step("add", async () => {
    await collection.add({
      ids: docs.map(([id]) => id),
      documents: docs.map(([, text]) => text),
      metadatas: docs.map(([, , topic]) => ({ topic })),
      embeddings,
    });
    return { inserted: docs.length };
  });

  const count = await step("count", () => collection.count());

  await step("refresh_index", async () => {
    await collection.refresh_index();
    return { refreshed: true };
  });

  const hybrid = await step("hybridSearch", () =>
    collection.hybridSearch({
      query: { whereDocument: { $contains: "向量检索" } },
      knn: { queryEmbeddings: [embed("向量检索")] },
      rank: { rrf: { rankWindowSize: 20, rankConstant: 60 } },
      nResults: 3,
      include: ["documents", "metadatas", "distances"],
    })
  );

  const vectorOnly = await step("query(vector only)", () =>
    collection.query({
      queryEmbeddings: [embed("向量检索")],
      nResults: 3,
      include: ["documents", "metadatas", "distances"],
    })
  );

  const fulltext = await step("get(fulltext only)", () =>
    collection.get({
      whereDocument: { $contains: "向量检索" },
      limit: 3,
      include: ["documents", "metadatas"],
    })
  );

  const hybridIds = (hybrid.ids?.[0] || []).filter(Boolean);
  const vectorIds = (vectorOnly.ids?.[0] || []).filter(Boolean);
  const fulltextIds = fulltext.ids || [];

  result.checks = {
    count,
    analyzerUsed,
    hybridIds,
    vectorIds,
    fulltextIds,
    hybridDiffersFromVector: hybridIds.join(",") !== vectorIds.join(","),
    hybridDiffersFromFulltext: hybridIds.join(",") !== fulltextIds.join(","),
    hybridHasScores: Boolean(hybrid.distances?.[0]?.length),
  };
  result.ok =
    count === docs.length &&
    hybridIds.length > 0 &&
    vectorIds.length > 0 &&
    fulltextIds.length > 0 &&
    result.checks.hybridHasScores;

  console.log(JSON.stringify(result.checks, null, 2));
} catch (error) {
  result.error = error?.stack || String(error);
} finally {
  try {
    await client?.close();
  } catch {}
  result.finishedAt = new Date().toISOString();
  const evidenceDir = path.resolve("artifacts/evidence");
  fs.mkdirSync(evidenceDir, { recursive: true });
  fs.writeFileSync(
    path.join(evidenceDir, "smoke-seekdb.json"),
    `${JSON.stringify(result, null, 2)}\n`
  );
  console.log(result.ok ? "SMOKE PASS" : "SMOKE FAIL");
  setTimeout(() => process.exit(result.ok ? 0 : 1), 200);
}
