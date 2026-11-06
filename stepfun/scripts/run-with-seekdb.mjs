import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let args = process.argv.slice(2);
let forceDocker = false;
let forceNative = false;
if (args[0] === "--docker") {
  forceDocker = true;
  args = args.slice(1);
}
if (args[0] === "--native") {
  forceNative = true;
  args = args.slice(1);
}
if (args.length === 0) {
  console.error("usage: node scripts/run-with-seekdb.mjs [--docker|--native] <script> [...args]");
  process.exit(2);
}

const useDocker = process.platform === "win32" ? !forceNative : forceDocker;

if (!useDocker) {
  const result = spawnSync(process.execPath, args, {
    stdio: "inherit",
    cwd: rootDir,
    env: process.env,
  });
  process.exit(result.status ?? 1);
}

const image = "stepfun-seekdb:local";
const cacheDir = path.join(rootDir, "data", "bindings-linux");
const dataVolume = process.env.STEPFUN_DATA_VOLUME || "stepfun-seekdb-data";
fs.mkdirSync(cacheDir, { recursive: true });

const inspect = spawnSync("docker", ["image", "inspect", image], {
  stdio: "ignore",
});
if (inspect.status !== 0) {
  console.log(`[seekdb-docker] building ${image} (first run only)`);
  const built = spawnSync(
    "docker",
    [
      "build",
      "-t",
      image,
      "-f",
      path.join(rootDir, "scripts", "seekdb-runner.Dockerfile"),
      path.join(rootDir, "scripts"),
    ],
    { stdio: "inherit", cwd: rootDir }
  );
  if (built.status !== 0) {
    console.error("[seekdb-docker] image build failed");
    process.exit(built.status ?? 1);
  }
}

const publishPort = process.env.STEPFUN_PUBLISH_PORT;
const containerName = process.env.STEPFUN_CONTAINER_NAME;
const dockerArgs = [
  "run",
  "--rm",
  "-i",
  ...(containerName ? ["--name", containerName] : []),
  // seekdb's HNSW builder needs thread creation that the default Docker seccomp
  // profile rejects; paired with the 64 MiB stack limit set below it starts fine.
  "--security-opt",
  "seccomp=unconfined",
  "-v",
  `${rootDir}:/app`,
  "-v",
  `${cacheDir}:/tmp/seekdb-bindings`,
  "-v",
  `${dataVolume}:/data`,
  "-w",
  "/app",
  "-e",
  "SEEKDB_BINDINGS_CACHE_DIR=/tmp/seekdb-bindings",
  "-e",
  "STEPFUN_ROOT=/app",
];
if (publishPort) {
  dockerArgs.push("-p", `${publishPort}:${publishPort}`);
  dockerArgs.push("-e", `PORT=${publishPort}`);
  dockerArgs.push("-e", "HOST=0.0.0.0");
}
dockerArgs.push(
  "-e",
  `STEPFUN_DB_PATH=${process.env.STEPFUN_DB_PATH || "/data/seekdb"}`,
  "-e",
  `STEPFUN_STATE_PATH=${process.env.STEPFUN_STATE_PATH || "/data/state.json"}`,
  "-e",
  `STEPFUN_DB_NAME=${process.env.STEPFUN_DB_NAME || "test"}`,
  "-e",
  `STEPFUN_SMOKE_DB=${process.env.STEPFUN_SMOKE_DB || "/data/smoke-seekdb"}`,
  "-e",
  `STEPFUN_TEST_DB=${process.env.STEPFUN_TEST_DB || "/data/hybrid-test"}`
);
dockerArgs.push(image, "bash", "-lc", buildCommand(args));

const result = spawnSync("docker", dockerArgs, {
  stdio: "inherit",
  cwd: rootDir,
  env: process.env,
});
process.exit(result.status ?? 1);

function buildCommand(argv) {
  const quoted = argv.map(shellQuote).join(" ");
  return [
    `ulimit -s 65536 || true`,
    `node -e "require('/app/node_modules/@seekdb/js-bindings/download.js').ensureBindingsDownloaded().then((p)=>console.log('[bindings]',p)).catch((e)=>{console.error(e);process.exit(1)})"`,
    `export LD_PRELOAD=$(find /tmp/seekdb-bindings -name libseekdb.so | head -n 1)`,
    `echo "[seekdb-docker] LD_PRELOAD=$LD_PRELOAD"`,
    `exec node ${quoted}`,
  ].join(" && ");
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}
