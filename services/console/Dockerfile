# agent007memory — companion console for agentmemory.
# Two listeners in one Node process:
#   3111  transparent reverse proxy -> agentmemory (live request capture)
#   3114  console UI + /api + /ws + /healthz
#
# Build is fully pinned by the lockfile (npm ci); the deploying compose file
# pins THIS repo by commit SHA in its build context.

FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json tsconfig.server.json vite.config.ts index.html ./
COPY public ./public
COPY docs ./docs
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PROXY_PORT=3111 \
    UI_PORT=3114 \
    HISTORY_DB_PATH=/data/agent007memory.sqlite \
    HISTORY_RETENTION_DAYS=365
WORKDIR /app
RUN mkdir -p /data && chown node:node /data
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
EXPOSE 3111 3114
USER node
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3114/healthz || exit 1
CMD ["node", "dist/server/index.js"]
