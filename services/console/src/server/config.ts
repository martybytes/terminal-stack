// All environment handling lives here; other modules import `config` only.
//
// Defaults are the DEV shape (backend on the host, agentmemory in Docker
// publishing 3111/3112 directly). The container overrides via ENV in the
// Dockerfile / compose: HOST=0.0.0.0, UPSTREAM_HTTP=http://agentmemory:3111,
// UPSTREAM_WS=ws://agentmemory:3112, SECRET_FILE=/upstream-data/.hmac.
// `npm run dev` sets PROXY_PORT=3121 so the dev proxy never collides with
// the real 3111.

function num(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

function optionalNum(name: string): number | null {
  const raw = process.env[name];
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function safeEndpoint(raw: string | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

export const config = {
  host: process.env.HOST ?? "127.0.0.1",
  proxyPort: num("PROXY_PORT", 3111),
  uiPort: num("UI_PORT", 3114),
  upstreamHttp: (process.env.UPSTREAM_HTTP ?? "http://127.0.0.1:3111").replace(/\/$/, ""),
  upstreamWs: (process.env.UPSTREAM_WS ?? "ws://127.0.0.1:3112").replace(/\/$/, ""),
  // Bearer for the console's OWN calls to agentmemory (proxy traffic passes
  // the caller's auth through untouched). File wins over env; re-read on 401.
  secretFile: process.env.SECRET_FILE ?? null,
  secretEnv: process.env.AGENTMEMORY_SECRET ?? null,
  // Ships off: request bodies carry memory contents. Metadata-only capture.
  captureBodies: process.env.CAPTURE_BODIES === "true",
  healthPollMs: num("HEALTH_POLL_MS", 15_000),
  llmPollMs: Math.max(1_000, num("LLM_POLL_MS", 3_000)),
  ringSize: num("RING_SIZE", 5_000),
  historyDbPath:
    process.env.HISTORY_DB_PATH ??
    (process.env.NODE_ENV === "production"
      ? "/data/agent007memory.sqlite"
      : ".agent007memory/history.sqlite"),
  historyRetentionDays: Math.max(1, Math.floor(num("HISTORY_RETENTION_DAYS", 365))),
  // Safe display-only mirrors of upstream settings. Deployments opt in by
  // forwarding these values; provider secrets are deliberately unsupported.
  llmProvider: process.env.LLM_PROVIDER ?? "configured LLM",
  llmEndpointLabel: process.env.LLM_ENDPOINT_LABEL ?? null,
  llmModel: process.env.LLM_MODEL ?? null,
  llmEndpoint: safeEndpoint(process.env.LLM_BASE_URL),
  llmTimeoutMs: optionalNum("LLM_TIMEOUT_MS"),
  llmMaxTokens: optionalNum("LLM_MAX_TOKENS"),
  llmSummarizeConcurrency: optionalNum("LLM_SUMMARIZE_CONCURRENCY"),
  llmProviderConcurrency: optionalNum("LLM_CONCURRENCY"),
  llmRecoveryBatchSize: optionalNum("LLM_RECOVERY_BATCH_SIZE"),
  llmGraphBatchSize: optionalNum("LLM_GRAPH_BATCH_SIZE"),
  embeddingProvider: process.env.LLM_EMBEDDING_PROVIDER ?? null,
  // Organization billing access is intentionally file-only. The console
  // stores no admin credential and scopes every query to one dedicated project.
  openAiAdminKeyFile: process.env.OPENAI_ADMIN_KEY_FILE ?? null,
  // A deliberately non-secret, already-masked fingerprint for the inference
  // key. Prefer a mounted file via OPENAI_INFERENCE_KEY_FILE when available;
  // the hint exists for deployments where the upstream owns the real key.
  openAiInferenceKeyFile: process.env.OPENAI_INFERENCE_KEY_FILE ?? null,
  llmApiKeyHint: process.env.LLM_API_KEY_HINT?.trim() || null,
  llmAdminKeyHint: process.env.LLM_ADMIN_KEY_HINT?.trim() || null,
  openAiInferenceKeyHint: process.env.OPENAI_INFERENCE_KEY_HINT?.trim() || null,
  openAiBillingProjectId: process.env.OPENAI_BILLING_PROJECT_ID?.trim() || null,
  openAiBillingProjectName: process.env.OPENAI_BILLING_PROJECT_NAME?.trim() || null,
  legacyOpenAiBillingApiKeyId: process.env.OPENAI_BILLING_API_KEY_ID?.trim() || null,
  billingSyncMs: Math.max(2 * 60 * 60_000, num("OPENAI_BILLING_SYNC_MS", 2 * 60 * 60_000)),
} as const;

export type Config = typeof config;
