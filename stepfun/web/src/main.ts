import type {
  BenchmarkPayload,
  CollectionInfo,
  HealthResponse,
  SearchHit,
} from "@shared/types";
import { api } from "./api";
import { runBenchmark } from "./bench";
import { chunkText, hashChunkId } from "./chunker";
import { Embedder, vectorToBase64 } from "./embedder";
import { loadSession, saveSession } from "./session";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

const session = loadSession();
let collections: CollectionInfo[] = [];
let activeCollection: string | null = session.activeCollection;
let embedder: Embedder | null = null;
let health: HealthResponse | null = null;
let lastRefreshAt: string | null = null;
let docCount = 0;
let busy = false;

const backendBadge = el<HTMLSpanElement>("backend-badge");
const seekdbBadge = el<HTMLSpanElement>("seekdb-badge");
const collectionSelect = el<HTMLSelectElement>("collection-select");
const collectionMeta = el<HTMLParagraphElement>("collection-meta");
const newCollectionInput = el<HTMLInputElement>("new-collection-input");
const createCollectionBtn = el<HTMLButtonElement>("create-collection-btn");
const deleteCollectionBtn = el<HTMLButtonElement>("delete-collection-btn");
const refreshIndexBtn = el<HTMLButtonElement>("refresh-index-btn");
const importText = el<HTMLTextAreaElement>("import-text");
const importFile = el<HTMLInputElement>("import-file");
const importTextBtn = el<HTMLButtonElement>("import-text-btn");
const importSampleBtn = el<HTMLButtonElement>("import-sample-btn");
const importClearBtn = el<HTMLButtonElement>("import-clear-btn");
const importProgress = el<HTMLDivElement>("import-progress");
const importProgressBar = el<HTMLDivElement>("import-progress-bar");
const importStatus = el<HTMLParagraphElement>("import-status");
const importStats = el<HTMLDivElement>("import-stats");
const searchInput = el<HTMLInputElement>("search-input");
const searchNResults = el<HTMLSelectElement>("search-nresults");
const searchBtn = el<HTMLButtonElement>("search-btn");
const searchStatus = el<HTMLParagraphElement>("search-status");
const searchTiming = el<HTMLParagraphElement>("search-timing");
const searchResults = el<HTMLDivElement>("search-results");
const modelSummary = el<HTMLDivElement>("model-summary");
const benchRunBtn = el<HTMLButtonElement>("bench-run-btn");
const benchStatus = el<HTMLSpanElement>("bench-status");
const benchNotes = el<HTMLDivElement>("bench-notes");
const benchQuality = el<HTMLDivElement>("bench-quality");
const benchJson = el<HTMLPreElement>("bench-json");
const runtimeDetails = el<HTMLParagraphElement>("runtime-details");

void boot();

async function boot(): Promise<void> {
  bindTabs();
  bindActions();
  setBadge(backendBadge, "加载本地模型…", "loading");
  setBadge(seekdbBadge, "seekdb 检测中…", "loading");

  const embedderTask = Embedder.create({
    onProgress: (message) => setBadge(backendBadge, message, "loading"),
  })
    .then((instance) => {
      embedder = instance;
      renderBackendBadge();
      setImportEnabled(true);
      updateSearchAvailability();
      return instance;
    })
    .catch((error: unknown) => {
      setBadge(backendBadge, "模型加载失败", "error");
      backendBadge.title = errorText(error);
      importStatus.textContent = `模型加载失败：${errorText(error)}`;
      throw error;
    });

  const healthTask = api
    .health()
    .then((response) => {
      health = response;
      renderSeekdbBadge();
    })
    .catch((error: unknown) => {
      setBadge(seekdbBadge, "seekdb 连接失败", "error");
      seekdbBadge.title = errorText(error);
    });

  await Promise.allSettled([embedderTask, healthTask]);
  collections = health?.collections ?? [];
  renderCollections();
  void loadManifestSummary();
  setImportEnabled(Boolean(embedder));
  updateSearchAvailability();
}

