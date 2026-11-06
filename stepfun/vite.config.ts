import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: path.join(rootDir, "web"),
  publicDir: "public",
  resolve: {
    alias: {
      "@shared": path.join(rootDir, "shared"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: false,
      },
    },
    fs: {
      allow: [rootDir],
    },
  },
  build: {
    outDir: path.join(rootDir, "dist"),
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
  optimizeDeps: {
    exclude: ["onnxruntime-web"],
  },
});
