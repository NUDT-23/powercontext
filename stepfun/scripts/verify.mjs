import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.STEPFUN_VERIFY_PORT || 8799);
const runId = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
const skipE2E = process.env.STEPFUN_SKIP_E2E === "1";
const evidence = {
  startedAt: new Date().toISOString(),
  runId,
  rootDir,
  port,
  steps: [],
  notes: [],
  ok: false,
};
let failed = false;

const evidenceDir = path.join(rootDir, "artifacts", "evidence");
fs.mkdirSync(evidenceDir, { recursive: true });
fs.mkdirSync(path.join(rootDir, "artifacts", "screenshots"), { recursive: true });

const edgePath = detectEdge();
const containerName = `stepfun-verify-${runId}`;

let server = null;
let serverLog = "";

main()
  .catch((error) => {
    evidence.error = String(error?.stack || error);
    console.error("VERIFY FAIL:", error?.message || error);
  })
  .finally(async () => {
    await stopServer();
    evidence.finishedAt = new Date().toISOString();
    evidence.ok = !failed && evidence.steps.every((item) => item.ok);
    fs.writeFileSync(
      path.join(evidenceDir, "verify.json"),
      `${JSON.stringify(evidence, null, 2)}\n`
    );
    printSummary();
    setTimeout(() => process.exit(evidence.ok ? 0 : 1), 300);
  });

async function main() {
  if (skipE2E) evidence.notes.push("STEPFUN_SKIP_E2E=1：跳过浏览器端到端验收");
  if (await isPortBusy()) {
    throw new Error(
      `port ${port} is already serving; set STEPFUN_VERIFY_PORT to a free port`
    );
  }

  await step("环境检查", async () => {
    const major = Number(process.versions.node.split(".")[0]);
    if (major < 20) throw new Error(`Node ${process.versions.node} < 20`);
    if (!fs.existsSync(path.join(rootDir, "node_modules", "@seekdb", "js-bindings"))) {
      throw new Error("缺少 @seekdb/js-bindings，请先运行 npm install");
    }
    const docker = process.platform === "win32" ? dockerVersion() : null;
    if (process.platform === "win32" && !docker) {
      throw new Error("Windows 需要可用的 Docker（seekdb 嵌入式绑定按 Linux 运行）");
    }
    return {
      node: process.version,
      platform: `${process.platform}-${process.arch}`,
      docker,
      edge: edgePath ?? "未找到（E2E 将跳过）",
    };
  });

  await step("模型与 ORT 静态资源检查", async () => {
    const modelDir = path.join(
      rootDir,
      "web",
      "public",
      "models",
      "Xenova",
      "bge-small-zh-v1.5"
    );
    const manifestPath = path.join(modelDir, "model-manifest.json");
    if (!fs.existsSync(manifestPath)) {
      throw new Error("缺少 model-manifest.json，请运行 npm run fetch-models");
    }
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const files = {
      fp16: "onnx/model_fp16.onnx",
      int8: "onnx/model_quantized.onnx",
    };
    for (const [name, file] of Object.entries(files)) {
      const full = path.join(modelDir, file);
      if (!fs.existsSync(full)) throw new Error(`缺少 ${name} 模型：${file}`);
      const bytes = fs.statSync(full).size;
      const expected = manifest.variants?.[name]?.bytes;
      if (expected && expected !== bytes) {
        throw new Error(`${name} 模型体积不一致：${bytes} != ${expected}`);
      }
    }
    const fp32 = manifest.variants?.fp32;
    if (fp32?.bytes) {
      evidence.notes.push(
        `FP32 基线：${(fp32.bytes / 1024 / 1024).toFixed(2)} MiB；INT8 压缩比 ${manifest.variants.int8.compressionRatio}×，FP16 ${manifest.variants.fp16.compressionRatio}×`
      );
    } else {
      evidence.notes.push(
        "FP32 基线未下载（不入库）：运行 npm run fetch-models:fp32 可得到精确压缩比"
      );
    }
    const ortDir = path.join(rootDir, "web", "public", "ort");
    const ortFiles = fs.existsSync(ortDir) ? fs.readdirSync(ortDir) : [];
    if (!ortFiles.some((name) => name.endsWith(".wasm"))) {
      throw new Error("缺少 web/public/ort 下的 ORT wasm（npm run prepare:ort）");
    }
    return {
      int8Bytes: manifest.variants.int8.bytes,
      fp16Bytes: manifest.variants.fp16.bytes,
      fp32Bytes: fp32?.bytes ?? null,
      ortFiles: ortFiles.length,
    };
  });

  await step("单元测试（切分 + 指标）", () =>
    run("unit", process.execPath, ["--test", "tests/unit.test.mjs"])
  );

  await step("seekdb 冒烟测试（中文双路 + 库内 RRF）", () =>
    run("smoke", process.execPath, [
      "scripts/run-with-seekdb.mjs",
      "server/scripts/smoke-seekdb.mjs",
    ], {
      env: {
        STEPFUN_SMOKE_DB: `/data/verify-smoke-${runId}`,
      },
    })
  );

  await step("混合检索集成测试（单次 hybridSearch 与 HNSW 回归）", () =>
    run("hybrid", process.execPath, [
      "scripts/run-with-seekdb.mjs",
      "tests/hybrid.test.mjs",
    ], {
      env: {
        STEPFUN_TEST_DB: `/data/verify-hybrid-${runId}`,
      },
    })
  );

  await step("构建前端与服务端", async () => {
    run("prepare-ort", process.execPath, ["scripts/prepare-ort.mjs"]);
    run(
      "build-web",
      process.execPath,
      [path.join("node_modules", "vite", "bin", "vite.js"), "build"]
    );
    run("build-server", process.execPath, ["scripts/build-server.mjs"]);
  });

  await step("启动生产服务并等待健康检查", async () => {
    await startServer();
    return { url: `http://127.0.0.1:${port}` };
  });

  if (skipE2E) {
    record("浏览器端到端验收", true, { skipped: true });
  } else if (!edgePath) {
    failed = true;
    record("浏览器端到端验收", false, {
      error:
        "未找到 Microsoft Edge / Chromium；设置 EDGE_PATH 或 STEPFUN_SKIP_E2E=1",
    });
  } else {
    await step("浏览器端到端验收（完整流程 + 自动/强制降级）", () =>
      run(
        "e2e",
        process.execPath,
        ["tests/e2e.spec.mjs"],
        {
          env: {
            BASE_URL: `http://127.0.0.1:${port}`,
            EDGE_PATH: edgePath,
          },
        }
      )
    );
  }
}