function bindTabs(): void {
  const tabs = document.querySelectorAll<HTMLButtonElement>(".tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      document.querySelectorAll<HTMLElement>(".panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${tab.dataset.tab}`);
      });
      if (tab.dataset.tab === "bench") void showStoredBenchmark();
    });
  });
}

function bindActions(): void {
  collectionSelect.addEventListener("change", () => {
    activeCollection = collectionSelect.value || null;
    persistSession();
    void loadCollectionState();
  });

  createCollectionBtn.addEventListener("click", () => {
    void withBusy(async () => {
      const name = newCollectionInput.value.trim();
      if (!NAME_RE.test(name)) throw new Error("集合名不合法：需以字母/数字开头，仅含字母、数字、-_. ");
      await api.createCollection(name);
      newCollectionInput.value = "";
      activeCollection = name;
      session.activeCollection = name;
      saveSession(session);
      await reloadCollections();
      await loadCollectionState();
    }, "创建集合失败");
  });

  deleteCollectionBtn.addEventListener("click", () => {
    if (!activeCollection) return;
    const name = activeCollection;
    if (!window.confirm(`删除集合 ${name}？其中所有文档与向量都会被移除。`)) return;
    void withBusy(async () => {
      await api.deleteCollection(name);
      delete session.importedDocs[name];
      delete session.lastRefreshAt[name];
      activeCollection = null;
      session.activeCollection = null;
      saveSession(session);
      await reloadCollections();
      await loadCollectionState();
    }, "删除集合失败");
  });

  refreshIndexBtn.addEventListener("click", () => {
    if (!activeCollection) return;
    void withBusy(async () => {
      const result = await api.refreshCollection(activeCollection as string);
      lastRefreshAt = result.lastRefreshAt;
      session.lastRefreshAt[activeCollection as string] = result.lastRefreshAt;
      saveSession(session);
      collectionMeta.textContent = `${result.count} 条文档 · 索引已刷新（${result.refreshMs.toFixed(
        1
      )} ms）· ${formatTime(result.lastRefreshAt)}`;
      updateSearchAvailability();
      await reloadCollections();
    }, "刷新索引失败");
  });

  importTextBtn.addEventListener("click", () => {
    void importPastedText();
  });

  importFile.addEventListener("change", () => {
    void importFiles();
  });

  importSampleBtn.addEventListener("click", () => {
    void importSampleCorpus();
  });

  importClearBtn.addEventListener("click", () => {
    importText.value = "";
    importFile.value = "";
    importStats.classList.add("hidden");
    importProgress.classList.add("hidden");
  });

  searchBtn.addEventListener("click", () => {
    void performSearch();
  });

  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void performSearch();
    }
  });

  benchRunBtn.addEventListener("click", () => {
    void runBench();
  });
}

async function importPastedText(): Promise<void> {
  const text = importText.value.trim();
  if (!text) {
    setImportMessage("请先粘贴文本。", true);
    return;
  }
  await withBusy(async () => {
    const collection = await resolveCollection();
    const sourceKey = await sha256Hex(text);
    await importSources(
      [
        {
          source: `paste:${sourceKey}`,
          text,
          metadata: { source: "paste" },
        },
      ],
      collection
    );
  }, "导入失败");
}

async function importFiles(): Promise<void> {
  const files = Array.from(importFile.files ?? []);
  if (files.length === 0) return;
  await withBusy(async () => {
    const items: SourceItem[] = [];
    for (const file of files) {
      const text = await file.text();
      if (file.name.endsWith(".jsonl")) {
        const lines = text.split(/\r?\n/).filter(Boolean);
        for (let index = 0; index < lines.length; index += 1) {
          try {
            const record = JSON.parse(lines[index]) as {
              id?: string;
              title?: string;
              text?: string;
            };
            const body = [record.title, record.text].filter(Boolean).join("\n");
            if (!body) continue;
            items.push({
              id: record.id,
              source: `${file.name}#${index + 1}`,
              text: body,
              metadata: { source: file.name, line: index + 1 },
            });
          } catch {
            // skip malformed line, keep the rest importable
          }
        }
      } else {
        items.push({
          source: file.name,
          text,
          metadata: { source: file.name },
        });
      }
    }
    if (items.length === 0) throw new Error("文件中没有可导入的文本");
    const collection = await resolveCollection();
    await importSources(items, collection);
    importFile.value = "";
  }, "导入失败");
}

async function importSampleCorpus(): Promise<void> {
  await withBusy(async () => {
    importProgress.classList.remove("hidden");
    setProgress(0, "读取示例语料…");
    const corpus = await api.corpus();
    const collection = "corpus";
    if (!collections.some((item) => item.name === collection)) {
      await api.createCollection(collection);
      await reloadCollections();
    }
    activeCollection = collection;
    session.activeCollection = collection;
    saveSession(session);
    await reloadCollections();
    await importSources(
      corpus.docs.map((doc) => ({
        id: doc.id,
        source: doc.id,
        text: `${doc.title}\n${doc.text}`,
        metadata: {
          source: "corpus",
          title: doc.title,
          tags: doc.tags.join(","),
        },
      })),
      collection
    );
  }, "导入示例语料失败");
}

