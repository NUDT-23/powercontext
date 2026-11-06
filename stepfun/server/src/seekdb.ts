import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  Collection,
  FulltextIndexConfig,
  Schema,
  SeekdbClient,
  VectorIndexConfig,
  type Metadata,
} from "seekdb";
import { elapsedMs, nowMs } from "./timing.js";
import { EMBEDDING_DIMENSION } from "./embedding-codec.js";

export interface StoreOptions {
  dbPath: string;
  database: string;
  statePath: string;
}

export interface IncomingDoc {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  embedding: number[];
}

export interface ImportCounts {
  inserted: number;
  updated: number;
  skipped: number;
  count: number;
}

export interface StoredHit {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  score: number | null;
}

export interface HybridCallRecord {
  at: string;
  collection: string;
  queryText: string;
  nResults: number;
  resultIds: string[];
  scores: Array<number | null>;
  durationMs: number;
  rank: { rankWindowSize: number; rankConstant: number };
  callCount: number;
}

interface CollectionState {
  analyzer: string;
  lastRefreshAt: string | null;
  lastImportAt: string | null;
  docHashes: Record<string, string>;
}

interface StateFile {
  version: 1;
  collections: Record<string, CollectionState>;
}

const ANALYZER_CANDIDATES: Array<{
  analyzer: "ik" | "ngram2";
  properties: Record<string, unknown>;
}> = [
  { analyzer: "ik", properties: { ik_mode: "smart" } },
  { analyzer: "ngram2", properties: { min_ngram_size: 1, max_ngram_size: 2 } },
];

export class SeekdbStore {
  private readonly options: StoreOptions;
  private client: SeekdbClient | null = null;
  private readonly collections = new Map<string, Collection>();
  private readonly analyzers = new Map<string, string>();
  private state: StateFile = { version: 1, collections: {} };
  private queue: Promise<unknown> = Promise.resolve();
  private lastHybrid: HybridCallRecord | null = null;
  private hybridCallCount = 0;
  private indexManagerWarmed = false;

  constructor(options: StoreOptions) {
    this.options = options;
  }

  async init(): Promise<void> {
    fs.mkdirSync(path.dirname(this.options.dbPath), { recursive: true });
    this.client = new SeekdbClient({
      path: this.options.dbPath,
      database: this.options.database,
    });
    this.loadState();
  }

  get platform(): string {
    return `${process.platform}-${process.arch}`;
  }

  get database(): string {
    return this.options.database;
  }

  async listCollections(): Promise<
    Array<{
      name: string;
      count: number;
      analyzer: string;
      lastRefreshAt: string | null;
      lastImportAt: string | null;
    }>
  > {
    return this.serialize(async () => {
      const client = this.requireClient();
      const collections = await client.listCollections({
        withEmbeddingFunction: false,
      });
      const out = [];
      for (const collection of collections) {
        if (collection.name.startsWith("__")) continue;
        const state = this.ensureState(collection.name);
        out.push({
          name: collection.name,
          count: await collection.count(),
          analyzer: state.analyzer,
          lastRefreshAt: state.lastRefreshAt,
          lastImportAt: state.lastImportAt,
        });
      }
      return out.sort((a, b) => a.name.localeCompare(b.name));
    });
  }

  async createCollection(name: string): Promise<void> {
    await this.serialize(() => this.getCollection(name));
  }

