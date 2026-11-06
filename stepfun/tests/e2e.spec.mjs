import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const base = (process.env.BASE_URL || "http://127.0.0.1:8787").replace(/\/$/, "");
const baseHost = new URL(base).hostname;
const edge =
  process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const collection = process.env.STEPFUN_E2E_COLLECTION || `e2e_${Date.now()}`;

const evidence = {
  startedAt: new Date().toISOString(),
  base,
  collection,
  checks: [],
  ok: false,
};

const shotDir = path.resolve("artifacts/screenshots");
fs.mkdirSync(shotDir, { recursive: true });
fs.mkdirSync(path.resolve("artifacts/evidence"), { recursive: true });

function record(name, ok, detail = {}) {
  evidence.checks.push({ name, ok, ...detail });
  console.log(`[${ok ? "ok" : "FAIL"}] ${name}${detail.error ? `: ${detail.error}` : ""}`);
  if (!ok) throw new Error(`${name} failed${detail.error ? `: ${detail.error}` : ""}`);
}

async function check(name, fn) {
  const started = Date.now();
  try {
    const value = await fn();
    record(name, true, { ms: Date.now() - started, value });
    return value;
  } catch (error) {
    record(name, false, {
      ms: Date.now() - started,
      error: String(error?.stack || error),
    });
  }
}

function browserArgs() {
  return ["--enable-unsafe-swiftshader"];
}

async function waitForModel(page) {
  await page.waitForFunction(
    () => /· (FP16|INT8)/.test(document.querySelector("#backend-badge")?.textContent || ""),
    null,
    { timeout: 180000 }
  );
}

async function importText(page, text, expectStatus) {
  await page.fill("#import-text", text);
  await page.click("#import-text-btn");
  await page.waitForFunction(
    (expected) =>
      (document.querySelector("#import-status")?.textContent || "").includes(expected),
    expectStatus,
    { timeout: 180000 }
  );
  return page.textContent("#import-status");
}

async function apiJson(page, url) {
  return page.evaluate(async (target) => {
    const response = await fetch(target);
    if (!response.ok) throw new Error(`${target}: HTTP ${response.status}`);
    return response.json();
  }, url);
}

async function clickSearch(page, query) {
  await page.fill("#search-input", query);
  const [response] = await Promise.all([
    page.waitForResponse(
      (item) => item.url().endsWith("/api/search") && item.request().method() === "POST",
      { timeout: 60000 }
    ),
    page.click("#search-btn"),
  ]);
  if (response.status() !== 200) throw new Error(`search HTTP ${response.status()}`);
  const body = await response.json();
  await page.waitForFunction(
    () => /返回 \d+ 条结果/.test(document.querySelector("#search-status")?.textContent || ""),
    null,
    { timeout: 30000 }
  );
  return body;
}