interface SourceItem {
  id?: string;
  source: string;
  text: string;
  metadata?: Record<string, string | number | boolean>;
}

async function importSources(items: SourceItem[], collection: string): Promise<void> {
  if (!embedder) throw new Error("模型尚未就绪");
  importProgress.classList.remove("hidden");
  importStats.classList.add("hidden");
  setProgress(0, "切分文本…");

  const chunks: Array<{
    id: string;
    text: string;
    metadata: Record<string, string | number | boolean>;
  }> = [];
  for (const item of items) {
    const parts = chunkText(item.text);
    for (const part of parts) {
      const id = item.id
        ? parts.length === 1
          ? item.id
          : `${item.id}-${part.index}`
        : await hashChunkId(item.source, part);
      chunks.push({
        id,
        text: part.text,
        metadata: { ...(item.metadata ?? {}), chunk: part.index },
      });
    }
  }
  if (chunks.length === 0) throw new Error("没有可导入的文本");

  const vectors = await embedder.embed(
    chunks.map((chunk) => chunk.text),
    {
      batchSize: 8,
      onProgress: (done, total) =>
        setProgress((done / total) * 0.7, `本地向量化 ${done}/${total} 块`),
    }
  );

  const totals = {
    inserted: 0,
    updated: 0,
    skipped: 0,
    count: 0,
    decodeMs: 0,
    writeMs: 0,
    refreshMs: 0,
  };
  const batchSize = 64;
  for (let start = 0; start < chunks.length; start += batchSize) {
    const slice = chunks.slice(start, start + batchSize);
    const isLast = start + batchSize >= chunks.length;
    const response = await api.importDocs({
      collection,
      docs: slice.map((chunk, offset) => ({
        id: chunk.id,
        text: chunk.text,
        metadata: chunk.metadata,
        embedding: vectorToBase64(vectors[start + offset]),
      })),
      refresh: isLast,
    });
    totals.inserted += response.inserted;
    totals.updated += response.updated;
    totals.skipped += response.skipped;
    totals.count = response.count;
    totals.decodeMs += response.timing.decodeMs;
    totals.writeMs += response.timing.writeMs;
    totals.refreshMs += response.timing.refreshMs;
    lastRefreshAt = response.lastRefreshAt;
    setProgress(
      0.7 + ((start + slice.length) / chunks.length) * 0.3,
      `写入 seekdb ${Math.min(start + batchSize, chunks.length)}/${chunks.length}`
    );
  }

  setProgress(1, "完成");
  session.importedDocs[collection] = totals.count;
  session.lastRefreshAt[collection] = lastRefreshAt;
  session.activeCollection = collection;
  saveSession(session);

  renderStats([
    ["分块", String(chunks.length)],
    ["新增", String(totals.inserted)],
    ["更新", String(totals.updated)],
    ["跳过", String(totals.skipped)],
    ["集合总量", String(totals.count)],
    ["写入", `${totals.writeMs.toFixed(1)} ms`],
    ["刷新索引", `${totals.refreshMs.toFixed(1)} ms`],
    ["向量化", embedder.info.label],
  ]);
  importStatus.textContent = `导入完成：新增 ${totals.inserted}，更新 ${totals.updated}，跳过 ${totals.skipped}`;

  await reloadCollections();
  collectionSelect.value = collection;
  await loadCollectionState();
}

