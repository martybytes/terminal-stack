ARG III_VERSION=0.11.2

FROM iiidev/iii:${III_VERSION} AS iii-image

FROM node:22-slim

ARG AGENTMEMORY_VERSION=0.9.29
ARG III_VERSION=0.11.2
ARG III_SDK_VERSION=0.11.2

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates tini gosu curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=iii-image /app/iii /usr/local/bin/iii

WORKDIR /opt/agentmemory
# Optional dependencies are installed on purpose. @huggingface/transformers is an
# optionalDependency of agentmemory and is the on-device embedding backend; with
# --omit=optional it is simply absent and agentmemory falls back to BM25-only
# keyword search. Costs ~300-500MB of image (ONNX runtime) and buys semantic
# search with no API key and no network dependency.
RUN printf '{"name":"agentmemory-deploy","version":"1.0.0","private":true,"overrides":{"iii-sdk":"%s"}}\n' "${III_SDK_VERSION}" > package.json \
 && npm install "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}" --no-fund --no-audit \
 && ln -s /opt/agentmemory/node_modules/.bin/agentmemory /usr/local/bin/agentmemory

# Deployment-local reliability patch for 0.9.29: durable file-backed LLM jobs,
# one-call provider gating, exact safe telemetry, resume-safe sessions, and
# sharded graph persistence. The assertion-based patch fails if the pinned
# layout moves.
COPY patch-agentmemory.mjs /tmp/patch-agentmemory.mjs
RUN node /tmp/patch-agentmemory.mjs && rm /tmp/patch-agentmemory.mjs

# Bake the embedding model into the image. agentmemory never sets transformers.js's
# cacheDir, so transformers.js uses its default: a .cache/ directory next to the
# package itself (NOT relative to cwd). Without this step the ~30MB model downloads
# on every container recreate, and a machine with no internet cannot start with
# semantic search at all.
#
# Model id and dtype must match the call inside the package exactly:
#   pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2", { dtype: "q8" })
# a different dtype resolves to a different ONNX file and the baked cache is ignored.
RUN node --input-type=module -e "import { pipeline } from '@huggingface/transformers'; await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', { dtype: 'q8' });" \
 && chown -R node:node /opt/agentmemory/node_modules/@huggingface/transformers/.cache

ENV AGENTMEMORY_III_VERSION=${III_VERSION} \
    TINI_SUBREAPER=1

COPY --chmod=0755 entrypoint.sh /usr/local/bin/agentmemory-entrypoint.sh

EXPOSE 3111 3113

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:3111/agentmemory/livez || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agentmemory-entrypoint.sh"]