let browser;
try {
  browser = await chromium.launch({
    executablePath: edge,
    headless: true,
    args: browserArgs(),
  });

  const context = await browser.newContext();
  const page = await context.newPage();
  const network = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith("http://") || url.startsWith("https://")) {
      network.push(url);
    }
  });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") pageErrors.push(message.text());
  });

  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await waitForModel(page);
  const backendLabel = (await page.textContent("#backend-badge")) || "";
  evidence.backend = backendLabel;

  await check("健康检查：seekdb 嵌入式服务可用", async () => {
    const health = await apiJson(page, "/api/health");
    if (!health.ok) throw new Error("health.ok is false");
    if (health.embedding?.location !== "browser") {
      throw new Error("server advertises server-side embedding");
    }
    return { seekdb: health.seekdb, collections: health.collections.length };
  });

  await check("集合创建", async () => {
    await page.click('[data-tab="library"]');
    await page.fill("#new-collection-input", collection);
    await page.click("#create-collection-btn");
    await page.waitForFunction(
      (name) =>
        [...document.querySelectorAll("#collection-select option")].some(
          (option) => option.value === name
        ),
      collection,
      { timeout: 60000 }
    );
    return collection;
  });

  const passage =
    "端侧混合检索验收文档。seekdb 在同一个数据库进程内完成向量检索与全文检索。" +
    "RRF 倒数排名融合根据两路结果的排名计算分数，浏览器只发送一次检索请求。" +
    "本段包含唯一标记：星海校验码 A7。" +
    "量化模型在浏览器本地完成推理，不经过任何云端 API。";

  await check("完整流程：本地向量化 → 入库 → 混合检索", async () => {
    const status = await importText(page, passage, "导入完成");
    const stats = await page.textContent("#import-stats");
    await page.click('[data-tab="search"]');
    await page.waitForFunction(
      () => !document.querySelector("#search-btn")?.disabled,
      null,
      { timeout: 60000 }
    );
    const response = await clickSearch(page, "星海校验码 A7");
    if (response.hybrid?.executedInDb !== true) {
      throw new Error("search response does not report in-db execution");
    }
    const count = await page.locator("#search-results .result").count();
    if (count === 0) throw new Error("search returned no result cards");
    const timing = await page.textContent("#search-timing");
    if (!timing.includes("RRF")) throw new Error("timing does not mention RRF");
    const text = await page.textContent("#search-results");
    if (!text.includes("星海校验码")) throw new Error("top results do not contain the query marker");
    await page.screenshot({ path: path.join(shotDir, "e2e-search.png"), fullPage: true });
    return { status, count, timing, stats };
  });

  await check("seekdb 数据层：单次 hybridSearch + 库内 RRF", async () => {
    const before = await apiJson(page, "/api/debug/hybrid");
    await clickSearch(page, "向量检索与全文检索如何融合");
    const after = await apiJson(page, "/api/debug/hybrid");
    if (after.callCount !== before.callCount + 1) {
      throw new Error(`hybridSearch call delta = ${after.callCount - before.callCount}`);
    }
    const state = await apiJson(page, `/api/collections/${collection}/state`);
    if (state.count === 0 || !state.lastRefreshAt) {
      throw new Error("collection state missing count/lastRefreshAt");
    }
    return {
      callDelta: after.callCount - before.callCount,
      lastCall: after.last,
      count: state.count,
      analyzer: state.analyzer,
    };
  });

  await check("增量导入：重复内容跳过、新内容可检索", async () => {
    const before = await apiJson(page, `/api/collections/${collection}/state`);
    await page.click('[data-tab="library"]');
    const skippedStatus = await importText(page, passage, "导入完成");
    if (!/跳过 [1-9]/.test(skippedStatus)) {
      throw new Error(`re-import did not skip: ${skippedStatus}`);
    }
    const fresh =
      "量子纠缠实验记录：本轮新增文本使用独立哈希，刷新索引后可被混合检索命中。" +
      "唯一标记：深空信标 B9。";
    const inserted = await importText(page, fresh, "导入完成");
    if (!/新增 [1-9]/.test(inserted)) throw new Error(`insert did not add: ${inserted}`);
    const after = await apiJson(page, `/api/collections/${collection}/state`);
    if (after.count <= before.count) throw new Error("count did not grow");
    if (!after.lastRefreshAt) throw new Error("refresh timestamp missing");
    await page.click('[data-tab="search"]');
    await clickSearch(page, "深空信标 B9");
    const results = await page.textContent("#search-results");
    if (!results.includes("深空信标")) throw new Error("incremental document not retrievable");
    return { before: before.count, after: after.count, skippedStatus, inserted };
  });

  await check("量化模型：本地文件 + 体积 + 压缩比", async () => {
    const manifest = await page.evaluate(async () => {
      const response = await fetch("/models/Xenova/bge-small-zh-v1.5/model-manifest.json");
      return response.json();
    });
    const variants = manifest.variants ?? {};
    for (const name of ["fp16", "int8"]) {
      if (!variants[name]?.bytes) throw new Error(`manifest missing ${name}`);
      const head = await page.evaluate(async (file) => {
        const response = await fetch(`/models/Xenova/bge-small-zh-v1.5/onnx/${file}`, {
          method: "HEAD",
        });
        return {
          status: response.status,
          length: Number(response.headers.get("content-length") || 0),
        };
      }, name === "fp16" ? "model_fp16.onnx" : "model_quantized.onnx");
      if (head.status !== 200) throw new Error(`${name} not served locally`);
      if (head.length && head.length !== variants[name].bytes) {
        throw new Error(`${name} size mismatch`);
      }
    }
    const fp32 = variants.fp32;
    if (fp32?.bytes) {
      const ratio = fp32.bytes / variants.int8.bytes;
      if (!(ratio > 3.5 && ratio < 4.2)) throw new Error(`unexpected int8 ratio ${ratio}`);
      const fp16Ratio = fp32.bytes / variants.fp16.bytes;
      if (!(fp16Ratio > 1.8 && fp16Ratio < 2.2)) {
        throw new Error(`unexpected fp16 ratio ${fp16Ratio}`);
      }
    }
    return {
      fp32Bytes: fp32?.bytes ?? null,
      fp16Bytes: variants.fp16.bytes,
      int8Bytes: variants.int8.bytes,
      fp16Ratio: variants.fp16.compressionRatio ?? null,
      int8Ratio: variants.int8.compressionRatio ?? null,
    };
  });

  await check("本地推理：除本机 API/静态资源外无外部请求", async () => {
    const external = network.filter((url) => {
      const { hostname } = new URL(url);
      return hostname !== baseHost && hostname !== "localhost" && hostname !== "127.0.0.1";
    });
    if (external.length > 0) throw new Error(`external requests: ${external.slice(0, 5)}`);
    const modelRequests = network.filter((url) => url.includes("/models/")).length;
    const ortRequests = network.filter((url) => url.includes("/ort/")).length;
    if (modelRequests === 0) throw new Error("no local model requests observed");
    if (ortRequests === 0) throw new Error("no local ort requests observed");
    return { total: network.length, modelRequests, ortRequests };
  });

  await check("会话状态：刷新页面后保留集合与模型后端", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForModel(page);
    await page.waitForFunction(
      (name) => document.querySelector("#collection-select")?.value === name,
      collection,
      { timeout: 60000 }
    );
    const stored = await page.evaluate(() => localStorage.getItem("stepfun-kb-session-v1"));
    if (!stored) throw new Error("session not persisted");
    return { collection, stored: stored.slice(0, 120) };
  });

  await check("降级路径：forceWasm 时使用 WASM · INT8 且仍可检索", async () => {
    const wasmContext = await browser.newContext();
    const wasmPage = await wasmContext.newPage();
    await wasmPage.goto(`${base}/?forceWasm=1`, { waitUntil: "domcontentloaded" });
    await waitForModel(wasmPage);
    const label = (await wasmPage.textContent("#backend-badge")) || "";
    if (!label.includes("WASM · INT8")) throw new Error(`unexpected badge: ${label}`);
    const reason = await wasmPage.getAttribute("#backend-badge", "title");
    if (!reason || !reason.includes("forceWasm")) {
      throw new Error(`fallback reason missing: ${reason}`);
    }
    await wasmPage.waitForFunction(
      (name) => {
        const select = document.querySelector("#collection-select");
        return select && [...select.options].some((option) => option.value === name);
      },
      collection,
      { timeout: 60000 }
    );
    await wasmPage.selectOption("#collection-select", collection);
    await wasmPage.click('[data-tab="search"]');
    await wasmPage.waitForFunction(
      () => !document.querySelector("#search-btn")?.disabled,
      null,
      { timeout: 60000 }
    );
    await clickSearch(wasmPage, "星海校验码 A7");
    const hits = await wasmPage.locator("#search-results .result").count();
    if (hits === 0) throw new Error("WASM fallback returned no results");
    await wasmPage.screenshot({ path: path.join(shotDir, "e2e-wasm.png"), fullPage: true });
    await wasmContext.close();
    return { label, reason, hits };
  });

  await check("自动降级：navigator.gpu 缺失时仍使用 WASM · INT8", async () => {
    const autoContext = await browser.newContext();
    await autoContext.addInitScript(() => {
      Object.defineProperty(navigator, "gpu", {
        configurable: true,
        get: () => undefined,
      });
    });
    const autoPage = await autoContext.newPage();
    await autoPage.goto(`${base}/`, { waitUntil: "domcontentloaded" });
    await waitForModel(autoPage);
    const label = (await autoPage.textContent("#backend-badge")) || "";
    if (!label.includes("WASM · INT8")) throw new Error(`unexpected badge: ${label}`);
    const reason = await autoPage.getAttribute("#backend-badge", "title");
    if (!reason || !reason.includes("navigator.gpu")) {
      throw new Error(`automatic fallback reason missing: ${reason}`);
    }
    await autoPage.waitForFunction(
      (name) => {
        const select = document.querySelector("#collection-select");
        return select && [...select.options].some((option) => option.value === name);
      },
      collection,
      { timeout: 60000 }
    );
    await autoPage.selectOption("#collection-select", collection);
    await autoPage.click('[data-tab="search"]');
    await autoPage.waitForFunction(
      () => !document.querySelector("#search-btn")?.disabled,
      null,
      { timeout: 60000 }
    );
    await clickSearch(autoPage, "星海校验码 A7");
    const hits = await autoPage.locator("#search-results .result").count();
    if (hits === 0) throw new Error("automatic WASM fallback returned no results");
    await autoContext.close();
    return { label, reason, hits };
  });

  await check("页面运行时无 JS 错误", async () => {
    const relevant = pageErrors.filter(
      (text) =>
        !/favicon|Failed to load resource/i.test(text) &&
        !/onnxruntime|VerifyEachNodeIsAssignedToAnEp|session_state\.cc/i.test(text)
    );
    if (relevant.length > 0) throw new Error(relevant.slice(0, 3).join(" | "));
    return { errors: pageErrors.length };
  });

  await context.close();
  evidence.ok = evidence.checks.every((item) => item.ok);
  console.log("E2E PASS");
} catch (error) {
  evidence.error = String(error?.stack || error);
  console.error("E2E FAIL:", error?.message || error);
} finally {
  try {
    await browser?.close();
  } catch {}
  evidence.finishedAt = new Date().toISOString();
  fs.writeFileSync(
    path.resolve("artifacts/evidence/e2e.json"),
    `${JSON.stringify(evidence, null, 2)}\n`
  );
  setTimeout(() => process.exit(evidence.ok ? 0 : 1), 200);
}