async function performSearch(): Promise<void> {
  const queryText = searchInput.value.trim();
  if (!queryText) {
    searchStatus.textContent = "请输入查询。";
    return;
  }
  if (!embedder) {
    searchStatus.textContent = "模型尚未就绪。";
    return;
  }
  if (!activeCollection) {
    searchStatus.textContent = "请先选择或导入一个集合。";
    return;
  }
  searchBtn.disabled = true;
  searchStatus.textContent = "本地向量化 + seekdb 混合检索…";
  searchTiming.textContent = "";
  try {
    const embedStart = performance.now();
    const vector = await embedder.embedOne(queryText);
    const embedMs = performance.now() - embedStart;
    const response = await api.search({
      collection: activeCollection,
      queryText,
      queryEmbedding: vectorToBase64(vector),
      nResults: Number(searchNResults.value) || 5,
    });
    session.lastQuery = queryText;
    saveSession(session);
    searchStatus.textContent = `返回 ${response.results.length} 条结果 · 后端 ${embedder.info.label}`;
    searchTiming.textContent = `查询向量化 ${embedMs.toFixed(1)} ms · seekdb 混合检索 ${
      response.timing.seekdbMs
    } ms · 端到端 ${(embedMs + response.timing.totalMs).toFixed(1)} ms · RRF 在库内执行 (k=${
      response.hybrid.rrf.rankConstant
    }, analyzer=${response.hybrid.analyzer})`;
    renderResults(response.results);
    await refreshHybridBadge();
  } catch (error) {
    searchStatus.textContent = `检索失败：${errorText(error)}`;
  } finally {
    searchBtn.disabled = false;
  }
}

function renderResults(results: SearchHit[]): void {
  searchResults.innerHTML = "";
  if (results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "result";
    empty.textContent = "没有命中结果。";
    searchResults.append(empty);
    return;
  }
  results.forEach((hit, index) => {
    const card = document.createElement("article");
    card.className = "result";
    const head = document.createElement("div");
    head.className = "result-head";

    const left = document.createElement("span");
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = `#${index + 1}`;
    left.append(rank, document.createTextNode(`  ${hit.id}`));

    const right = document.createElement("span");
    right.textContent = hit.score === null ? "score —" : `score ${hit.score}`;
    head.append(left, right);
    card.append(head);

    const text = document.createElement("p");
    text.textContent = hit.text;
    card.append(text);

    const meta = document.createElement("div");
    meta.className = "tags";
    const title = hit.metadata?.title ?? hit.metadata?.source;
    if (title) meta.append(tag(String(title)));
    const tags = hit.metadata?.tags;
    if (typeof tags === "string" && tags.length > 0) {
      tags.split(",").filter(Boolean).forEach((value) => meta.append(tag(value)));
    }
    if (meta.childElementCount > 0) card.append(meta);
    searchResults.append(card);
  });
}

function tag(value: string): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = "tag";
  span.textContent = value;
  return span;
}

async function runBench(): Promise<void> {
  if (!embedder) {
    benchStatus.textContent = "模型尚未就绪";
    return;
  }
  benchRunBtn.disabled = true;
  benchNotes.textContent = "";
  benchStatus.textContent = "准备基准…";
  try {
    const result = await runBenchmark(embedder, (message) => {
      benchStatus.textContent = message;
    });
    benchStatus.textContent = "完成";
    renderBenchmark(result.payload);
    benchNotes.textContent = [
      ...result.notes,
      `原始结果已保存：${result.savedPath}`,
    ].join("\n");
  } catch (error) {
    benchStatus.textContent = "失败";
    benchNotes.textContent = errorText(error);
  } finally {
    benchRunBtn.disabled = false;
  }
}

async function showStoredBenchmark(): Promise<void> {
  if (benchQuality.childElementCount > 0) return;
  try {
    const stored = await api.benchResults();
    if (stored.payload) renderBenchmark(stored.payload);
    else benchStatus.textContent = "尚未运行基准";
  } catch {
    benchStatus.textContent = "读取历史基准失败";
  }
}