async function step(name, fn) {
  const started = Date.now();
  try {
    const value = await fn();
    record(name, true, { ms: Date.now() - started, value });
    return value;
  } catch (error) {
    failed = true;
    record(name, false, {
      ms: Date.now() - started,
      error: String(error?.stack || error),
    });
    throw error;
  }
}

function record(name, ok, detail = {}) {
  evidence.steps.push({ name, ok, ...detail });
  console.log(`${ok ? "[ok]" : "[FAIL]"} ${name}`);
  if (!ok && detail.error) console.error(detail.error);
}

function run(label, command, args, options = {}) {
  const started = Date.now();
  const result = spawnSync(command, args, {
    cwd: rootDir,
    stdio: "inherit",
    env: { ...process.env, ...(options.env ?? {}) },
  });
  const ms = Date.now() - started;
  if (result.error) {
    throw new Error(`${label}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${label} exited with code ${result.status}`);
  }
  return { ms };
}

function dockerVersion() {
  const result = spawnSync("docker", ["version", "--format", "{{.Server.Version}}"], {
    stdio: "pipe",
    encoding: "utf8",
  });
  if (result.status !== 0) return null;
  return result.stdout.trim();
}

function detectEdge() {
  if (process.env.EDGE_PATH) {
    return fs.existsSync(process.env.EDGE_PATH) ? process.env.EDGE_PATH : null;
  }
  const candidates =
    process.platform === "win32"
      ? [
          "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
          "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        ]
      : [
          "/usr/bin/microsoft-edge",
          "/usr/bin/microsoft-edge-stable",
          "/usr/bin/google-chrome",
          "/usr/bin/chromium",
          "/usr/bin/chromium-browser",
        ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? null;
}

async function isPortBusy() {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
      signal: AbortSignal.timeout(1500),
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function startServer() {
  const env = {
    ...process.env,
    STEPFUN_DB_PATH: `/data/verify-${runId}`,
    STEPFUN_STATE_PATH: `/data/verify-state-${runId}.json`,
    STEPFUN_PUBLISH_PORT: String(port),
    PORT: String(port),
    HOST: "0.0.0.0",
    STEPFUN_CONTAINER_NAME: containerName,
  };
  serverLog = path.join(rootDir, "data", `verify-server-${runId}.log`);
  const stream = fs.createWriteStream(serverLog);
  server = spawn(
    process.execPath,
    ["scripts/run-with-seekdb.mjs", "dist-server/index.js"],
    { cwd: rootDir, env, stdio: ["ignore", "pipe", "pipe"] }
  );
  server.stdout.on("data", (chunk) => stream.write(chunk));
  server.stderr.on("data", (chunk) => stream.write(chunk));
  server.on("exit", (code) => {
    evidence.notes.push(`server process exited with code ${code}`);
  });

  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(2000),
      });
      if (response.ok) {
        const body = await response.json();
        if (!body.ok) throw new Error("health.ok is false");
        return body;
      }
    } catch {
      // keep waiting
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  const tail = fs.existsSync(serverLog)
    ? fs.readFileSync(serverLog, "utf8").slice(-2000)
    : "";
  throw new Error(`server did not become healthy on port ${port}\n${tail}`);
}

async function stopServer() {
  if (process.platform === "win32" || process.env.STEPFUN_USE_DOCKER === "1") {
    spawnSync("docker", ["rm", "-f", containerName], { stdio: "ignore" });
  }
  if (!server) return;
  try {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/pid", String(server.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      server.kill("SIGTERM");
    }
  } catch {
    // best-effort cleanup
  }
  server = null;
}

function printSummary() {
  const passed = evidence.steps.filter((item) => item.ok).length;
  console.log(`\n验证结果：${passed}/${evidence.steps.length} 项通过`);
  for (const note of evidence.notes) console.log(`- ${note}`);
  console.log(
    evidence.ok
      ? "VERIFY PASS · 证据写入 artifacts/evidence/verify.json"
      : "VERIFY FAIL · 详见 artifacts/evidence/verify.json"
  );
}
