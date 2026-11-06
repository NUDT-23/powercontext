import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(rootDir, "web", "public", "ort");
const sources = [
  path.join(rootDir, "node_modules", "onnxruntime-web", "dist"),
  path.join(rootDir, "node_modules", "@huggingface", "transformers", "dist"),
];

fs.mkdirSync(outDir, { recursive: true });
const copied = new Map();

for (const sourceDir of sources) {
  if (!fs.existsSync(sourceDir)) continue;
  for (const name of fs.readdirSync(sourceDir)) {
    if (!/^ort-wasm.*\.(wasm|mjs)$/.test(name)) continue;
    if (copied.has(name)) continue;
    const from = path.join(sourceDir, name);
    const to = path.join(outDir, name);
    fs.copyFileSync(from, to);
    copied.set(name, fs.statSync(to).size);
  }
}

if (![...copied.keys()].some((name) => name.endsWith(".wasm"))) {
  console.error("[prepare-ort] no wasm binaries found; run npm install first");
  process.exit(1);
}

fs.writeFileSync(
  path.join(outDir, "manifest.json"),
  `${JSON.stringify({ generatedAt: new Date().toISOString(), files: Object.fromEntries(copied) }, null, 2)}\n`
);

for (const [name, bytes] of copied) {
  console.log(`[prepare-ort] ${name} ${(bytes / 1024 / 1024).toFixed(2)} MiB`);
}