function renderBenchmark(payload: BenchmarkPayload): void {
  const samples = new Map(payload.samples.map((sample) => [sample.label, sample]));
  const table = document.createElement("table");
  const header = document.createElement("tr");
  [
    "精度/后端",
    "模型体积",
    "压缩比",
    "Recall@5",
    "Recall@10",
    "nDCG@5",
    "nDCG@10",
    "热态吞吐",
    "检索中位数",
  ].forEach((title) => {
    const th = document.createElement("th");
    th.textContent = title;
    header.append(th);
  });
  table.append(header);

  payload.quality.forEach((quality) => {
    const row = document.createElement("tr");
    const sample =
      [...samples.values()].find(
        (item) =>
          item.label.startsWith(quality.precision.toUpperCase()) ||
          item.backend.endsWith(quality.precision)
      ) ?? null;
    const cells = [
      `${quality.precision.toUpperCase()} / ${quality.backend}`,
      formatBytes(quality.modelBytes),
      quality.compressionRatio > 0 ? `${quality.compressionRatio.toFixed(2)}x` : "—",
      quality.recallAt5.toFixed(3),
      quality.recallAt10.toFixed(3),
      quality.ndcgAt5.toFixed(3),
      quality.ndcgAt10.toFixed(3),
      sample ? `${sample.warm.docsPerSecond.toFixed(1)} docs/s` : "—",
      sample ? `${sample.searchMedianMs.toFixed(1)} ms` : "—",
    ];
    cells.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      row.append(td);
    });
    table.append(row);
  });

  const extra = document.createElement("p");
  extra.className = "meta";
  extra.textContent = `设备：${payload.device.backend} · 查询向量化中位数 + 检索 = 端到端 ${payload.search.endToEndMedianMs} ms（p95 ${payload.search.endToEndP95Ms} ms）· 语料 ${payload.corpus.docs} 篇 / ${payload.corpus.queries} 查询`;

  benchQuality.innerHTML = "";
  benchQuality.append(table, extra);
  benchJson.textContent = JSON.stringify(payload, null, 2);
}

async function loadManifestSummary(): Promise<void> {
  try {
    const response = await fetch("/models/Xenova/bge-small-zh-v1.5/model-manifest.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = (await response.json()) as {
      variants: Record<string, { bytes: number; compressionRatio?: number } | null>;
      generatedAt: string;
    };
    const table = document.createElement("table");
    const header = document.createElement("tr");
    ["精度", "模型体积", "相对 FP32 压缩比"].forEach((title) => {
      const th = document.createElement("th");
      th.textContent = title;
      header.append(th);
    });
    table.append(header);
    for (const [name, variant] of Object.entries(manifest.variants)) {
      const row = document.createElement("tr");
      [name.toUpperCase(), variant ? formatBytes(variant.bytes) : "缺失", variant?.compressionRatio ? `${variant.compressionRatio.toFixed(2)}x` : "—"].forEach(
        (value) => {
          const td = document.createElement("td");
          td.textContent = value;
          row.append(td);
        }
      );
      table.append(row);
    }
    modelSummary.innerHTML = "";
    modelSummary.append(table);
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent =
      "INT8 (q8) 与 FP16 随仓库分发；FP32 基线体积用于计算压缩比。" +
      (manifest.variants.fp32 ? "" : " 运行 npm run fetch-models:fp32 后重新生成清单可获得 FP32 基线。");
    modelSummary.append(note);
  } catch (error) {
    modelSummary.textContent = `读取模型清单失败：${errorText(error)}。请先运行 npm run fetch-models。`;
  }
}

function renderBackendBadge(): void {
  if (!embedder) return;
  const info = embedder.info;
  setBadge(
    backendBadge,
    `${info.label}${info.gpuAdapter ? ` · ${info.gpuAdapter}` : ""}`,
    info.backend === "webgpu" ? "ok" : "warn"
  );
  backendBadge.title = info.reason ?? "浏览器本地推理";
  updateRuntimeDetails();
}

function renderSeekdbBadge(): void {
  if (!health) return;
  setBadge(
    seekdbBadge,
    `seekdb ${health.seekdb.version} · ${health.seekdb.platform}`,
    "ok"
  );
  seekdbBadge.title = `嵌入式数据库 ${health.seekdb.database}`;
}

function updateRuntimeDetails(): void {
  const parts = [
    `模型：${embedder?.modelId ?? "-"}`,
    `后端：${embedder?.info.label ?? "加载中"}`,
  ];
  if (embedder?.info.gpuAdapter) parts.push(`GPU：${embedder.info.gpuAdapter}`);
  if (embedder?.info.reason) parts.push(`降级原因：${embedder.info.reason}`);
  parts.push(`跨源隔离：${crossOriginIsolated ? "已启用" : "未启用（WASM 单线程）"}`);
  runtimeDetails.textContent = parts.join(" · ");
}

async function refreshHybridBadge(): Promise<void> {
  try {
    const debug = await api.lastHybrid();
    seekdbBadge.title = `本进程 hybridSearch 调用次数：${debug.callCount}`;
  } catch {
    // diagnostic only
  }
}

