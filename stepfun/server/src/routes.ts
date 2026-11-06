import fs from "node:fs";
import path from "node:path";
import { Router, type Request } from "express";
import type {
  ImportResponse,
  SearchHit,
  SearchResponse,
} from "../../shared/types.js";
import { loadCorpus } from "./corpus.js";
import { decodeEmbedding, decodeEmbeddingList } from "./embedding-codec.js";
import { runHybridSearch } from "./hybrid.js";
import { aggregateQuality, median, percentile } from "./metrics.js";
import { SeekdbStore } from "./seekdb.js";
import { elapsedMs, nowMs, round } from "./timing.js";

export interface RouterOptions {
  rootDir: string;
}

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

export function createRouter(store: SeekdbStore, options: RouterOptions): Router {
  const router = Router();
  const corpus = loadCorpus(options.rootDir);

  router.get("/health", async (_req, res) => {
    const collections = await store.listCollections();
    res.json({
      ok: true,
      seekdb: {
        version: readSeekdbVersion(options.rootDir),
        platform: store.platform,
        database: store.database,
      },
      collections: collections.map((collection) => ({
        ...collection,
        dimensions: 512,
      })),
      embedding: { location: "browser" },
      serverTime: new Date().toISOString(),
    });
  });

  router.get("/corpus", (_req, res) => {
    res.json(corpus);
  });

  router.post("/collections", async (req, res) => {
    const name = requireCollectionName(req.body?.name);
    await store.createCollection(name);
    res.status(201).json({ ok: true, name });
  });

  router.delete("/collections/:name", async (req, res) => {
    const name = requireCollectionName(req.params.name);
    await store.deleteCollection(name);
    res.json({ ok: true, name });
  });

  router.get("/collections/:name/state", async (req, res) => {
    const name = requireCollectionName(req.params.name);
    res.json(await store.getCollectionState(name));
  });

  router.post("/collections/:name/refresh", async (req, res) => {
    const name = requireCollectionName(req.params.name);
    const refreshed = await store.refresh(name);
    const meta = await store.collectionMeta(name);
    res.json({
      ok: true,
      name,
      refreshMs: round(refreshed.refreshMs),
      count: meta.count,
      lastRefreshAt: meta.lastRefreshAt,
    });
  });

  router.post("/import", async (req, res) => {
    const started = nowMs();
    const body = req.body ?? {};
    const collection = requireCollectionName(body.collection);
    const rawDocs = body.docs;
    if (!Array.isArray(rawDocs) || rawDocs.length === 0) {
      throw badRequest("docs must be a non-empty array");
    }
    if (rawDocs.length > 2048) {
      throw badRequest("docs per request is limited to 2048");
    }

    const decodeStart = nowMs();
    const docs = rawDocs.map((raw: unknown, index: number) => {
      const item = raw as Record<string, unknown>;
      const id = typeof item?.id === "string" ? item.id.trim() : "";
      const text = typeof item?.text === "string" ? item.text : "";
      if (!id) throw badRequest(`docs[${index}].id must be a non-empty string`);
      if (!text.trim()) throw badRequest(`docs[${index}].text is empty`);
      const embedding = decodeEmbedding(
        String(item?.embedding ?? ""),
        `docs[${index}].embedding`
      );
      const metadata =
        item?.metadata && typeof item.metadata === "object"
          ? (item.metadata as Record<string, string | number | boolean>)
          : {};
      return { id, text, metadata, embedding };
    });
    const seen = new Set<string>();
    for (const doc of docs) {
      if (seen.has(doc.id)) throw badRequest(`duplicate id in request: ${doc.id}`);
      seen.add(doc.id);
    }
    const decodeMs = elapsedMs(decodeStart);

    const writeStart = nowMs();
    const counts = await store.importDocs(collection, docs);
    const writeMs = elapsedMs(writeStart);

    let refreshMs = 0;
    let meta = await store.collectionMeta(collection);
    if (body.refresh !== false) {
      const refreshed = await store.refresh(collection);
      refreshMs = refreshed.refreshMs;
      meta = await store.collectionMeta(collection);
    }

    const response: ImportResponse = {
      inserted: counts.inserted,
      updated: counts.updated,
      skipped: counts.skipped,
      count: meta.count,
      lastRefreshAt: meta.lastRefreshAt,
      timing: {
        decodeMs: round(decodeMs),
        writeMs: round(writeMs),
        refreshMs: round(refreshMs),
      },
    };
    res.json({ ...response, totalMs: round(elapsedMs(started)) });
  });

  router.post("/search", async (req, res) => {
    const started = nowMs();
    const body = req.body ?? {};
    const collection = requireCollectionName(body.collection);
    const queryText = typeof body.queryText === "string" ? body.queryText : "";
    if (!queryText.trim()) throw badRequest("queryText is required");
    const queryEmbedding = decodeEmbedding(
      String(body.queryEmbedding ?? ""),
      "queryEmbedding"
    );
    const nResults =
      typeof body.nResults === "number" && body.nResults > 0 ? body.nResults : 5;

    const { hits, durationMs, hybrid } = await runHybridSearch(
      store,
      collection,
      queryText,
      queryEmbedding,
      nResults
    );
    const response: SearchResponse = {
      results: hits.map(toSearchHit),
      timing: {
        seekdbMs: round(durationMs),
        totalMs: round(elapsedMs(started)),
      },
      hybrid,
    };
    res.json(response);
  });

  router.post("/eval", async (req, res) => {
    const body = req.body ?? {};
    const collection = requireCollectionName(body.collection);
    const rawQueries = body.queries;
    if (!Array.isArray(rawQueries) || rawQueries.length === 0) {
      throw badRequest("queries must be a non-empty array");
    }
    const queries = rawQueries.map((raw: unknown, index: number) => {
      const item = raw as Record<string, unknown>;
      const id = typeof item?.id === "string" ? item.id : `q${index}`;
      const text = typeof item?.text === "string" ? item.text.trim() : "";
      if (!text) throw badRequest(`queries[${index}].text is required`);
      return {
        id,
        text,
        embedding: decodeEmbedding(
          String(item?.embedding ?? ""),
          `queries[${index}].embedding`
        ),
      };
    });
    const qrels = Array.isArray(body.qrels) ? body.qrels : corpus.qrels;
    const nResults =
      typeof body.nResults === "number" && body.nResults > 0
        ? Math.min(body.nResults, 20)
        : 10;

    const rankings: Array<{ queryId: string; ids: string[] }> = [];
    const searchTimings: number[] = [];
    for (const query of queries) {
      const { hits, durationMs } = await runHybridSearch(
        store,
        collection,
        query.text,
        query.embedding,
        nResults
      );
      rankings.push({ queryId: query.id, ids: hits.map((hit) => hit.id) });
      searchTimings.push(durationMs);
    }

    res.json({
      collection,
      nResults,
      metrics: aggregateQuality(rankings, qrels),
      rankings,
      timing: {
        queries: queries.length,
        timingsMs: searchTimings.map((value) => round(value)),
        medianMs: round(median(searchTimings)),
        p95Ms: round(percentile(searchTimings, 95)),
        totalMs: round(searchTimings.reduce((sum, value) => sum + value, 0)),
      },
    });
  });

  router.get("/bench/results", (_req, res) => {
    const file = path.join(options.rootDir, "artifacts", "bench", "results.json");
    if (!fs.existsSync(file)) {
      res.json({ payload: null });
      return;
    }
    try {
      res.json(JSON.parse(fs.readFileSync(file, "utf8")));
    } catch (error) {
      throw new Error(`failed to read benchmark results: ${String(error)}`);
    }
  });

  router.post("/bench", async (req, res) => {
    const payload = req.body ?? {};
    const dir = path.join(options.rootDir, "artifacts", "bench");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, "results.json");
    fs.writeFileSync(
      file,
      `${JSON.stringify({ receivedAt: new Date().toISOString(), payload }, null, 2)}\n`
    );
    res.json({ ok: true, path: path.relative(options.rootDir, file) });
  });

  router.get("/debug/hybrid", (_req, res) => {
    const last = store.lastHybridCall();
    res.json({
      callCount: last?.callCount ?? 0,
      last,
    });
  });

  return router;
}

function toSearchHit(hit: {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  score: number | null;
}): SearchHit {
  return {
    id: hit.id,
    text: hit.text,
    metadata: hit.metadata,
    score: hit.score === null ? null : round(hit.score, 6),
  };
}

function requireCollectionName(value: unknown): string {
  const name = typeof value === "string" ? value.trim() : "";
  if (!NAME_PATTERN.test(name)) {
    throw badRequest(
      "collection must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
    );
  }
  return name;
}

function badRequest(message: string): Error & { statusCode: number } {
  const error = new Error(message) as Error & { statusCode: number };
  error.statusCode = 400;
  return error;
}

function readSeekdbVersion(rootDir: string): string {
  try {
    const pkg = JSON.parse(
      fs.readFileSync(
        path.join(rootDir, "node_modules", "seekdb", "package.json"),
        "utf8"
      )
    );
    return String(pkg.version ?? "unknown");
  } catch {
    return "unknown";
  }
}
