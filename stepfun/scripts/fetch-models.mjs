import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = process.env.STEPFUN_MODEL_REPO || "Xenova/bge-small-zh-v1.5";
const base = (process.env.HF_MIRROR || "https://hf-mirror.com").replace(/\/$/, "");
const withFp32 = process.argv.includes("--with-fp32");
const modelDir = path.join(rootDir, "web", "public", "models", ...repo.split("/"));

const files = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "vocab.txt",
  "onnx/model_fp16.onnx",
  "onnx/model_quantized.onnx",
];
if (withFp32) files.push("onnx/model.onnx");

fs.mkdirSync(path.join(modelDir, "onnx"), { recursive: true });

for (const file of files) {
  const target = path.join(modelDir, file);
  if (fs.existsSync(target) && fs.statSync(target).size > 0) {
    console.log(`[fetch-models] skip ${file} (${formatBytes(fs.statSync(target).size)})`);
    continue;
  }
  const url = `${base}/${repo}/resolve/main/${file}`;
  console.log(`[fetch-models] GET ${url}`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const part = `${target}.part`;
  if (!(await downloadWithCurl(url, part))) {
    const response = await fetch(url, { redirect: "follow" });
    if (!response.ok) {
      throw new Error(`download failed: HTTP ${response.status} ${url}`);
    }
    fs.writeFileSync(part, Buffer.from(await response.arrayBuffer()));
  }
  const bytes = fs.statSync(part).size;
  if (bytes === 0) throw new Error(`download produced an empty file: ${url}`);
  fs.renameSync(part, target);
  console.log(`[fetch-models] ${file} ${formatBytes(bytes)}`);
}

const onnxFiles = {};
for (const file of fs.readdirSync(path.join(modelDir, "onnx"))) {
  if (!file.endsWith(".onnx")) continue;
  const full = path.join(modelDir, "onnx", file);
  const bytes = fs.statSync(full).size;
  const sha256 = createHash("sha256").update(fs.readFileSync(full)).digest("hex");
  onnxFiles[file] = { bytes, sha256 };
}

const fp32 = onnxFiles["model.onnx"]?.bytes ?? null;
const summarize = (name, bytes) => ({
  bytes,
  ...(fp32 ? { compressionRatio: Number((fp32 / bytes).toFixed(2)) } : {}),
  sha256: onnxFiles[name]?.sha256 ?? null,
});

const manifest = {
  repo,
  generatedAt: new Date().toISOString(),
  dimension: 512,
  pooling: "cls",
  normalize: true,
  files: onnxFiles,
  variants: {
    fp32: fp32 ? summarize("model.onnx", fp32) : null,
    fp16: summarize("model_fp16.onnx", onnxFiles["model_fp16.onnx"]?.bytes ?? 0),
    int8: summarize(
      "model_quantized.onnx",
      onnxFiles["model_quantized.onnx"]?.bytes ?? 0
    ),
  },
};
fs.writeFileSync(
  path.join(modelDir, "model-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`
);
console.log(JSON.stringify(manifest.variants, null, 2));
if (!fp32) {
  console.log(
    "[fetch-models] fp32 baseline absent; run `npm run fetch-models:fp32` for exact compression ratios"
  );
}

function formatBytes(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
}

async function downloadWithCurl(url, part) {
  const probe = spawnSync("curl", ["--version"], { stdio: "ignore" });
  if (probe.status !== 0) return false;
  const result = spawnSync(
    "curl",
    [
      "-sL",
      "--retry",
      "5",
      "--retry-delay",
      "2",
      "--connect-timeout",
      "20",
      "--max-time",
      "1800",
      "-o",
      part,
      url,
    ],
    { stdio: "inherit" }
  );
  return result.status === 0 && fs.existsSync(part);
}
