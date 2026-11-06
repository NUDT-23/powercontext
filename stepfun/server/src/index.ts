import express from "express";
import fs from "node:fs";
import path from "node:path";
import { createRouter } from "./routes.js";
import { SeekdbStore } from "./seekdb.js";

const rootDir = process.env.STEPFUN_ROOT
  ? path.resolve(process.env.STEPFUN_ROOT)
  : process.cwd();
const port = Number(process.env.PORT || 8787);
const host = process.env.HOST || "0.0.0.0";

const store = new SeekdbStore({
  dbPath: process.env.STEPFUN_DB_PATH || path.join(rootDir, "data", "seekdb"),
  database: process.env.STEPFUN_DB_NAME || "test",
  statePath:
    process.env.STEPFUN_STATE_PATH ||
    path.join(rootDir, "data", "state.json"),
});

const app = express();
app.disable("x-powered-by");
app.use((_req, res, next) => {
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  next();
});
app.use(express.json({ limit: "64mb" }));
app.use("/api", createRouter(store, { rootDir }));

const distDir = path.join(rootDir, "dist");
if (fs.existsSync(distDir)) {
  app.use(express.static(distDir, { index: "index.html" }));
  app.get(/^\/(?!api\/).*/, (_req, res) => {
    res.sendFile(path.join(distDir, "index.html"));
  });
} else {
  app.get("/", (_req, res) => {
    res
      .status(503)
      .type("text/plain")
      .send("Frontend bundle missing. Run: npm run build");
  });
}

app.use(
  (
    error: Error & { statusCode?: number },
    _req: express.Request,
    res: express.Response,
    _next: express.NextFunction
  ) => {
    const status = error.statusCode ?? 500;
    if (status >= 500) console.error(error);
    res.status(status).json({ error: error.message });
  }
);

async function main(): Promise<void> {
  await store.init();
  const server = app.listen(port, host, () => {
    console.log(`[seekdb-kb] listening on http://${host}:${port}`);
    console.log(`[seekdb-kb] database=${store.database} platform=${store.platform}`);
  });
  const shutdown = async (signal: string) => {
    console.log(`[seekdb-kb] ${signal} received, closing seekdb`);
    server.close();
    await store.close();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}

main().catch((error) => {
  console.error("[seekdb-kb] fatal:", error);
  process.exit(1);
});
