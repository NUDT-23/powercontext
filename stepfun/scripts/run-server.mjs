import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const build = spawnSync(process.execPath, [path.join(rootDir, "scripts", "build-server.mjs")], {
  stdio: "inherit",
  cwd: rootDir,
});
if (build.status !== 0) process.exit(build.status ?? 1);

const result = spawnSync(
  process.execPath,
  [path.join(rootDir, "scripts", "run-with-seekdb.mjs"), "dist-server/index.js"],
  {
    stdio: "inherit",
    cwd: rootDir,
    env: {
      ...process.env,
      STEPFUN_PUBLISH_PORT: process.env.PORT || "8787",
    },
  }
);
process.exit(result.status ?? 1);
