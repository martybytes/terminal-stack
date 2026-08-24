import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// AgentMemory 0.9.29 launches every background LLM call immediately and stores
// its graph in a handful of ever-growing KV scopes. This pinned deployment
// patch adds a durable iii queue, safe per-call telemetry, resume-safe sessions,
// and sharded graph persistence. Keep it fail-fast so a package upgrade cannot
// silently apply only part of the compatibility layer.
//
// NEVER make a request path await a startup promise here. A patch that inserted
// `await agentmemoryStartupReady;` as the first line of `mem::search`, released by
// a `markAgentmemoryStartupReady()` call sited just before the "search active"
// boot log, deadlocked every search permanently on 2026-08-21: that boot line is
// never reached on this deployment's startup path, so the promise never resolved.
// Every search then hung until the engine killed the invocation at 180s (HTTP
// 504), and because the MCP bridge turns that into `{"results":[]}` rather than an
// error, `memory_recall` and `memory_smart_search` looked like "nothing found"
// across all three agents while capture kept working perfectly. If a request path
// ever genuinely needs to wait for startup, give the wait a timeout and a
// fallback, and prove the release actually runs before shipping it — an unreleased
// gate here is indistinguishable from an empty memory store.
//
// Duplicate hook invocations are NOT suppressed here any more. Codex fires two hook
// registrations for one event, which this patch used to absorb on /observe. It now
// belongs to terminal-stack (bootstrap/_agentmemory.ps1), which drops the duplicate
// inside the hook before the request is made — covering retrieval as well as capture,
// and keeping hook-duplication logic out of a server patch.
const distDir = "/opt/agentmemory/node_modules/@agentmemory/agentmemory/dist";
const candidates = readdirSync(distDir)
  .filter((name) => name === "index.mjs" || /^src-.*\.mjs$/.test(name))
  .map((name) => join(distDir, name));

function replaceOnce(source, before, after, label, file) {
  const first = source.indexOf(before);
  if (first === -1) return { source, changed: false };
  if (source.indexOf(before, first + before.length) !== -1) {
    throw new Error(`${label}: expected one match in ${file}, found multiple`);
  }
  return {
    source: source.slice(0, first) + after + source.slice(first + before.length),
    changed: true,
  };
}

function replaceInSection(source, patch, file) {
  if (!patch.section) {
    return replaceOnce(source, patch.before, patch.after, patch.label, file);
  }
  const start = source.indexOf(patch.section[0]);
  const end = source.indexOf(patch.section[1], start + patch.section[0].length);
  if (start === -1 || end === -1 || end <= start) {
    throw new Error(`${patch.label}: section markers not found in ${file}`);
  }
  const section = source.slice(start, end);
  const result = replaceOnce(section, patch.before, patch.after, patch.label, file);
  return {
    source: source.slice(0, start) + result.source + source.slice(end),
    changed: result.changed,
  };
}