  async collectionMeta(name: string): Promise<{
    name: string;
    count: number;
    lastRefreshAt: string | null;
    lastImportAt: string | null;
    analyzer: string;
  }> {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const state = this.ensureState(name);
      return {
        name,
        count: await collection.count(),
        lastRefreshAt: state.lastRefreshAt,
        lastImportAt: state.lastImportAt,
        analyzer: state.analyzer,
      };
    });
  }

  async deleteCollection(name: string): Promise<void> {
    return this.serialize(async () => {
      const client = this.requireClient();
      if (await client.hasCollection(name)) {
        await client.deleteCollection(name);
      }
      this.collections.delete(name);
      this.analyzers.delete(name);
      delete this.state.collections[name];
      this.saveState();
    });
  }

  async getCollectionState(name: string): Promise<{
    name: string;
    count: number;
    lastRefreshAt: string | null;
    lastImportAt: string | null;
    ids: string[];
    analyzer: string;
  }> {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const state = this.ensureState(name);
      const ids: string[] = [];
      const pageSize = 500;
      for (let offset = 0; ; offset += pageSize) {
        const page = await collection.get({
          limit: pageSize,
          offset,
          include: [],
        });
        ids.push(...page.ids);
        if (page.ids.length < pageSize) break;
      }
      return {
        name,
        count: await collection.count(),
        lastRefreshAt: state.lastRefreshAt,
        lastImportAt: state.lastImportAt,
        ids,
        analyzer: state.analyzer,
      };
    });
  }

  async importDocs(name: string, docs: IncomingDoc[]): Promise<ImportCounts> {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const state = this.ensureState(name);
      const ids: string[] = [];
      const documents: string[] = [];
      const metadatas: Array<Record<string, string | number | boolean>> = [];
      const embeddings: number[][] = [];
      let inserted = 0;
      let updated = 0;
      let skipped = 0;

      for (const doc of docs) {
        if (doc.embedding.length !== EMBEDDING_DIMENSION) {
          throw new Error(
            `document ${doc.id}: expected ${EMBEDDING_DIMENSION}-dim embedding, got ${doc.embedding.length}`
          );
        }
        const hash = hashDoc(doc);
        const previous = state.docHashes[doc.id];
        if (previous === hash) {
          skipped += 1;
          continue;
        }
        if (previous) updated += 1;
        else inserted += 1;
        ids.push(doc.id);
        documents.push(doc.text);
        metadatas.push(doc.metadata ?? {});
        embeddings.push(doc.embedding);
        state.docHashes[doc.id] = hash;
      }

      const batchSize = 128;
      for (let start = 0; start < ids.length; start += batchSize) {
        await collection.upsert({
          ids: ids.slice(start, start + batchSize),
          documents: documents.slice(start, start + batchSize),
          metadatas: metadatas.slice(start, start + batchSize),
          embeddings: embeddings.slice(start, start + batchSize),
        });
      }

      state.lastImportAt = new Date().toISOString();
      this.saveState();
      return {
        inserted,
        updated,
        skipped,
        count: await collection.count(),
      };
    });
  }

  async refresh(name: string): Promise<{ refreshMs: number; count: number }> {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const start = nowMs();
      await collection.refresh_index();
      const refreshMs = elapsedMs(start);
      const state = this.ensureState(name);
      state.lastRefreshAt = new Date().toISOString();
      this.saveState();
      return { refreshMs, count: await collection.count() };
    });
  }

  async hybridSearch(
    name: string,
    queryText: string,
    queryEmbedding: number[],
    nResults: number
  ): Promise<{ hits: StoredHit[]; durationMs: number; rank: HybridCallRecord["rank"] }> {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const rank = { rankWindowSize: 40, rankConstant: 60 };
      const start = nowMs();
      const result = await collection.hybridSearch({
        query: { whereDocument: { $contains: queryText } },
        knn: { queryEmbeddings: [queryEmbedding], nResults: nResults * 2 },
        rank: { rrf: rank },
        nResults,
        include: ["documents", "metadatas", "distances"],
      });
      const durationMs = elapsedMs(start);

      const ids = result.ids[0] ?? [];
      const docs = result.documents?.[0] ?? [];
      const metas = result.metadatas?.[0] ?? [];
      const distances = result.distances?.[0] ?? [];
      const hits: StoredHit[] = ids.map((id, index) => ({
        id,
        text: docs[index] ?? "",
        metadata: normalizeMetadata(metas[index]),
        score: distances[index] ?? null,
      }));

      this.hybridCallCount += 1;
      this.lastHybrid = {
        at: new Date().toISOString(),
        collection: name,
        queryText,
        nResults,
        resultIds: [...ids],
        scores: hits.map((hit) => hit.score),
        durationMs,
        rank,
        callCount: this.hybridCallCount,
      };
      return { hits, durationMs, rank };
    });
  }

  lastHybridCall(): HybridCallRecord | null {
    return this.lastHybrid;
  }

  analyzerFor(name: string): string {
    return this.analyzers.get(name) ?? this.state.collections[name]?.analyzer ?? "unknown";
  }

  async close(): Promise<void> {
    if (!this.client) return;
    try {
      await this.client.close();
    } catch {
      // embedded close occasionally reports an already-closed handle
    }
    this.client = null;
  }

  private requireClient(): SeekdbClient {
    if (!this.client) throw new Error("seekdb store is not initialized");
    return this.client;
  }

  private async getCollection(name: string): Promise<Collection> {
    const cached = this.collections.get(name);
    if (cached) return cached;
    const client = this.requireClient();
    let collection: Collection;
    if (await client.hasCollection(name)) {
      collection = await client.getCollection({
        name,
        embeddingFunction: null,
      });
      this.ensureState(name);
      if (!this.analyzers.has(name)) {
        this.analyzers.set(
          name,
          this.state.collections[name]?.analyzer ?? "unknown"
        );
      }
    } else {
      collection = await this.createWithFallback(name);
    }
    if (!this.indexManagerWarmed) {
      // seekdb's background index manager starts lazily and intermittently fails
      // its first build; a refresh on the empty collection warms it up so later
      // refreshes reliably publish the HNSW index.
      await collection.refresh_index();
      this.indexManagerWarmed = true;
    }
    this.collections.set(name, collection);
    return collection;
  }

  private async createWithFallback(name: string): Promise<Collection> {
    const client = this.requireClient();
    let lastError: unknown = null;
    for (const candidate of ANALYZER_CANDIDATES) {
      if (await client.hasCollection(name)) {
        await client.deleteCollection(name);
      }
      try {
        const created = await client.createCollection({
          name,
          schema: new Schema({
            vectorIndex: new VectorIndexConfig({
              hnsw: { dimension: EMBEDDING_DIMENSION, distance: "cosine" },
              embeddingFunction: null,
            }),
            fulltextIndex: new FulltextIndexConfig(
              candidate.analyzer,
              candidate.properties
            ),
          }),
        });
        const state = this.ensureState(name);
        state.analyzer = candidate.analyzer;
        this.analyzers.set(name, candidate.analyzer);
        this.saveState();
        return created;
      } catch (error) {
        lastError = error;
      }
    }
    throw new Error(
      `failed to create collection ${name}: ${
        lastError instanceof Error ? lastError.message : String(lastError)
      }`
    );
  }

  private ensureState(name: string): CollectionState {
    const existing = this.state.collections[name];
    if (existing) return existing;
    const created: CollectionState = {
      analyzer: this.analyzers.get(name) ?? "unknown",
      lastRefreshAt: null,
      lastImportAt: null,
      docHashes: {},
    };
    this.state.collections[name] = created;
    return created;
  }

  private serialize<T>(task: () => Promise<T>): Promise<T> {
    const run = this.queue.then(task, task);
    this.queue = run.catch(() => undefined);
    return run;
  }

  private loadState(): void {
    try {
      const raw = fs.readFileSync(this.options.statePath, "utf8");
      const parsed = JSON.parse(raw) as StateFile;
      if (parsed?.version === 1 && parsed.collections) {
        this.state = parsed;
      }
    } catch {
      this.state = { version: 1, collections: {} };
    }
    for (const [name, state] of Object.entries(this.state.collections)) {
      this.analyzers.set(name, state.analyzer);
    }
  }

  private saveState(): void {
    fs.mkdirSync(path.dirname(this.options.statePath), {
      recursive: true,
    });
    const tmp = `${this.options.statePath}.tmp`;
    fs.writeFileSync(tmp, `${JSON.stringify(this.state, null, 2)}\n`);
    fs.renameSync(tmp, this.options.statePath);
  }
}

function normalizeMetadata(
  value: Metadata | null | undefined
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  if (!value) return out;
  for (const [key, item] of Object.entries(value)) {
    if (
      typeof item === "string" ||
      typeof item === "number" ||
      typeof item === "boolean"
    ) {
      out[key] = item;
    }
  }
  return out;
}

function hashDoc(doc: IncomingDoc): string {
  const metadata = JSON.stringify(doc.metadata ?? {});
  return createHash("sha256")
    .update(`${doc.id}\n${doc.text}\n${metadata}`)
    .digest("hex");
}