function renderCollections(): void {
  collectionSelect.innerHTML = "";
  if (collections.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "尚无集合（导入时自动创建）";
    collectionSelect.append(option);
  } else {
    for (const item of collections) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = `${item.name} (${item.count})`;
      collectionSelect.append(option);
    }
  }
  const preferred =
    (activeCollection && collections.some((item) => item.name === activeCollection)
      ? activeCollection
      : null) ??
    (session.activeCollection &&
    collections.some((item) => item.name === session.activeCollection)
      ? session.activeCollection
      : null) ??
    collections[0]?.name ??
    null;
  activeCollection = preferred;
  collectionSelect.value = preferred ?? "";
  session.activeCollection = preferred;
  saveSession(session);
  void loadCollectionState();
}

async function reloadCollections(): Promise<void> {
  const response = await api.health();
  health = response;
  collections = response.collections;
  renderCollections();
}

async function loadCollectionState(): Promise<void> {
  if (!activeCollection) {
    collectionMeta.textContent = "尚未选择集合";
    lastRefreshAt = null;
    docCount = 0;
    updateSearchAvailability();
    return;
  }
  try {
    const state = await api.collectionState(activeCollection);
    docCount = state.count;
    lastRefreshAt = state.lastRefreshAt;
    session.importedDocs[activeCollection] = state.count;
    session.lastRefreshAt[activeCollection] = state.lastRefreshAt;
    saveSession(session);
    collectionMeta.textContent = `${state.count} 条文档 · 分析器 ${state.analyzer} · 最近刷新 ${formatTime(
      state.lastRefreshAt
    )}`;
  } catch (error) {
    collectionMeta.textContent = `读取集合状态失败：${errorText(error)}`;
  }
  updateSearchAvailability();
}

async function resolveCollection(): Promise<string> {
  const typed = newCollectionInput.value.trim();
  const name = typed || activeCollection || "kb";
  if (!NAME_RE.test(name)) {
    throw new Error("集合名不合法：需以字母/数字开头，仅含字母、数字、-_. ");
  }
  if (!collections.some((item) => item.name === name)) {
    await api.createCollection(name);
    await reloadCollections();
  }
  activeCollection = name;
  session.activeCollection = name;
  saveSession(session);
  collectionSelect.value = name;
  return name;
}

function updateSearchAvailability(): void {
  const ready = Boolean(embedder) && Boolean(activeCollection) && docCount > 0 && Boolean(lastRefreshAt);
  searchBtn.disabled = !ready;
  if (!embedder) {
    searchStatus.textContent = "模型加载中…";
  } else if (!activeCollection || docCount === 0) {
    searchStatus.textContent = "请先导入文档。";
  } else if (!lastRefreshAt) {
    searchStatus.textContent = "索引尚未刷新，请点击「刷新索引」。";
  } else if (searchStatus.textContent.includes("请先") || searchStatus.textContent.includes("尚未") || searchStatus.textContent.includes("模型加载中")) {
    searchStatus.textContent = "等待查询";
  }
}

function setImportEnabled(enabled: boolean): void {
  [importTextBtn, importSampleBtn, createCollectionBtn, refreshIndexBtn, deleteCollectionBtn].forEach(
    (button) => {
      button.disabled = !enabled || busy;
    }
  );
}

async function withBusy(task: () => Promise<void>, label: string): Promise<void> {
  if (busy) return;
  busy = true;
  setImportEnabled(Boolean(embedder));
  try {
    await task();
  } catch (error) {
    setImportMessage(`${label}：${errorText(error)}`, true);
  } finally {
    busy = false;
    setImportEnabled(Boolean(embedder));
  }
}

function setProgress(ratio: number, message: string): void {
  importProgressBar.style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  importStatus.textContent = message;
}

function setImportMessage(message: string, isError = false): void {
  importProgress.classList.remove("hidden");
  importStatus.textContent = message;
  importStatus.classList.toggle("err", isError);
}

function renderStats(entries: Array<[string, string]>): void {
  importStats.classList.remove("hidden");
  importStats.innerHTML = "";
  for (const [label, value] of entries) {
    const box = document.createElement("div");
    box.className = "stat";
    const strong = document.createElement("b");
    strong.textContent = value;
    const span = document.createElement("span");
    span.textContent = label;
    box.append(strong, span);
    importStats.append(box);
  }
}

function setBadge(element: HTMLElement, text: string, kind: string): void {
  element.textContent = text;
  element.className = `badge ${kind}`;
}

function persistSession(): void {
  session.activeCollection = activeCollection;
  saveSession(session);
}

function formatTime(iso: string | null): string {
  if (!iso) return "从未";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element #${id}`);
  return node as T;
}
