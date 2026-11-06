FROM node:20-slim

# seekdb's Linux native binding links against libaio.
RUN apt-get update \
  && apt-get install -y --no-install-recommends libaio1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./

# Override for restricted networks, e.g. --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org/
# The CPU binaries ship inside onnxruntime-node; without this flag its postinstall
# tries to download CUDA binaries from GitHub, which the runtime does not need.
ENV ONNXRUNTIME_NODE_INSTALL_CUDA=skip
RUN npm config set registry "$NPM_REGISTRY" \
  && npm ci --no-audit --no-fund --include=dev

COPY . .

# Pre-download the seekdb native bindings so the runtime image does not need
# network access, then expose libseekdb.so through LD_PRELOAD as the addon
# requires it to be resolved before dlopen.
ENV SEEKDB_BINDINGS_CACHE_DIR=/opt/seekdb-bindings
RUN node -e "require('/app/node_modules/@seekdb/js-bindings/download.js').ensureBindingsDownloaded().then((p) => console.log('[bindings]', p))" \
  && ln -sf "$(find /opt/seekdb-bindings -name libseekdb.so | head -n 1)" /opt/libseekdb.so

RUN npm run build

ENV NODE_ENV=production \
    LD_PRELOAD=/opt/libseekdb.so \
    STEPFUN_DB_PATH=/data/seekdb \
    STEPFUN_STATE_PATH=/data/state.json \
    PORT=8787 \
    HOST=0.0.0.0

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD node -e "fetch('http://127.0.0.1:8787/api/health').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "dist-server/index.js"]