const patches = [
  {
    label: "durable LLM queue and telemetry primitives",
    before: `//#region src/providers/agent-sdk.ts`,
    after: `const AGENTMEMORY_LLM_QUEUE = process.env.AGENTMEMORY_LLM_QUEUE || "agentmemory-llm";
const LLM_TELEMETRY_LIMIT = 500;
const llmCallContext = new AsyncLocalStorage();
const llmCallRows = [];
const llmJobRows = /* @__PURE__ */ new Map();
const llmTelemetryInstanceId = generateId("llminstance");
let llmTelemetrySequence = 0;
function nextLlmTelemetryId() {
\tllmTelemetrySequence += 1;
\treturn llmTelemetrySequence;
}
function boundedPushLlmCall(row) {
\tllmCallRows.push(row);
\tif (llmCallRows.length > LLM_TELEMETRY_LIMIT) llmCallRows.splice(0, llmCallRows.length - LLM_TELEMETRY_LIMIT);
}
function beginLlmCall(family, systemPrompt, userPrompt) {
\tconst context = llmCallContext.getStore() || {};
\tconst now = Date.now();
\tconst row = {
\t\tid: nextLlmTelemetryId(),
\t\tjobId: context.jobId || null,
\t\tfamily: context.family || family || "other",
\t\tstatus: "running",
\t\toutcome: null,
\t\tmodel: null,
\t\tpromptChars: systemPrompt.length + userPrompt.length,
\t\testimatedPromptTokens: Math.ceil((systemPrompt.length + userPrompt.length) / 4),
\t\tpromptTokens: null,
\t\tcachedPromptTokens: null,
\t\tcacheWriteTokens: null,
\t\tcompletionTokens: null,
\t\treasoningTokens: null,
\t\ttotalTokens: null,
\t\tprovider: "openai",
\t\tproject: context.project || null,
\t\tsessionId: context.sessionId || null,
\t\tqueuedAt: context.queuedAt || null,
\t\tstartedAt: now,
\t\tcompletedAt: null,
\t\tqueueWaitMs: context.queuedAt ? Math.max(0, now - context.queuedAt) : 0,
\t\tproviderLatencyMs: null
\t};
\tboundedPushLlmCall(row);
\treturn row;
}
function updateLlmCall(row, changes) {
\tif (row) Object.assign(row, changes);
}
function publicLlmJob(job) {
\treturn {
\t\tid: job.id,
\t\tfamily: job.family,
\t\tstatus: job.status,
\t\tattempt: job.attempt,
\t\tqueuedAt: job.queuedAt,
\t\tstartedAt: job.startedAt || null,
\t\tcompletedAt: job.completedAt || null,
\t\toutcome: job.outcome || null,
\t\tproject: job.project || null,
\t\tsessionId: job.sessionId || null
\t};
}
async function enqueueLlmJob(sdk, family, payload) {
\tconst jobId = generateId("llmjob");
\tconst queuedAt = Date.now();
\tllmJobRows.set(jobId, { id: jobId, family, status: "queued", attempt: 0, queuedAt, project: payload?.project || null, sessionId: payload?.sessionId || null });
\twhile (llmJobRows.size > LLM_TELEMETRY_LIMIT) llmJobRows.delete(llmJobRows.keys().next().value);
\ttry {
\t\tawait sdk.trigger({
\t\t\tfunction_id: "mem::llm-job",
\t\t\tpayload: { jobId, family, queuedAt, ...payload },
\t\t\taction: TriggerAction.Enqueue({ queue: AGENTMEMORY_LLM_QUEUE })
\t\t});
\t\treturn { success: true, queued: true, jobId };
\t} catch (err) {
\t\tconst job = llmJobRows.get(jobId);
\t\tif (job) Object.assign(job, { status: "failed", outcome: "enqueue_failed", completedAt: Date.now() });
\t\tthrow err;
\t}
}
function enterLlmCallContext(data, fallbackFamily) {
\tconst supplied = data?._llmJob;
\tllmCallContext.enterWith({
\t\tjobId: supplied?.jobId || null,
\t\tfamily: supplied?.family || fallbackFamily,
\t\tqueuedAt: supplied?.queuedAt || null,
\t\tproject: data?.project || supplied?.project || null,
\t\tsessionId: data?.sessionId || supplied?.sessionId || null
\t});
}
function safeLlmErrorOutcome(err) {
\tconst message = err instanceof Error ? err.message : String(err);
\tif (message.includes("circuit_breaker_open")) return "circuit_open";
\tif (message.toLowerCase().includes("timeout")) return "timeout";
\treturn "failure";
}
//#region src/providers/agent-sdk.ts`,
  },
  {
    label: "sharded graph state adapter",
    section: ["var StateKV = class", "//#endregion\n//#region src/state/vector-index.ts"],
    before: `var StateKV = class {
\tconstructor(sdk) {
\t\tthis.sdk = sdk;
\t}
\tasync get(scope, key) {
\t\treturn this.sdk.trigger({
\t\t\tfunction_id: "state::get",
\t\t\tpayload: {
\t\t\t\tscope,
\t\t\t\tkey
\t\t\t}
\t\t});
\t}
\tasync set(scope, key, value) {
\t\treturn this.sdk.trigger({
\t\t\tfunction_id: "state::set",
\t\t\tpayload: {
\t\t\t\tscope,
\t\t\t\tkey,
\t\t\t\tvalue
\t\t\t}
\t\t});
\t}
\tasync update(scope, key, ops) {
\t\treturn this.sdk.trigger({
\t\t\tfunction_id: "state::update",
\t\t\tpayload: {
\t\t\t\tscope,
\t\t\t\tkey,
\t\t\t\tops
\t\t\t}
\t\t});
\t}
\tasync delete(scope, key) {
\t\treturn this.sdk.trigger({
\t\t\tfunction_id: "state::delete",
\t\t\tpayload: {
\t\t\t\tscope,
\t\t\t\tkey
\t\t\t}
\t\t});
\t}
\tasync list(scope) {
\t\treturn this.sdk.trigger({
\t\t\tfunction_id: "state::list",
\t\t\tpayload: { scope }
\t\t});
\t}
};`,
    after: `const GRAPH_V2_SHARD_COUNT = 64;
const GRAPH_V2_MANIFEST_KEY = "graph:v2:manifest";
const GRAPH_V2_SCOPES = /* @__PURE__ */ new Set([
\t"mem:graph:nodes",
\t"mem:graph:edges",
\t"mem:graph:name-index",
\t"mem:graph:edge-key",
\t"mem:graph:node-degree"
]);
let graphV2Active = false;
let graphV2Migrating = false;
function isGraphV2Requested() {
\treturn process.env.AGENTMEMORY_GRAPH_STORAGE_V2 !== "false";
}
function graphShardScope(scope, key) {
\tconst byte = createHash("sha256").update(String(key)).digest()[0];
\treturn scope + ":v2:" + String(byte % GRAPH_V2_SHARD_COUNT).padStart(2, "0");
}
function compactGraphSnapshot(value) {
\tif (!value || typeof value !== "object") return value;
\tconst compact = (item) => {
\t\tif (!item || typeof item !== "object") return item;
\t\tconst refs = Array.isArray(item.sourceObservationIds) ? item.sourceObservationIds : [];
\t\treturn {
\t\t\t...item,
\t\t\tsourceObservationCount: refs.length,
\t\t\tsourceObservationIds: refs.slice(-32),
\t\t\t...(refs.length > 32 ? { provenanceTruncated: true } : {})
\t\t};
\t};
\treturn {
\t\t...value,
\t\tversion: 2,
\t\ttopNodes: Array.isArray(value.topNodes) ? value.topNodes.map(compact) : [],
\t\ttopEdges: Array.isArray(value.topEdges) ? value.topEdges.map(compact) : []
\t};
}
async function mapWithConcurrency(items, concurrency, fn) {
\tconst results = new Array(items.length);
\tlet next = 0;
\tawait Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
\t\tfor (;;) {
\t\t\tconst index = next++;
\t\t\tif (index >= items.length) return;
\t\t\tresults[index] = await fn(items[index], index);
\t\t}
\t}));
\treturn results;
}
var StateKV = class {
\tconstructor(sdk) {
\t\tthis.sdk = sdk;
\t}
\tresolvedScope(scope, key) {
\t\tif (!graphV2Active) return scope;
\t\tif (GRAPH_V2_SCOPES.has(scope)) return graphShardScope(scope, key);
\t\tif (scope === "mem:graph:snapshot") return "mem:graph:snapshot:v2";
\t\treturn scope;
\t}
\trawGet(scope, key, timeoutMs) {
\t\treturn this.sdk.trigger({ function_id: "state::get", payload: { scope, key }, timeoutMs });
\t}
\trawSet(scope, key, value, timeoutMs) {
\t\treturn this.sdk.trigger({ function_id: "state::set", payload: { scope, key, value }, timeoutMs });
\t}
\trawUpdate(scope, key, ops, timeoutMs) {
\t\treturn this.sdk.trigger({ function_id: "state::update", payload: { scope, key, ops }, timeoutMs });
\t}
\trawDelete(scope, key, timeoutMs) {
\t\treturn this.sdk.trigger({ function_id: "state::delete", payload: { scope, key }, timeoutMs });
\t}
\trawList(scope, timeoutMs) {
\t\treturn this.sdk.trigger({ function_id: "state::list", payload: { scope }, timeoutMs });
\t}
\tasync get(scope, key) {
\t\treturn this.rawGet(this.resolvedScope(scope, key), key);
\t}
\tasync set(scope, key, value) {
\t\tconst resolved = this.resolvedScope(scope, key);
\t\treturn this.rawSet(resolved, key, resolved === "mem:graph:snapshot:v2" ? compactGraphSnapshot(value) : value);
\t}
\tasync update(scope, key, ops) {
\t\treturn this.rawUpdate(this.resolvedScope(scope, key), key, ops);
\t}
\tasync delete(scope, key) {
\t\treturn this.rawDelete(this.resolvedScope(scope, key), key);
\t}
\tasync list(scope) {
\t\tif (graphV2Active && GRAPH_V2_SCOPES.has(scope)) {
\t\t\tconst scopes = Array.from({ length: GRAPH_V2_SHARD_COUNT }, (_, i) => scope + ":v2:" + String(i).padStart(2, "0"));
\t\t\treturn (await mapWithConcurrency(scopes, 8, (shard) => this.rawList(shard))).flat();
\t\t}
\t\treturn this.rawList(graphV2Active && scope === "mem:graph:snapshot" ? "mem:graph:snapshot:v2" : scope);
\t}
\tsetGraphV2(scope, key, value, timeoutMs = 6e5) {
\t\tconst resolved = GRAPH_V2_SCOPES.has(scope) ? graphShardScope(scope, key) : scope === "mem:graph:snapshot" ? "mem:graph:snapshot:v2" : scope;
\t\treturn this.rawSet(resolved, key, resolved === "mem:graph:snapshot:v2" ? compactGraphSnapshot(value) : value, timeoutMs);
\t}
\tasync listGraphV2(scope) {
\t\tif (!GRAPH_V2_SCOPES.has(scope)) return this.rawList(scope === "mem:graph:snapshot" ? "mem:graph:snapshot:v2" : scope, 6e5);
\t\tconst scopes = Array.from({ length: GRAPH_V2_SHARD_COUNT }, (_, i) => scope + ":v2:" + String(i).padStart(2, "0"));
\t\treturn (await mapWithConcurrency(scopes, 8, (shard) => this.rawList(shard, 6e5))).flat();
\t}
};`,
  },
  {
    label: "OpenAI provider fields",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\tazureApiVersion;\n\tconstructor(apiKey, model, maxTokens, baseURL) {`,
    after: `\tazureApiVersion;\n\tcompressionModel;\n\tcompressionMaxTokens;\n\tconstructor(apiKey, model, maxTokens, baseURL) {`,
  },
  {
    label: "independent compression settings",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\t\tthis.maxTokens = maxTokens;\n\t\tthis.baseUrl = normalizeBaseUrl(baseURL || getEnvVar("OPENAI_BASE_URL"));`,
    after: `\t\tthis.maxTokens = maxTokens;\n\t\tthis.compressionModel = getEnvVar("AGENTMEMORY_COMPRESSION_MODEL") || model;\n\t\tconst compressionMax = Number(getEnvVar("AGENTMEMORY_COMPRESSION_MAX_TOKENS"));\n\t\tthis.compressionMaxTokens = Number.isFinite(compressionMax) && compressionMax > 0 ? Math.floor(compressionMax) : Math.min(maxTokens, 1024);\n\t\tthis.baseUrl = normalizeBaseUrl(baseURL || getEnvVar("OPENAI_BASE_URL"));`,
  },
  {
    label: "compression model routing",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\tasync compress(systemPrompt, userPrompt) {\n\t\treturn this.call(systemPrompt, userPrompt);\n\t}\n\tasync summarize(systemPrompt, userPrompt) {\n\t\treturn this.call(systemPrompt, userPrompt);\n\t}\n\tasync call(systemPrompt, userPrompt) {`,
    after: `\tasync compress(systemPrompt, userPrompt) {\n\t\tconst family = llmCallContext.getStore()?.family;\n\t\tconst observationCompression = family === "compression";\n\t\treturn this.call(systemPrompt, userPrompt, observationCompression ? this.compressionModel : this.model, observationCompression ? this.compressionMaxTokens : this.maxTokens);\n\t}\n\tasync summarize(systemPrompt, userPrompt) {\n\t\treturn this.call(systemPrompt, userPrompt, this.model, this.maxTokens);\n\t}\n\tasync call(systemPrompt, userPrompt, model, maxTokens) {`,
  },
  {
    label: "per-call model and output budget",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\t\tconst body = {\n\t\t\tmodel: this.model,\n\t\t\tmax_tokens: this.maxTokens,`,
    after: `\t\tconst body = {\n\t\t\tmodel,`,
  },
  {
    label: "GPT-5.6 completion token parameter",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\t\t};\n\t\tif (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort;`,
    after: `\t\t};\n\t\tif (model.startsWith("gpt-5.6")) body.max_completion_tokens = maxTokens;\n\t\telse body.max_tokens = maxTokens;\n\t\tif (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort;`,
  },
  {
    label: "model telemetry before provider request",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\t\tif (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort;
\t\tlet response;`,
    after: `\t\tif (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort;
\t\tupdateLlmCall(llmCallContext.getStore()?.callRow, { model });
\t\tlet response;`,
  },
  {
    label: "provider token observability",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `\t\tconst data = await response.json();\n\t\tconst message = data.choices?.[0]?.message;`,
    after: `\t\tconst data = await response.json();\n\t\tif (data.usage) {\n\t\t\tconst promptDetails = data.usage.prompt_tokens_details || {};\n\t\t\tconst completionDetails = data.usage.completion_tokens_details || {};\n\t\t\tconst cachedPromptTokens = promptDetails.cached_tokens ?? null;\n\t\t\tconst cacheWriteTokens = promptDetails.cache_write_tokens ?? null;\n\t\t\tconst reasoningTokens = completionDetails.reasoning_tokens ?? null;\n\t\t\tupdateLlmCall(llmCallContext.getStore()?.callRow, { model, promptTokens: data.usage.prompt_tokens ?? null, cachedPromptTokens, cacheWriteTokens, completionTokens: data.usage.completion_tokens ?? null, reasoningTokens, totalTokens: data.usage.total_tokens ?? null });\n\t\t\tprocess.stderr.write(\`[agentmemory] llm_usage \${JSON.stringify({ model, promptTokens: data.usage.prompt_tokens, cachedPromptTokens, cacheWriteTokens, completionTokens: data.usage.completion_tokens, reasoningTokens, totalTokens: data.usage.total_tokens })}\\n\`);\n\t\t} else updateLlmCall(llmCallContext.getStore()?.callRow, { model });\n\t\tconst message = data.choices?.[0]?.message;`,
  },
  {
    label: "bounded oversized-session summary input",
    section: ["async function produceSummaryXml", "function stripXmlWrappers"],
    before: `async function produceSummaryXml(provider, compressed, sessionId, project) {\n\tconst chunkSize = getChunkSize();`,
    after: `async function produceSummaryXml(provider, compressed, sessionId, project) {\n\tconst sourceObservationCount = compressed.length;\n\tconst configuredMax = Number(process.env.AGENTMEMORY_SUMMARY_MAX_OBSERVATIONS || "500");\n\tconst maxObservations = Number.isFinite(configuredMax) && configuredMax > 0 ? Math.floor(configuredMax) : 500;\n\tif (compressed.length > maxObservations) {\n\t\tconst headCount = Math.min(50, Math.floor(maxObservations / 4));\n\t\tconst tailCount = Math.min(150, Math.floor(maxObservations / 3));\n\t\tconst middleCount = Math.max(0, maxObservations - headCount - tailCount);\n\t\tconst selected = new Set();\n\t\tfor (let i = 0; i < headCount; i++) selected.add(i);\n\t\tconst middleStart = headCount;\n\t\tconst middleEnd = Math.max(middleStart, compressed.length - tailCount);\n\t\tfor (let i = 0; i < middleCount; i++) selected.add(Math.min(middleEnd - 1, middleStart + Math.floor((i + .5) * (middleEnd - middleStart) / middleCount)));\n\t\tfor (let i = Math.max(0, compressed.length - tailCount); i < compressed.length; i++) selected.add(i);\n\t\tcompressed = [...selected].sort((a, b) => a - b).map((i) => compressed[i]).filter(Boolean);\n\t\tlogger.info("Summarize sampled oversized session", { sessionId, sourceObservations: sourceObservationCount, selectedObservations: compressed.length, maxObservations });\n\t}\n\tconst chunkSize = getChunkSize();`,
  },
  {
    label: "profile loads session summaries",
    section: ["function registerProfileFunction", "function extractConventions"],
    before: `\t\tconst obsPerSession = await Promise.all(top20Sessions.map((s) => kv.list(KV.observations(s.id)).catch(() => [])));`,
    after: `\t\tconst [obsPerSession, summariesPerSession] = await Promise.all([\n\t\t\tPromise.all(top20Sessions.map((s) => kv.list(KV.observations(s.id)).catch(() => []))),\n\t\t\tPromise.all(top20Sessions.map((s) => kv.get(KV.summaries, s.id).catch(() => null)))\n\t\t]);`,
  },
  {
    label: "profile merges summary concepts",
    section: ["function registerProfileFunction", "function extractConventions"],
    before: `\t\t\tconst observations = obsPerSession[i];\n\t\t\ttotalObs += observations.length;`,
    after: `\t\t\tconst observations = obsPerSession[i];\n\t\t\tconst summary = summariesPerSession[i];\n\t\t\tfor (const concept of summary?.concepts || []) conceptFreq.set(concept, (conceptFreq.get(concept) || 0) + 1);\n\t\t\ttotalObs += observations.length;`,
  },
  {
    label: "bounded resilient provider queue",
    section: ["var ResilientProvider = class", "//#region src/providers/fallback-chain.ts"],
    before: `\tbreaker = new CircuitBreaker();\n\tname;\n\tconstructor(inner) {\n\t\tthis.inner = inner;\n\t\tthis.name = \`resilient(\${inner.name})\`;\n\t}\n\tasync call(fn) {\n\t\tif (!this.breaker.isAllowed) throw new Error("circuit_breaker_open");\n\t\ttry {\n\t\t\tconst result = await fn();\n\t\t\tthis.breaker.recordSuccess();\n\t\t\treturn result;\n\t\t} catch (err) {\n\t\t\tthis.breaker.recordFailure();\n\t\t\tthrow err;\n\t\t}\n\t}\n\tasync compress(systemPrompt, userPrompt) {\n\t\treturn this.call(() => this.inner.compress(systemPrompt, userPrompt));\n\t}\n\tasync summarize(systemPrompt, userPrompt) {\n\t\treturn this.call(() => this.inner.summarize(systemPrompt, userPrompt));\n\t}`,
    after: `\tbreaker = new CircuitBreaker();\n\tname;\n\tactive = 0;\n\twaiters = [];\n\tconcurrency;\n\tconstructor(inner) {\n\t\tthis.inner = inner;\n\t\tthis.name = \`resilient(\${inner.name})\`;\n\t\tconst configured = Number(process.env.AGENTMEMORY_LLM_CONCURRENCY || "1");\n\t\tthis.concurrency = Number.isFinite(configured) && configured > 0 ? Math.floor(configured) : 1;\n\t}\n\tasync acquire() {\n\t\tconst queuedAt = Date.now();\n\t\tif (this.active >= this.concurrency) await new Promise((resolve) => this.waiters.push(resolve));\n\t\tthis.active += 1;\n\t\treturn Date.now() - queuedAt;\n\t}\n\trelease() {\n\t\tthis.active -= 1;\n\t\tthis.waiters.shift()?.();\n\t}\n\tasync call(family, systemPrompt, userPrompt, fn) {\n\t\tconst inherited = llmCallContext.getStore() || {};\n\t\tconst resolvedFamily = inherited.family || family;\n\t\tconst queueDepth = this.waiters.length + Math.max(0, this.active - this.concurrency + 1);\n\t\tconst providerGateWaitMs = await this.acquire();\n\t\tconst row = beginLlmCall(resolvedFamily, systemPrompt, userPrompt);\n\t\tupdateLlmCall(row, { providerGateWaitMs, providerQueueDepth: queueDepth, active: this.active, waiting: this.waiters.length });\n\t\tconst startedAt = Date.now();\n\t\tlet outcome = "success";\n\t\ttry {\n\t\t\treturn await llmCallContext.run({ ...inherited, family: resolvedFamily, callRow: row }, async () => {\n\t\t\t\tif (!this.breaker.isAllowed) throw new Error("circuit_breaker_open");\n\t\t\t\ttry {\n\t\t\t\t\tconst result = await fn();\n\t\t\t\t\tthis.breaker.recordSuccess();\n\t\t\t\t\treturn result;\n\t\t\t\t} catch (err) {\n\t\t\t\t\tthis.breaker.recordFailure();\n\t\t\t\t\tthrow err;\n\t\t\t\t}\n\t\t\t});\n\t\t} catch (err) {\n\t\t\toutcome = safeLlmErrorOutcome(err);\n\t\t\tthrow err;\n\t\t} finally {\n\t\t\tconst completedAt = Date.now();\n\t\t\tupdateLlmCall(row, { status: "completed", outcome, completedAt, providerLatencyMs: completedAt - startedAt });\n\t\t\tprocess.stderr.write(\`[agentmemory] llm_call \${JSON.stringify({ id: row.id, jobId: row.jobId, family: resolvedFamily, outcome, promptChars: row.promptChars, estimatedPromptTokens: row.estimatedPromptTokens, queueWaitMs: row.queueWaitMs, providerGateWaitMs, providerLatencyMs: completedAt - startedAt, active: this.active, waiting: this.waiters.length })}\\n\`);\n\t\t\tthis.release();\n\t\t}\n\t}\n\tasync compress(systemPrompt, userPrompt) {\n\t\treturn this.call("compression", systemPrompt, userPrompt, () => this.inner.compress(systemPrompt, userPrompt));\n\t}\n\tasync summarize(systemPrompt, userPrompt) {\n\t\treturn this.call("summary", systemPrompt, userPrompt, () => this.inner.summarize(systemPrompt, userPrompt));\n\t}`,
  },
  {
    label: "dedup race guard",
    before: `\t\treturn withKeyedLock(\`obs:\${payload.sessionId}\`, async () => {\n\t\t\tif (maxObservationsPerSession && maxObservationsPerSession > 0) {`,
    after: `\t\treturn withKeyedLock(\`obs:\${payload.sessionId}\`, async () => {\n\t\t\tif (dedupMap && dedupHash && dedupMap.isDuplicate(dedupHash)) return {\n\t\t\t\tdeduplicated: true,\n\t\t\t\tsessionId: payload.sessionId\n\t\t\t};\n\t\t\tif (maxObservationsPerSession && maxObservationsPerSession > 0) {`,
  },
  {
    label: "uncategorized provider calls use other family",
    section: ["var ResilientProvider = class", "//#region src/providers/fallback-chain.ts"],
    before: `\tasync compress(systemPrompt, userPrompt) {
\t\treturn this.call("compression", systemPrompt, userPrompt, () => this.inner.compress(systemPrompt, userPrompt));
\t}
\tasync summarize(systemPrompt, userPrompt) {
\t\treturn this.call("summary", systemPrompt, userPrompt, () => this.inner.summarize(systemPrompt, userPrompt));
\t}`,
    after: `\tasync compress(systemPrompt, userPrompt) {
\t\treturn this.call("other", systemPrompt, userPrompt, () => this.inner.compress(systemPrompt, userPrompt));
\t}
\tasync summarize(systemPrompt, userPrompt) {
\t\treturn this.call("other", systemPrompt, userPrompt, () => this.inner.summarize(systemPrompt, userPrompt));
\t}`,
  },
  {
    label: "observation compression uses durable queue",
    section: ["function registerObserveFunction", "//#region src/functions/image-quota-cleanup.ts"],
    before: `\t\t\tif (isAutoCompressEnabled()) await sdk.trigger({
\t\t\t\tfunction_id: "mem::compress",
\t\t\t\tpayload: {
\t\t\t\t\tobservationId: obsId,
\t\t\t\t\tsessionId: payload.sessionId,
\t\t\t\t\traw
\t\t\t\t},
\t\t\t\taction: TriggerAction.Void()
\t\t\t});`,
    after: `\t\t\tif (isAutoCompressEnabled()) await enqueueLlmJob(sdk, "compression", {
\t\t\t\tobservationId: obsId,
\t\t\t\tsessionId: payload.sessionId
\t\t\t});`,
  },
  {
    label: "compression telemetry context",
    section: ["function registerCompressFunction", "//#region src/functions/context.ts"],
    before: `\tsdk.registerFunction("mem::compress", async (data) => {
\t\tconst startMs = Date.now();`,
    after: `\tsdk.registerFunction("mem::compress", async (data) => {
\t\tenterLlmCallContext(data, "compression");
\t\tconst startMs = Date.now();`,
  },
  {
    label: "summary telemetry context",
    section: ["function registerSummarizeFunction", "//#region src/functions/migrate.ts"],
    before: `\tsdk.registerFunction("mem::summarize", async (data) => {
\t\tconst startMs = Date.now();`,
    after: `\tsdk.registerFunction("mem::summarize", async (data) => {
\t\tenterLlmCallContext(data, "summary");
\t\tconst startMs = Date.now();`,
  },
  {
    label: "graph telemetry context",
    section: ["function registerGraphFunction", "function registerGraphImportFunction"],
    before: `\tsdk.registerFunction("mem::graph-extract", async (data) => {
\t\tif (!data.observations || data.observations.length === 0)`,
    after: `\tsdk.registerFunction("mem::graph-extract", async (data) => {
\t\tenterLlmCallContext(data, "graph");
\t\tif (!data.observations || data.observations.length === 0)`,
  },
  {
    label: "consolidation telemetry context",
    section: ["function registerConsolidationPipelineFunction", "//#region src/functions/team.ts"],
    before: `\tsdk.registerFunction("mem::consolidate-pipeline", async (data) => {`,
    after: `\tsdk.registerFunction("mem::consolidate-pipeline", async (data) => {
\t\tenterLlmCallContext(data, "consolidation");`,
  },
  {
    label: "durable LLM job handlers",
    before: `//#region src/functions/context.ts`,
    after: `function registerDurableLlmFunctions(sdk, kv) {
\tasync function summaryDue(sessionId) {
\t\tconst [compressed, existing] = await Promise.all([
\t\t\tkv.list(KV.observations(sessionId)).then((items) => items.filter((o) => o.title)),
\t\t\tkv.get(KV.summaries, sessionId).catch(() => null)
\t\t]);
\t\tconst configuredMinimum = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_OBSERVATIONS || "10");
\t\tconst minimum = Number.isFinite(configuredMinimum) && configuredMinimum > 0 ? Math.floor(configuredMinimum) : 10;
\t\tconst configuredDelta = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_NEW_OBSERVATIONS || "25");
\t\tconst minimumDelta = Number.isFinite(configuredDelta) && configuredDelta > 0 ? Math.floor(configuredDelta) : 25;
\t\tconst configuredAge = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MAX_AGE_MS || "3600000");
\t\tconst maximumAge = Number.isFinite(configuredAge) && configuredAge > 0 ? configuredAge : 36e5;
\t\tconst delta = Math.max(0, compressed.length - (Number(existing?.observationCount) || 0));
\t\tconst age = existing?.createdAt ? Date.now() - new Date(existing.createdAt).getTime() : Infinity;
\t\treturn {
\t\t\tdue: compressed.length >= minimum && (!existing || delta >= minimumDelta || delta > 0 && age >= maximumAge),
\t\t\tcompressed: compressed.length,
\t\t\tdelta,
\t\t\treason: compressed.length < minimum ? "not_enough_observations" : "not_enough_changes"
\t\t};
\t}
\tfunction requestedProject(data = {}, required = false) {
\t\tconst project = typeof data.project === "string" && data.project.trim() ? data.project.trim() : null;
\t\tif (required && !project && data.allProjects !== true) throw new Error("project_or_allProjects_required");
\t\treturn project;
\t}
\tasync function selectSessions(data = {}, required = false) {
\t\tconst project = requestedProject(data, required);
\t\treturn (await kv.list(KV.sessions)).filter((session) => {
\t\t\tif (data.sessionId && session?.id !== data.sessionId) return false;
\t\t\tif (project && session?.project !== project) return false;
\t\t\treturn true;
\t\t});
\t}
\tasync function maintenancePreview(data = {}) {
\t\tconst project = requestedProject(data, true);
\t\tconst sessions = await selectSessions(data, true);
\t\tlet observations = 0;
\t\tlet compressedObservations = 0;
\t\tlet scanErrors = 0;
\t\tfor (const session of sessions) {
\t\t\tif (!session?.id) { scanErrors += 1; continue; }
\t\t\ttry {
\t\t\t\tconst rows = await kv.list(KV.observations(session.id));
\t\t\t\tobservations += rows.length;
\t\t\t\tcompressedObservations += rows.filter((row) => row.title).length;
\t\t\t} catch { scanErrors += 1; }
\t\t}
\t\treturn { success: true, dryRun: true, scope: project || "all", sessions: sessions.length, observations, compressedObservations, scanErrors, queuedJobs: 2 };
\t}
\tasync function recoverPendingBatch(data = {}) {
\t\tconst configuredBatch = Number(process.env.AGENTMEMORY_LLM_RECOVERY_BATCH_SIZE || "25");
\t\tconst batchSize = Number.isFinite(configuredBatch) && configuredBatch > 0 ? Math.min(100, Math.floor(configuredBatch)) : 25;
\t\tconst sessions = await selectSessions(data);
\t\tconst recoverableSessions = [];
\t\tconst pending = [];
\t\tlet rawObservations = 0;
\t\tlet reconciledSessions = 0;
\t\tlet scanErrors = 0;
\t\tfor (const session of sessions) {
\t\t\tif (!session?.id) {
\t\t\t\tscanErrors += 1;
\t\t\t\tlogger.warn("LLM recovery skipped malformed session", { reason: "missing_session_id" });
\t\t\t\tcontinue;
\t\t\t}
\t\t\ttry {
\t\t\t\tconst observations = await kv.list(KV.observations(session.id));
\t\t\t\trecoverableSessions.push(session);
\t\t\t\tconst raw = observations.filter((observation) => !observation.title);
\t\t\t\trawObservations += raw.length;
\t\t\t\tfor (const observation of raw) {
\t\t\t\t\tif (pending.length < batchSize) pending.push({ sessionId: session.id, observationId: observation.id });
\t\t\t\t}
\t\t\t\tif (!data.dryRun && session.observationCount !== observations.length) {
\t\t\t\t\tawait kv.update(KV.sessions, session.id, [{ type: "set", path: "observationCount", value: observations.length }]);
\t\t\t\t\treconciledSessions += 1;
\t\t\t\t}
\t\t\t} catch (err) {
\t\t\t\tscanErrors += 1;
\t\t\t\tlogger.warn("LLM recovery skipped unreadable session", { sessionId: session.id, error: err instanceof Error ? err.message : String(err) });
\t\t\t}
\t\t}
\t\tif (!data.dryRun && !data.skipCompression) for (const item of pending) await enqueueLlmJob(sdk, "compression", item);
\t\tconst hasMore = !data.skipCompression && rawObservations > pending.length;
\t\tif (!data.dryRun && hasMore) {
\t\t\tawait enqueueLlmJob(sdk, "recovery", {
\t\t\t\tsessionId: data.sessionId,
\t\t\t\tproject: requestedProject(data),
\t\t\t\tskipCompression: data.skipCompression,
\t\t\t\tskipSummary: data.skipSummary,
\t\t\t\tskipGraph: data.skipGraph
\t\t\t});
\t\t} else if (!data.dryRun) {
\t\t\tfor (const session of recoverableSessions) {
\t\t\t\tif (process.env.AGENTMEMORY_AUTO_SUMMARIZE !== "false" && !data.skipSummary) await enqueueLlmJob(sdk, "summary", { sessionId: session.id });
\t\t\t\tif (process.env.GRAPH_EXTRACTION_ENABLED === "true" && !data.skipGraph) await enqueueLlmJob(sdk, "graph", { sessionId: session.id });
\t\t\t}
\t\t}
\t\tconst result = { success: true, dryRun: data.dryRun === true, project: requestedProject(data), sessions: sessions.length, recoverableSessions: recoverableSessions.length, rawObservations, queuedCompression: data.skipCompression ? 0 : pending.length, projectedSummaryJobs: data.skipSummary ? 0 : recoverableSessions.length, projectedGraphJobs: data.skipGraph ? 0 : recoverableSessions.length, hasMore, reconciledSessions, scanErrors };
\t\tlogger.info(data.dryRun ? "Pending LLM recovery previewed" : "Pending LLM recovery batch queued", result);
\t\treturn result;
\t}
\tsdk.registerFunction("mem::llm-maintenance-preview", maintenancePreview);
\tsdk.registerFunction("mem::llm-maintenance-run", async (data = {}) => {
\t\tconst preview = await maintenancePreview(data);
\t\tconst project = requestedProject(data, true);
\t\tconst basic = await enqueueLlmJob(sdk, "consolidation", { project, allProjects: data.allProjects === true, maintenanceStep: "basic" });
\t\tconst pipeline = await enqueueLlmJob(sdk, "consolidation", { project, allProjects: data.allProjects === true, maintenanceStep: "pipeline" });
\t\treturn { ...preview, dryRun: false, jobs: [basic.jobId, pipeline.jobId] };
\t});
\tsdk.registerFunction("mem::llm-summary-run", async (data = {}) => {
\t\tif (!data.sessionId || !await kv.get(KV.sessions, data.sessionId).catch(() => null)) throw new Error("valid_sessionId_required");
\t\treturn enqueueLlmJob(sdk, "summary", { sessionId: data.sessionId, project: data.project, force: true });
\t});
\tsdk.registerFunction("mem::llm-recovery-preview", async (data = {}) => recoverPendingBatch({ ...data, dryRun: true }));
\tsdk.registerFunction("mem::llm-job", async (data) => {
\t\tif (!data?.jobId || !data?.family) throw new Error("invalid_llm_job");
\t\tenterLlmCallContext(data, data.family);
\t\tlet job = llmJobRows.get(data.jobId);
\t\tif (!job) {
\t\t\tjob = { id: data.jobId, family: data.family, status: "queued", attempt: 0, queuedAt: data.queuedAt || Date.now() };
\t\t\tllmJobRows.set(data.jobId, job);
\t\t}
\t\tObject.assign(job, { status: "running", attempt: (job.attempt || 0) + 1, startedAt: Date.now(), outcome: null });
\t\tconst forwarded = { jobId: data.jobId, family: data.family, queuedAt: data.queuedAt || job.queuedAt, project: data.project || null, sessionId: data.sessionId || null };
\t\ttry {
\t\t\tlet result;
\t\t\tif (data.family === "compression") {
\t\t\t\tconst raw = await kv.get(KV.observations(data.sessionId), data.observationId);
\t\t\t\tif (!raw) result = { success: true, skipped: true, reason: "observation_missing" };
\t\t\t\telse if (raw.title) result = { success: true, skipped: true, reason: "already_compressed" };
\t\t\t\telse result = await sdk.trigger({ function_id: "mem::compress", payload: { observationId: data.observationId, sessionId: data.sessionId, raw, _llmJob: forwarded } });
\t\t\t} else if (data.family === "summary") {
\t\t\t\tconst due = await summaryDue(data.sessionId);
\t\t\t\tresult = data.force === true || due.due ? await sdk.trigger({ function_id: "mem::summarize", payload: { sessionId: data.sessionId, project: data.project, _llmJob: forwarded } }) : { success: true, skipped: true, reason: due.reason, observationCount: due.compressed, newObservations: due.delta };
\t\t\t} else if (data.family === "graph") {
\t\t\t\tif (graphV2Migrating) throw new Error("graph_v2_migration_in_progress");
\t\t\t\tresult = await sdk.trigger({ function_id: "mem::graph-extract-incremental", payload: { sessionId: data.sessionId, _llmJob: forwarded } });
\t\t\t} else if (data.family === "consolidation") {
\t\t\t\tresult = data.maintenanceStep === "basic"
\t\t\t\t\t? await sdk.trigger({ function_id: "mem::consolidate", payload: { project: data.project, minObservations: 10, _llmJob: forwarded } })
\t\t\t\t\t: await sdk.trigger({ function_id: "mem::consolidate-pipeline", payload: { project: data.project, tier: "all", force: true, _llmJob: forwarded } });
\t\t\t} else if (data.family === "recovery") {
\t\t\t\tresult = await recoverPendingBatch(data);
\t\t\t} else throw new Error("unsupported_llm_job_family");
\t\t\tif (result?.success === false) throw new Error(\`llm_job_failed:\${data.family}\`);
\t\t\tObject.assign(job, { status: "completed", outcome: result?.skipped ? "skipped" : "success", completedAt: Date.now() });
\t\t\treturn result;
\t\t} catch (err) {
\t\t\tObject.assign(job, { status: "queued", outcome: safeLlmErrorOutcome(err), completedAt: null });
\t\t\tthrow err;
\t\t}
\t});
\tsdk.registerFunction("mem::llm-requeue-pending", async (data = {}) => {
\t\treturn enqueueLlmJob(sdk, "recovery", {
\t\t\tsessionId: data.sessionId,
\t\t\tproject: requestedProject(data),
\t\t\tskipCompression: data.skipCompression === true,
\t\t\tskipSummary: data.skipSummary === true,
\t\t\tskipGraph: data.skipGraph === true
\t\t});
\t});
}
//#region src/functions/context.ts`,
  },
  {
    label: "resume safe REST session start",
    section: ["sdk.registerFunction(\"api::session::start\"", "sdk.registerFunction(\"api::session::end\""],
    before: `\t\tconst session = {
\t\t\tid: sessionId,
\t\t\tproject,
\t\t\tcwd,
\t\t\tstartedAt: (/* @__PURE__ */ new Date()).toISOString(),
\t\t\tstatus: "active",
\t\t\tobservationCount: 0,
\t\t\t...title ? { summary: title.slice(0, 200) } : {},
\t\t\t...title ? { firstPrompt: title.slice(0, 200) } : {},
\t\t\t...agentId ? { agentId } : {}
\t\t};`,
    after: `\t\tconst [existingSession, existingObservations] = await Promise.all([
\t\t\tkv.get(KV.sessions, sessionId).catch(() => null),
\t\t\tkv.list(KV.observations(sessionId)).catch(() => [])
\t\t]);
\t\tconst { endedAt: _endedAt, ...previousSession } = existingSession || {};
\t\tconst now = (/* @__PURE__ */ new Date()).toISOString();
\t\tconst session = {
\t\t\t...previousSession,
\t\t\tid: sessionId,
\t\t\tproject,
\t\t\tcwd,
\t\t\tstartedAt: existingSession?.startedAt || now,
\t\t\tupdatedAt: now,
\t\t\tstatus: "active",
\t\t\tobservationCount: existingObservations.length,
\t\t\t...title ? { summary: title.slice(0, 200) } : {},
\t\t\t...title && !existingSession?.firstPrompt ? { firstPrompt: title.slice(0, 200) } : {},
\t\t\t...agentId ? { agentId } : {}
\t\t};`,
  },
  {
    label: "resume safe event session start",
    section: ["sdk.registerFunction(\"event::session::started\"", "sdk.registerFunction(\"event::observation\""],
    before: `\t\tconst session = {
\t\t\tid: data.sessionId,
\t\t\tproject: data.project,
\t\t\tcwd: data.cwd,
\t\t\tstartedAt: (/* @__PURE__ */ new Date()).toISOString(),
\t\t\tstatus: "active",
\t\t\tobservationCount: 0,
\t\t\t...agentId ? { agentId } : {}
\t\t};`,
    after: `\t\tconst [existingSession, existingObservations] = await Promise.all([
\t\t\tkv.get(KV.sessions, data.sessionId).catch(() => null),
\t\t\tkv.list(KV.observations(data.sessionId)).catch(() => [])
\t\t]);
\t\tconst { endedAt: _endedAt, ...previousSession } = existingSession || {};
\t\tconst now = (/* @__PURE__ */ new Date()).toISOString();
\t\tconst session = {
\t\t\t...previousSession,
\t\t\tid: data.sessionId,
\t\t\tproject: data.project,
\t\t\tcwd: data.cwd,
\t\t\tstartedAt: existingSession?.startedAt || now,
\t\t\tupdatedAt: now,
\t\t\tstatus: "active",
\t\t\tobservationCount: existingObservations.length,
\t\t\t...agentId ? { agentId } : {}
\t\t};`,
  },
  {
    label: "REST observe propagates storage failures",
    section: ["sdk.registerFunction(\"api::observe\"", "sdk.registerFunction(\"api::context\""],
    before: `\t\treturn {
\t\t\tstatus_code: 201,
\t\t\tbody: await sdk.trigger({
\t\t\t\tfunction_id: "mem::observe",
\t\t\t\tpayload
\t\t\t})
\t\t};`,
    after: `\t\tconst result = await sdk.trigger({ function_id: "mem::observe", payload });
\t\treturn {
\t\t\tstatus_code: result?.success === false ? 503 : 201,
\t\t\tbody: result
\t\t};`,
  },
  {
    label: "LLM telemetry and administration REST endpoints",
    before: `\tsdk.registerFunction("api::health", async (req) => {`,
    after: `\tsdk.registerFunction("api::llm-telemetry", async (req) => {
\t\tconst afterId = Math.max(0, Number(req.query_params?.["afterId"]) || 0);
\t\tconst limit = Math.max(1, Math.min(500, Number(req.query_params?.["limit"]) || 200));
\t\tconst calls = llmCallRows.filter((row) => row.id > afterId).slice(-limit);
\t\tconst jobs = [...llmJobRows.values()].sort((a, b) => b.queuedAt - a.queuedAt).slice(0, limit).map(publicLlmJob);
\t\tconst queue = await sdk.trigger({ function_id: "engine::queue::topic_stats", payload: { topic: AGENTMEMORY_LLM_QUEUE } }).catch(() => null);
\t\tconst circuitBreaker = provider && "circuitState" in provider ? provider.circuitState : null;
\t\treturn {
\t\t\tstatus_code: 200,
\t\t\tbody: {
\t\t\t\tts: Date.now(),
\t\t\t\tqueueName: AGENTMEMORY_LLM_QUEUE,
\t\t\t\tinstanceId: llmTelemetryInstanceId,
\t\t\t\tqueue,
\t\t\t\tactiveJobs: jobs.filter((job) => job.status === "running").length,
\t\t\t\tcircuitBreaker,
\t\t\t\tcalls,
\t\t\t\tjobs,
\t\t\t\tnextAfterId: llmCallRows.at(-1)?.id || afterId
\t\t\t}
\t\t};
\t});
\tsdk.registerTrigger({
\t\ttype: "http",
\t\tfunction_id: "api::llm-telemetry",
\t\tconfig: { api_path: "/agentmemory/llm/telemetry", http_method: "GET", middleware_function_ids: ["middleware::api-auth"] }
\t});
\tconst operatorPayload = (req) => ({
\t\tproject: typeof req.body?.project === "string" ? req.body.project.trim().slice(0, 200) : void 0,
\t\tallProjects: req.body?.allProjects === true,
\t\tsessionId: typeof req.body?.sessionId === "string" ? req.body.sessionId.trim().slice(0, 200) : void 0,
\t\tskipCompression: req.body?.skipCompression === true,
\t\tskipSummary: req.body?.skipSummary === true,
\t\tskipGraph: req.body?.skipGraph === true
\t});
\tsdk.registerFunction("api::llm-maintenance-preview", async (req) => ({ status_code: 200, body: await sdk.trigger({ function_id: "mem::llm-maintenance-preview", payload: operatorPayload(req) }) }));
\tsdk.registerTrigger({ type: "http", function_id: "api::llm-maintenance-preview", config: { api_path: "/agentmemory/llm/maintenance/preview", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] } });
\tsdk.registerFunction("api::llm-maintenance-run", async (req) => ({ status_code: 202, body: await sdk.trigger({ function_id: "mem::llm-maintenance-run", payload: operatorPayload(req) }) }));
\tsdk.registerTrigger({ type: "http", function_id: "api::llm-maintenance-run", config: { api_path: "/agentmemory/llm/maintenance", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] } });
\tsdk.registerFunction("api::llm-summary-run", async (req) => ({ status_code: 202, body: await sdk.trigger({ function_id: "mem::llm-summary-run", payload: operatorPayload(req) }) }));
\tsdk.registerTrigger({ type: "http", function_id: "api::llm-summary-run", config: { api_path: "/agentmemory/llm/summarize", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] } });
\tsdk.registerFunction("api::llm-recovery-preview", async (req) => ({ status_code: 200, body: await sdk.trigger({ function_id: "mem::llm-recovery-preview", payload: operatorPayload(req), timeoutMs: 6e5 }) }));
\tsdk.registerTrigger({ type: "http", function_id: "api::llm-recovery-preview", config: { api_path: "/agentmemory/llm/recovery/preview", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] } });
\tsdk.registerFunction("api::llm-requeue-pending", async (req) => ({
\t\tstatus_code: 202,
\t\tbody: await sdk.trigger({ function_id: "mem::llm-requeue-pending", payload: {
\t\t\tsessionId: typeof req.body?.sessionId === "string" ? req.body.sessionId : void 0,
\t\t\tproject: typeof req.body?.project === "string" ? req.body.project.trim().slice(0, 200) : void 0,
\t\t\tskipCompression: req.body?.skipCompression === true,
\t\t\tskipSummary: req.body?.skipSummary === true,
\t\t\tskipGraph: req.body?.skipGraph === true
\t\t} })
\t}));
\tsdk.registerTrigger({
\t\ttype: "http",
\t\tfunction_id: "api::llm-requeue-pending",
\t\tconfig: { api_path: "/agentmemory/llm/requeue-pending", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] }
\t});
\tsdk.registerFunction("api::graph-migration-start", async () => {
\t\tconst result = await sdk.trigger({ function_id: "mem::graph-migrate-v2", payload: {}, timeoutMs: 6e5 });
\t\treturn { status_code: result?.success === false ? 500 : 200, body: result };
\t});
\tsdk.registerTrigger({
\t\ttype: "http",
\t\tfunction_id: "api::graph-migration-start",
\t\tconfig: { api_path: "/agentmemory/admin/graph-migration", http_method: "POST", middleware_function_ids: ["middleware::api-auth"] }
\t});
\tsdk.registerFunction("api::graph-migration-status", async () => ({
\t\tstatus_code: 200,
\t\tbody: await sdk.trigger({ function_id: "mem::graph-migration-status", payload: {} })
\t}));
\tsdk.registerTrigger({
\t\ttype: "http",
\t\tfunction_id: "api::graph-migration-status",
\t\tconfig: { api_path: "/agentmemory/admin/graph-migration", http_method: "GET", middleware_function_ids: ["middleware::api-auth"] }
\t});
\tsdk.registerFunction("api::health", async (req) => {`,
  },
  {
    label: "graph v2 snapshot compatibility",
    section: ["async function readSnapshot", "function buildSnapshotFromArrays"],
    before: `\t\tif (snap && typeof snap === "object" && snap.version === 1) return snap;`,
    after: `\t\tif (snap && typeof snap === "object" && (snap.version === 1 || snap.version === 2)) return snap;`,
  },
  {
    label: "graph v2 snapshot version",
    section: ["function emptySnapshot", "async function readSnapshot"],
    before: `\t\tversion: 1,`,
    after: `\t\tversion: graphV2Active ? 2 : 1,`,
  },
  {
    label: "graph provenance merge fix",
    section: ["function mergeNode", "function resolvePagination"],
    before: `function mergeNode(existing, incoming, obsIds, capturedAt) {
\treturn {
\t\t...existing,
\t\tsourceObservationIds: [...new Set([
\t\t\t...existing.sourceObservationIds,
\t\t\t...incoming.sourceObservationIds,
\t\t\t...obsIds
\t\t])],
\t\tproperties: {
\t\t\t...existing.properties,
\t\t\t...incoming.properties
\t\t},
\t\tupdatedAt: capturedAt
\t};
}
function mergeEdge(existing, obsIds) {
\treturn {
\t\t...existing,
\t\tsourceObservationIds: [...new Set([...existing.sourceObservationIds, ...obsIds])]
\t};
}`,
    after: `function mergeNode(existing, incoming, capturedAt) {
\treturn {
\t\t...existing,
\t\tsourceObservationIds: [...new Set([...existing.sourceObservationIds, ...incoming.sourceObservationIds])],
\t\tproperties: {
\t\t\t...existing.properties,
\t\t\t...incoming.properties
\t\t},
\t\tupdatedAt: capturedAt
\t};
}
function mergeEdge(existing, incoming) {
\treturn {
\t\t...existing,
\t\tsourceObservationIds: [...new Set([...existing.sourceObservationIds, ...incoming.sourceObservationIds])]
\t};
}`,
  },
  {
    label: "graph provenance merge call sites",
    section: ["async function persistGraphDelta", "function registerGraphFunction"],
    before: `\t\t\tconst merged = mergeNode(existing, node, obsIds, capturedAt);`,
    after: `\t\t\tconst merged = mergeNode(existing, node, capturedAt);`,
  },
  {
    label: "graph edge provenance merge call site",
    section: ["async function persistGraphDelta", "function registerGraphFunction"],
    before: `\t\t\tconst merged = mergeEdge(existing, obsIds);`,
    after: `\t\t\tconst merged = mergeEdge(existing, edge);`,
  },
  {
    label: "graph v2 migration functions",
    before: `function registerGraphFunction(sdk, kv, provider) {`,
    after: `function registerGraphV2MigrationFunction(sdk, kv) {
\tsdk.registerFunction("mem::graph-migration-status", async () => {
\t\tconst manifest = await kv.rawGet(KV.config, GRAPH_V2_MANIFEST_KEY).catch(() => null);
\t\treturn { success: true, active: graphV2Active, migrating: graphV2Migrating, manifest };
\t});
\tsdk.registerFunction("mem::graph-migrate-v2", async () => withKeyedLock("graph-v2-migration", async () => {
\t\tif (graphV2Active) return { success: true, skipped: true, reason: "already_active", manifest: await kv.rawGet(KV.config, GRAPH_V2_MANIFEST_KEY).catch(() => null) };
\t\tgraphV2Migrating = true;
\t\tconst startedAt = (/* @__PURE__ */ new Date()).toISOString();
\t\ttry {
\t\t\tawait kv.rawSet(KV.config, GRAPH_V2_MANIFEST_KEY, { version: 2, status: "reading_legacy", startedAt }, 6e5);
\t\t\tconst [nodes, edges] = await Promise.all([
\t\t\t\tkv.rawList(KV.graphNodes, 6e5),
\t\t\t\tkv.rawList(KV.graphEdges, 6e5)
\t\t\t]);
\t\t\tawait kv.rawSet(KV.config, GRAPH_V2_MANIFEST_KEY, { version: 2, status: "copying", startedAt, expectedNodes: nodes.length, expectedEdges: edges.length }, 6e5);
\t\t\tconst liveNodes = nodes.filter((node) => !node.stale);
\t\t\tconst liveEdges = edges.filter((edge) => !edge.stale);
\t\t\tconst degree = /* @__PURE__ */ new Map();
\t\t\tfor (const edge of liveEdges) {
\t\t\t\tdegree.set(edge.sourceNodeId, (degree.get(edge.sourceNodeId) || 0) + 1);
\t\t\t\tdegree.set(edge.targetNodeId, (degree.get(edge.targetNodeId) || 0) + 1);
\t\t\t}
\t\t\tawait mapWithConcurrency(nodes, 8, async (node) => {
\t\t\t\tawait kv.setGraphV2(KV.graphNodes, node.id, node);
\t\t\t\tawait kv.setGraphV2(KV.graphNodeDegree, node.id, degree.get(node.id) || 0);
\t\t\t});
\t\t\tawait mapWithConcurrency(liveNodes, 8, (node) => kv.setGraphV2(KV.graphNameIndex, nameIndexKey(node.type, node.name), node.id));
\t\t\tawait mapWithConcurrency(edges, 8, (edge) => kv.setGraphV2(KV.graphEdges, edge.id, edge));
\t\t\tawait mapWithConcurrency(liveEdges, 8, (edge) => kv.setGraphV2(KV.graphEdgeKey, edgeIndexKey(edge.sourceNodeId, edge.targetNodeId, edge.type), edge.id));
\t\t\tconst snapshot = buildSnapshotFromArrays(nodes, edges);
\t\t\tawait kv.setGraphV2(KV.graphSnapshot, SNAPSHOT_KEY, snapshot);
\t\t\tconst [copiedNodes, copiedEdges] = await Promise.all([kv.listGraphV2(KV.graphNodes), kv.listGraphV2(KV.graphEdges)]);
\t\t\tif (copiedNodes.length !== nodes.length || copiedEdges.length !== edges.length) throw new Error(\`graph_v2_validation_failed: expected \${nodes.length}/\${edges.length}, got \${copiedNodes.length}/\${copiedEdges.length}\`);
\t\t\tconst manifest = {
\t\t\t\tversion: 2,
\t\t\t\tstatus: "complete",
\t\t\t\tstartedAt,
\t\t\t\tcompletedAt: (/* @__PURE__ */ new Date()).toISOString(),
\t\t\t\tshards: GRAPH_V2_SHARD_COUNT,
\t\t\t\ttotalNodes: copiedNodes.filter((node) => !node.stale).length,
\t\t\t\ttotalEdges: copiedEdges.filter((edge) => !edge.stale).length,
\t\t\t\tlegacyNodes: nodes.length,
\t\t\t\tlegacyEdges: edges.length
\t\t\t};
\t\t\tawait kv.rawSet(KV.config, GRAPH_V2_MANIFEST_KEY, manifest, 6e5);
\t\t\tgraphV2Active = true;
\t\t\tlogger.info("Graph v2 migration completed", manifest);
\t\t\treturn { success: true, manifest };
\t\t} catch (err) {
\t\t\tconst outcome = { version: 2, status: "failed", startedAt, failedAt: (/* @__PURE__ */ new Date()).toISOString(), error: safeLlmErrorOutcome(err) };
\t\t\tawait kv.rawSet(KV.config, GRAPH_V2_MANIFEST_KEY, outcome, 6e5).catch(() => {});
\t\t\tlogger.error("Graph v2 migration failed", { error: err instanceof Error ? err.message : String(err) });
\t\t\treturn { success: false, error: "graph_v2_migration_failed" };
\t\t} finally {
\t\t\tgraphV2Migrating = false;
\t\t}
\t}));
}
function registerGraphFunction(sdk, kv, provider) {`,
  },
  {
    label: "graph retries LLM extraction failures",
    section: ["function registerGraphFunction", "function registerGraphImportFunction"],
    before: `\t\t\treturn {
\t\t\t\tsuccess: true,
\t\t\t\tnodesAdded: nodes.length,
\t\t\t\tedgesAdded: edges.length
\t\t\t};`,
    after: `\t\t\treturn {
\t\t\t\tsuccess: !llmError,
\t\t\t\tnodesAdded: nodes.length,
\t\t\t\tedgesAdded: edges.length,
\t\t\t\t...(llmError ? { error: "llm_graph_extraction_failed" } : {})
\t\t\t};`,
  },
  {
    label: "change-aware session LLM lifecycle",
    section: [
      `sdk.registerFunction("event::session::stopped"`,
      `sdk.registerFunction("event::session::ended"`,
    ],
    before: `sdk.registerFunction("event::session::stopped", async (data) => {
\t\tconst summary = await sdk.trigger({
\t\t\tfunction_id: "mem::summarize",
\t\t\tpayload: data
\t\t});
\t\tconst fireVoid = (function_id, payload) => sdk.trigger({
\t\t\tfunction_id,
\t\t\tpayload,
\t\t\taction: TriggerAction.Void()
\t\t}).catch((err) => logger.warn(function_id + " trigger failed", {
\t\t\tsessionId: data.sessionId,
\t\t\terror: err instanceof Error ? err.message : String(err)
\t\t}));
\t\tif (isReflectEnabled()) fireVoid("mem::slot-reflect", { sessionId: data.sessionId });
\t\ttry {
\t\t\tconst compressed = (await kv.list(KV.observations(data.sessionId))).filter((o) => o.title);
\t\t\tif (compressed.length > 0) fireVoid("mem::graph-extract", { observations: compressed });
\t\t} catch (err) {
\t\t\tlogger.warn("graph-extract trigger failed", {
\t\t\t\tsessionId: data.sessionId,
\t\t\t\terror: err instanceof Error ? err.message : String(err)
\t\t\t});
\t\t}
\t\tif (isConsolidationEnabled() && !data.skipConsolidation) {
\t\t\tif (await consolidationDue(kv)) {
\t\t\t\tfireVoid("mem::consolidate-pipeline", {
\t\t\t\t\ttier: "all",
\t\t\t\t\tforce: true
\t\t\t\t});
\t\t\t\tfireVoid("mem::auto-crystallize", { olderThanDays: 0 });
\t\t\t}
\t\t}
\t\treturn summary;
\t});
\tsdk.registerTrigger({
\t\ttype: "durable:subscriber",
\t\tfunction_id: "event::session::stopped",
\t\tconfig: { topic: "agentmemory.session.stopped" }
\t});
\t`,
    after: `sdk.registerFunction("mem::graph-extract-incremental", async (data) => {
\t\tif (process.env.GRAPH_EXTRACTION_ENABLED !== "true") return { success: true, skipped: true, reason: "graph_disabled" };
\t\tif (!data?.sessionId) return { success: false, error: "sessionId is required" };
\t\treturn withKeyedLock(\`graph-auto:\${data.sessionId}\`, async () => {
\t\t\tconst compressed = (await kv.list(KV.observations(data.sessionId))).filter((o) => o.title).sort((a, b) => {
\t\t\t\tconst at = new Date(a.timestamp || a.createdAt || 0).getTime();
\t\t\t\tconst bt = new Date(b.timestamp || b.createdAt || 0).getTime();
\t\t\t\treturn at - bt || String(a.id || "").localeCompare(String(b.id || ""));
\t\t\t});
\t\t\tif (compressed.length === 0) return { success: true, skipped: true, reason: "no_observations" };
\t\t\tconst markerKey = \`graph:auto:\${data.sessionId}\`;
\t\t\tconst marker = await kv.get(KV.config, markerKey).catch(() => null);
\t\t\tconst markedIndex = marker?.lastObservationId ? compressed.findIndex((o) => o.id === marker.lastObservationId) : -1;
\t\t\tconst start = markedIndex >= 0 ? markedIndex + 1 : Math.min(Number(marker?.processedObservationCount) || 0, compressed.length);
\t\t\tconst pending = compressed.slice(start);
\t\t\tconst configuredMin = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MIN_NEW_OBSERVATIONS || "10");
\t\t\tconst minNew = Number.isFinite(configuredMin) && configuredMin > 0 ? Math.floor(configuredMin) : 10;
\t\t\tif (pending.length === 0 || marker && pending.length < minNew) return { success: true, skipped: true, reason: "not_enough_changes", pending: pending.length };
\t\t\tconst configuredMax = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MAX_OBSERVATIONS_PER_RUN || "25");
\t\t\tconst maxPerRun = Number.isFinite(configuredMax) && configuredMax > 0 ? Math.floor(configuredMax) : 25;
\t\t\tconst batch = pending.slice(0, maxPerRun);
\t\t\tconst result = await sdk.trigger({
\t\t\t\tfunction_id: "mem::graph-extract",
\t\t\t\tpayload: { observations: batch, _llmJob: data._llmJob }
\t\t\t});
\t\t\tif (result?.success === false) return result;
\t\t\tawait kv.set(KV.config, markerKey, {
\t\t\t\tlastObservationId: batch.at(-1)?.id,
\t\t\t\tprocessedObservationCount: start + batch.length,
\t\t\t\tupdatedAt: (/* @__PURE__ */ new Date()).toISOString()
\t\t\t});
\t\t\tlogger.info("Incremental graph extraction completed", { sessionId: data.sessionId, processed: batch.length, remaining: pending.length - batch.length });
\t\t\treturn { success: true, processed: batch.length, remaining: pending.length - batch.length, result };
\t\t});
\t});
\tsdk.registerFunction("event::session::stopped", async (data) => {
\t\treturn withKeyedLock(\`session-stop:\${data.sessionId}\`, async () => {
\t\t\tlet summary = { success: true, skipped: true, reason: "auto_summary_disabled" };
\t\t\tif (process.env.AGENTMEMORY_AUTO_SUMMARIZE !== "false") summary = await enqueueLlmJob(sdk, "summary", { sessionId: data.sessionId });
\t\t\tconst fireVoid = (function_id, payload) => sdk.trigger({
\t\t\t\tfunction_id,
\t\t\t\tpayload,
\t\t\t\taction: TriggerAction.Void()
\t\t\t}).catch((err) => logger.warn(function_id + " trigger failed", {
\t\t\t\tsessionId: data.sessionId,
\t\t\t\terror: err instanceof Error ? err.message : String(err)
\t\t\t}));
\t\t\tif (isReflectEnabled()) fireVoid("mem::slot-reflect", { sessionId: data.sessionId });
\t\t\tif (process.env.GRAPH_EXTRACTION_ENABLED === "true") await enqueueLlmJob(sdk, "graph", { sessionId: data.sessionId });
\t\t\tif (isConsolidationEnabled() && !data.skipConsolidation) {
\t\t\t\tif (await consolidationDue(kv)) {
\t\t\t\t\tawait enqueueLlmJob(sdk, "consolidation", { sessionId: data.sessionId });
\t\t\t\t\tfireVoid("mem::auto-crystallize", { olderThanDays: 0 });
\t\t\t\t}
\t\t\t}
\t\t\treturn summary;
\t\t});
\t});
\tsdk.registerTrigger({
\t\ttype: "durable:subscriber",
\t\tfunction_id: "event::session::stopped",
\t\tconfig: { topic: "agentmemory.session.stopped" }
\t});
\t`,
  },
  {
    label: "activate completed graph v2 manifest",
    section: ["async function main()", "registerPrivacyFunction(sdk)"],
    before: `\tconst kv = new StateKV(sdk);
\tconst secret = getEnvVar("AGENTMEMORY_SECRET");`,
    after: `\tconst kv = new StateKV(sdk);
\tconst graphV2Manifest = await kv.rawGet(KV.config, GRAPH_V2_MANIFEST_KEY).catch(() => null);
\tgraphV2Active = isGraphV2Requested() && graphV2Manifest?.status === "complete" && graphV2Manifest?.version === 2;
\tconst secret = getEnvVar("AGENTMEMORY_SECRET");`,
  },
  {
    label: "register durable LLM functions",
    section: ["async function main()", "registerSearchFunction(sdk, kv);"],
    before: `\tregisterCompressFunction(sdk, kv, provider, metricsStore);`,
    after: `\tregisterCompressFunction(sdk, kv, provider, metricsStore);
\tregisterDurableLlmFunctions(sdk, kv);`,
  },
  {
    label: "register graph v2 migration",
    section: ["async function main()", "registerGraphImportFunction(sdk, kv);"],
    before: `\tregisterGraphFunction(sdk, kv, provider);`,
    after: `\tregisterGraphFunction(sdk, kv, provider);
\tregisterGraphV2MigrationFunction(sdk, kv);`,
  },
  {
    label: "startup migration and backlog recovery",
    section: ["async function main()", "registerMcpEndpoints(sdk, kv, secret);"],
    before: `\tregisterApiTriggers(sdk, kv, secret, metricsStore, provider);`,
    after: `\tregisterApiTriggers(sdk, kv, secret, metricsStore, provider);
\tif (process.env.AGENTMEMORY_SKIP_STARTUP_RECOVERY_ONCE === "true") logger.info("Skipped one startup LLM recovery pass by operator request");
\telse setTimeout(async () => {
\t\tawait sdk.trigger({ function_id: "mem::llm-requeue-pending", payload: { skipGraph: true }, timeoutMs: 6e5 }).catch((err) => logger.error("Automatic LLM backlog recovery failed", { error: err instanceof Error ? err.message : String(err) }));
\t\tlet migrationOk = true;
\t\tif (isGraphV2Requested() && !graphV2Active && graphV2Manifest?.status !== "failed") {
\t\t\tconst migration = await sdk.trigger({ function_id: "mem::graph-migrate-v2", payload: {}, timeoutMs: 6e5 }).catch((err) => {
\t\t\t\tlogger.error("Automatic graph v2 migration invocation failed", { error: err instanceof Error ? err.message : String(err) });
\t\t\t\treturn { success: false };
\t\t\t});
\t\t\tmigrationOk = migration?.success !== false;
\t\t}
\t\tif (migrationOk && graphV2Active) await sdk.trigger({ function_id: "mem::llm-requeue-pending", payload: { skipCompression: true, skipSummary: true }, timeoutMs: 6e5 }).catch((err) => logger.error("Automatic graph backlog recovery failed", { error: err instanceof Error ? err.message : String(err) }));
\t}, 5e3).unref();`,
  },
  {
    label: "memories list honours project filter",
    before: `let filtered = latest ? memories.filter((m) => m.isLatest) : memories;
\t\tif (filterAgentId) filtered = filtered.filter((m) => m.agentId === filterAgentId || includeOrphans && m.agentId === void 0);`,
    after: `let filtered = latest ? memories.filter((m) => m.isLatest) : memories;
\t\tif (filterAgentId) filtered = filtered.filter((m) => m.agentId === filterAgentId || includeOrphans && m.agentId === void 0);
\t\t// Upstream 0.9.29 reads no project param here at all, so ?project=<x> was
\t\t// silently ignored and every value returned the same unfiltered page.
\t\tconst rawProject = req.query_params?.["project"];
\t\tconst projectFilter = typeof rawProject === "string" && rawProject.trim().length > 0 ? rawProject.trim() : void 0;
\t\tconst includeUnprojected = req.query_params?.["includeUnprojected"] === "true";
\t\tif (projectFilter) filtered = filtered.filter((m) => m.project === projectFilter || includeUnprojected && m.project === void 0);`,
  },
  {
    label: "search compact projection includes project",
    before: `if (format === "compact") {
\t\t\tconst packed = applyTokenBudget(enriched.map((r) => ({
\t\t\t\tobsId: r.observation.id,
\t\t\t\tsessionId: r.sessionId,
\t\t\t\ttitle: r.observation.title,
\t\t\t\ttype: r.observation.type,
\t\t\t\tscore: r.score,
\t\t\t\ttimestamp: r.observation.timestamp
\t\t\t})));`,
    after: `if (format === "compact") {
\t\t\tconst packed = applyTokenBudget(enriched.map((r) => ({
\t\t\t\tobsId: r.observation.id,
\t\t\t\tsessionId: r.sessionId,
\t\t\t\ttitle: r.observation.title,
\t\t\t\ttype: r.observation.type,
\t\t\t\tscore: r.score,
\t\t\t\ttimestamp: r.observation.timestamp,
\t\t\t\tproject: r.observation.project ?? r.project ?? void 0
\t\t\t})));`,
  },
  {
    label: "memory observation view carries project",
    before: `function memoryToObservation(memory) {
	return {
		id: memory.id,
		sessionId: memory.sessionIds?.[0] ?? "memory",`,
    after: `function memoryToObservation(memory) {
	// Upstream drops project here, so a memory saved WITH a project came back out
	// of search with none: the field survives validation, persistence and the list
	// API and is lost only in this projection.
	return {
		id: memory.id,
		sessionId: memory.sessionIds?.[0] ?? "memory",
		...memory.project ? { project: memory.project } : {},`,
  },
  {
    label: "lesson observation view carries project",
    before: `function lessonToObservation(l) {
	return {
		id: l.id,
		sessionId: "lesson",`,
    after: `function lessonToObservation(l) {
	return {
		id: l.id,
		sessionId: "lesson",
		...l.project ? { project: l.project } : {},`,
  },
  {
    // Backstop so no family can overflow the model context, including paths not
    // individually bounded (graph extraction, temporal extraction, query
    // expansion all call provider.compress directly). A logged truncation beats
    // a hard 400 that a caller may swallow. Default 48000 chars is ~12k tokens:
    // 16,384 context - 2,048 output - system prompt - margin.
    label: "provider input ceiling",
    section: ["var OpenAIProvider = class", "function resolveTimeout()"],
    before: `async call(systemPrompt, userPrompt, model, maxTokens) {\n\t\tconst url = buildChatUrl(this.baseUrl, this.isAzure, this.azureApiVersion);`,
    after: `async call(systemPrompt, userPrompt, model, maxTokens) {\n\t\tconst maxInputChars = Number(process.env.AGENTMEMORY_LLM_MAX_INPUT_CHARS || "48000");\n\t\tif (Number.isFinite(maxInputChars) && maxInputChars > 0 && typeof userPrompt === "string" && userPrompt.length > maxInputChars) {\n\t\t\tconst fromChars = userPrompt.length;\n\t\t\tuserPrompt = userPrompt.slice(0, maxInputChars) + "\\n\\n[truncated: exceeded AGENTMEMORY_LLM_MAX_INPUT_CHARS]";\n\t\t\tprocess.stderr.write("[agentmemory] llm_input_clamped " + JSON.stringify({ family: llmCallContext.getStore()?.family ?? null, model, fromChars, toChars: userPrompt.length, maxInputChars }) + "\\n");\n\t\t}\n\t\tconst url = buildChatUrl(this.baseUrl, this.isAzure, this.azureApiVersion);`,
  },
  {
    // The reflect stage sent every matching fact, lesson, and untruncated
    // crystal narrative for a concept cluster. Against a growing semantic store
    // (1,435 facts and climbing) one cluster reached 106k chars / ~26.5k tokens
    // and was rejected by a 16,384-token endpoint. Bound it by relevance first
    // so the strongest material survives, rather than letting the provider
    // ceiling above cut at an arbitrary character.
    label: "bounded reflect cluster input",
    before: `function buildReflectPrompt(cluster) {\n\tconst sections = [];\n\tsections.push(\`## Concept Cluster: \${cluster.concepts.join(", ")}\`);\n\tif (cluster.facts.length > 0) sections.push("\\n## Known Facts", ...cluster.facts.map((f) => \`- [confidence=\${f.confidence}] \${f.fact}\`));\n\tif (cluster.lessons.length > 0) sections.push("\\n## Lessons Learned", ...cluster.lessons.map((l) => \`- [confidence=\${l.confidence}] \${l.content}\`));\n\tif (cluster.crystalNarratives.length > 0) sections.push("\\n## Completed Work Summaries", ...cluster.crystalNarratives.map((n) => \`- \${n}\`));\n\treturn \`Synthesize higher-order insights from this cluster of related memories:\\n\\n\${sections.join("\\n")}\`;\n}`,
    after: `function buildReflectPrompt(cluster) {\n\tconst reflectNum = (name, fallback) => {\n\t\tconst v = Number(process.env[name] || fallback);\n\t\treturn Number.isFinite(v) && v > 0 ? Math.floor(v) : fallback;\n\t};\n\tconst maxFacts = reflectNum("AGENTMEMORY_REFLECT_MAX_FACTS", 40);\n\tconst maxLessons = reflectNum("AGENTMEMORY_REFLECT_MAX_LESSONS", 20);\n\tconst maxConcepts = reflectNum("AGENTMEMORY_REFLECT_MAX_CONCEPTS", 60);\n\tconst maxCrystals = reflectNum("AGENTMEMORY_REFLECT_MAX_CRYSTALS", 5);\n\tconst maxNarrativeChars = reflectNum("AGENTMEMORY_REFLECT_MAX_NARRATIVE_CHARS", 800);\n\tconst maxPromptChars = reflectNum("AGENTMEMORY_REFLECT_MAX_PROMPT_CHARS", 40000);\n\tconst byConfidence = (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0);\n\tconst sourceCounts = {\n\t\tfacts: cluster.facts.length,\n\t\tlessons: cluster.lessons.length,\n\t\tcrystals: cluster.crystalNarratives.length\n\t};\n\tlet facts = [...cluster.facts].sort(byConfidence).slice(0, maxFacts);\n\tlet lessons = [...cluster.lessons].sort(byConfidence).slice(0, maxLessons);\n\tlet crystals = cluster.crystalNarratives.slice(0, maxCrystals).map((n) => {\n\t\tconst text = String(n ?? "");\n\t\treturn text.length > maxNarrativeChars ? text.slice(0, maxNarrativeChars) + " [truncated]" : text;\n\t});\n\tconst render = () => {\n\t\tconst conceptLabel = cluster.concepts.length > maxConcepts ? cluster.concepts.slice(0, maxConcepts).join(", ") + " (+" + (cluster.concepts.length - maxConcepts) + " more)" : cluster.concepts.join(", ");\n\t\tconst sections = ["## Concept Cluster: " + conceptLabel];\n\t\tif (facts.length > 0) sections.push("\\n## Known Facts", ...facts.map((f) => "- [confidence=" + f.confidence + "] " + f.fact));\n\t\tif (lessons.length > 0) sections.push("\\n## Lessons Learned", ...lessons.map((l) => "- [confidence=" + l.confidence + "] " + l.content));\n\t\tif (crystals.length > 0) sections.push("\\n## Completed Work Summaries", ...crystals.map((n) => "- " + n));\n\t\treturn "Synthesize higher-order insights from this cluster of related memories:\\n\\n" + sections.join("\\n");\n\t};\n\tlet prompt = render();\n\twhile (prompt.length > maxPromptChars) {\n\t\tif (crystals.length > 0) crystals = [];\n\t\telse if (facts.length > 5) facts = facts.slice(0, Math.max(5, Math.floor(facts.length * .75)));\n\t\telse if (lessons.length > 5) lessons = lessons.slice(0, Math.max(5, Math.floor(lessons.length * .75)));\n\t\telse break;\n\t\tprompt = render();\n\t}\n\tif (facts.length < sourceCounts.facts || lessons.length < sourceCounts.lessons || crystals.length < sourceCounts.crystals || cluster.concepts.length > maxConcepts) logger.info("Reflect bounded cluster input", { sourceConcepts: cluster.concepts.length, usedConcepts: Math.min(cluster.concepts.length, maxConcepts), sourceFacts: sourceCounts.facts, usedFacts: facts.length, sourceLessons: sourceCounts.lessons, usedLessons: lessons.length, sourceCrystals: sourceCounts.crystals, usedCrystals: crystals.length, promptChars: prompt.length, maxPromptChars });\n\treturn prompt;\n}`,
  },
  {
    // The reflect loop swallowed every provider error with a bare `catch {`, so
    // a context overflow surfaced only as reflect.newInsights === 0 inside an
    // otherwise successful pipeline result - no log line anywhere. Keep
    // continuing (one bad cluster must not abort the pipeline) but say so.
    label: "reflect cluster failures are logged",
    before: `totalInsights++;\n\t\t\t\t}\n\t\t\t} catch {\n\t\t\t\tcontinue;\n\t\t\t}`,
    after: `totalInsights++;\n\t\t\t\t}\n\t\t\t} catch (err) {\n\t\t\t\tlogger.warn("Reflect cluster failed", { concepts: cluster.concepts, facts: cluster.facts.length, lessons: cluster.lessons.length, crystals: cluster.crystalNarratives.length, error: err instanceof Error ? err.message : String(err) });\n\t\t\t\tcontinue;\n\t\t\t}`,
  },
];

let patchedFiles = 0;
for (const file of candidates) {
  let source = readFileSync(file, "utf8");
  if (!source.includes("var OpenAIProvider = class")) continue;
  for (const patch of patches) {
    const result = replaceInSection(source, patch, file);
    if (!result.changed) {
      throw new Error(`${patch.label}: package layout changed; no match in ${file}`);
    }
    source = result.source;
  }
  writeFileSync(file, source);
  patchedFiles += 1;
}

if (patchedFiles < 1) {
  throw new Error("No AgentMemory runtime bundle was patched");
}
process.stdout.write(`Patched ${patchedFiles} AgentMemory runtime bundle(s).\n`);
