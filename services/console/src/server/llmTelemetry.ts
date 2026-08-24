// Safe LLM observability for the console. Polls AgentMemory's authenticated
// health/config endpoints, derives rolling completion deltas, and exposes only
// provider metadata explicitly mirrored into this process. Keys, prompts, and
// responses never enter the snapshot.

import type {
  LlmCallFamily,
  LlmCallTelemetry,
  LlmCircuitBreaker,
  LlmCompletionEvent,
  LlmFeatureFlag,
  LlmJobTelemetry,
  LlmQueueTelemetry,
  LlmSafeConfig,
  LlmSnapshot,
} from "../shared/types.js";
import { config } from "./config.js";
import { openAiKeyHints } from "./keyHints.js";
import {
  LLM_WINDOW_MS,
  LlmActivityTracker,
  type UpstreamFunctionMetric,
} from "./llmActivity.js";
import { upstreamJson } from "./upstream.js";
import { estimateLlmCall, PRICING_CATALOG_EFFECTIVE } from "./llmCost.js";
import { billing } from "./billing.js";
import { assessLlmEndpoint, isActiveLocalLlmCall } from "../shared/llmEndpoint.js";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function string(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function family(value: unknown): LlmCallFamily {
  return value === "compression" ||
    value === "summary" ||
    value === "graph" ||
    value === "consolidation"
    ? value
    : "other";
}

function parseCalls(payload: unknown): LlmCallTelemetry[] {
  const rows = asRecord(payload)?.calls;
  if (!Array.isArray(rows)) return [];
  const calls: LlmCallTelemetry[] = [];
  for (const value of rows) {
    const row = asRecord(value);
    const id = number(row?.id);
    const startedAt = number(row?.startedAt);
    if (id <= 0 || startedAt <= 0) continue;
    const provider = string(row?.provider)?.toLowerCase() ??
      (config.llmProvider.toLowerCase().includes("openai") ? "openai" : config.llmProvider.toLowerCase());
    const base = {
      id,
      jobId: string(row?.jobId),
      family: family(row?.family),
      status: row?.status === "running" ? "running" : "completed",
      outcome: string(row?.outcome),
      model: string(row?.model),
      promptChars: number(row?.promptChars),
      estimatedPromptTokens: number(row?.estimatedPromptTokens),
      promptTokens: nullableNumber(row?.promptTokens),
      cachedPromptTokens: nullableNumber(row?.cachedPromptTokens),
      cacheWriteTokens: nullableNumber(row?.cacheWriteTokens),
      completionTokens: nullableNumber(row?.completionTokens),
      reasoningTokens: nullableNumber(row?.reasoningTokens),
      totalTokens: nullableNumber(row?.totalTokens),
      provider,
      project: string(row?.project),
      sessionId: string(row?.sessionId),
      queuedAt: nullableNumber(row?.queuedAt),
      startedAt,
      completedAt: nullableNumber(row?.completedAt),
      queueWaitMs: number(row?.queueWaitMs),
      providerGateWaitMs: number(row?.providerGateWaitMs),
      providerLatencyMs: nullableNumber(row?.providerLatencyMs),
    } satisfies Omit<LlmCallTelemetry, "estimatedCostNanos" | "costCoverage">;
    const localCall = isActiveLocalLlmCall(endpointAssessment, config.llmModel, base.model);
    const effective = localCall
      ? { ...base, provider: config.llmProvider.trim().toLowerCase() || "local" }
      : base;
    const estimate = localCall ? { nanos: 0, coverage: "local" as const } : estimateLlmCall(effective);
    calls.push({ ...effective, estimatedCostNanos: estimate.nanos, costCoverage: estimate.coverage });
  }
  return calls.sort((a, b) => b.id - a.id);
}

function parseJobs(payload: unknown): LlmJobTelemetry[] {
  const rows = asRecord(payload)?.jobs;
  if (!Array.isArray(rows)) return [];
  const jobs: LlmJobTelemetry[] = [];
  for (const value of rows) {
    const row = asRecord(value);
    const id = string(row?.id);
    const queuedAt = number(row?.queuedAt);
    if (!id || queuedAt <= 0) continue;
    const rawStatus = string(row?.status);
    const status =
      rawStatus === "queued" || rawStatus === "running" || rawStatus === "failed"
        ? rawStatus
        : "completed";
    jobs.push({
      id,
      family: family(row?.family),
      status,
      attempt: Math.max(0, Math.floor(number(row?.attempt))),
      queuedAt,
      startedAt: nullableNumber(row?.startedAt),
      completedAt: nullableNumber(row?.completedAt),
      outcome: string(row?.outcome),
      project: string(row?.project),
      sessionId: string(row?.sessionId),
    });
  }
  return jobs;
}

function parseQueue(payload: unknown): LlmQueueTelemetry | null {
  const root = asRecord(payload);
  const queue = asRecord(root?.queue);
  const name = string(root?.queueName);
  if (!queue || !name) return null;
  return {
    name,
    depth: number(queue.depth),
    consumers: number(queue.consumer_count ?? queue.consumerCount),
    dlqDepth: number(queue.dlq_depth ?? queue.dlqDepth),
    activeJobs: number(root?.activeJobs),
  };
}

function parseMetrics(payload: unknown): UpstreamFunctionMetric[] {
  const rows = asRecord(payload)?.functionMetrics;
  if (!Array.isArray(rows)) return [];
  const metrics: UpstreamFunctionMetric[] = [];
  for (const row of rows) {
    const metric = asRecord(row);
    const functionId = string(metric?.functionId);
    if (!functionId) continue;
    metrics.push({
      functionId,
      totalCalls: number(metric?.totalCalls),
      successCount: number(metric?.successCount),
      failureCount: number(metric?.failureCount),
      avgLatencyMs: number(metric?.avgLatencyMs),
      avgQualityScore: number(metric?.avgQualityScore),
    });
  }
  return metrics;
}

function parseCircuit(payload: unknown): LlmCircuitBreaker {
  const raw = asRecord(asRecord(payload)?.circuitBreaker);
  const state = string(raw?.state);
  return {
    state:
      state === "closed" || state === "half-open" || state === "open" ? state : "unknown",
    failures: Math.floor(number(raw?.failures)),
    lastFailureAt: nullableNumber(raw?.lastFailureAt),
    openedAt: nullableNumber(raw?.openedAt),
  };
}

function parseFeatures(payload: unknown): LlmFeatureFlag[] {
  const rows = asRecord(payload)?.flags;
  if (!Array.isArray(rows)) return [];
  const flags: LlmFeatureFlag[] = [];
  for (const row of rows) {
    const flag = asRecord(row);
    const key = string(flag?.key);
    const label = string(flag?.label);
    if (!key || !label) continue;
    flags.push({
      key,
      label,
      enabled: flag?.enabled === true,
      default: flag?.default === true,
      needsLlm: flag?.needsLlm === true,
      description: string(flag?.description) ?? "",
      affects: Array.isArray(flag?.affects)
        ? flag.affects.filter((value): value is string => typeof value === "string")
        : [],
    });
  }
  return flags;
}

const endpointAssessment = assessLlmEndpoint(config.llmProvider, config.llmEndpoint, config.llmModel);
const relevantKeyHints = () => endpointAssessment.costApplicability === "local"
  ? []
  : openAiKeyHints().filter((hint) =>
      hint.configured && (hint.purpose === "inference" ? endpointAssessment.inferenceActive : true),
    );

const safeConfig: LlmSafeConfig = {
  provider: config.llmProvider,
  endpointLabel: config.llmEndpointLabel,
  model: config.llmModel,
  endpoint: config.llmEndpoint,
  timeoutMs: config.llmTimeoutMs,
  maxTokens: config.llmMaxTokens,
  summarizeConcurrency: config.llmSummarizeConcurrency,
  providerConcurrency: config.llmProviderConcurrency,
  recoveryBatchSize: config.llmRecoveryBatchSize,
  graphBatchSize: config.llmGraphBatchSize,
  embeddingProvider: config.embeddingProvider,
  keyHints: relevantKeyHints(),
  ...endpointAssessment,
};

const tracker = new LlmActivityTracker();
const subscribers: Array<(event: LlmCompletionEvent) => void> = [];
const callSubscribers: Array<(call: LlmCallTelemetry, sourceInstanceId: string) => void> = [];
const notifiedCalls = new Set<string>();
let latest: LlmSnapshot = {
  ts: Date.now(),
  sourceInstanceId: null,
  windowMs: LLM_WINDOW_MS,
  upstreamOk: false,
  version: null,
  config: safeConfig,
  circuitBreaker: { state: "unknown", failures: 0, lastFailureAt: null, openedAt: null },
  functions: tracker.summaries(),
  features: [],
  calls: [],
  jobs: [],
  queue: null,
  cost: {
    currency: "USD",
    estimatedTodayNanos: 0,
    estimatedWindowNanos: 0,
    pricedCallsToday: 0,
    unpricedCallsToday: 0,
    billedMonthToDateNanos: null,
    billedThrough: null,
    billingStatus: "setup_required",
    billingDetail: "Add a file-mounted OpenAI Admin API key and the dedicated OpenAI project ID.",
    billingScope: null,
    lastBillingAttemptAt: null,
    lastBillingSuccessAt: null,
    nextBillingSyncAllowedAt: null,
    lastBillingSyncAt: null,
    pricingCatalogEffective: PRICING_CATALOG_EFFECTIVE,
  },
};
let polling = false;
let started = false;
let lastFlagsAt = 0;
let cachedFeatures: LlmFeatureFlag[] = [];
let cachedVersion: string | null = null;
let cachedProviderKind: string | null = null;
let cachedEmbeddingProvider: string | null = null;

async function poll(): Promise<void> {
  if (polling) return;
  polling = true;
  try {
    const now = Date.now();
    const shouldRefreshFlags = cachedFeatures.length === 0 || now - lastFlagsAt >= 60_000;
    const [health, flagsPayload, exactTelemetry] = await Promise.all([
      upstreamJson<unknown>("/agentmemory/health"),
      shouldRefreshFlags
        ? upstreamJson<unknown>("/agentmemory/config/flags")
        : Promise.resolve(null),
      upstreamJson<unknown>("/agentmemory/llm/telemetry?limit=500"),
    ]);

    if (flagsPayload) {
      cachedFeatures = parseFeatures(flagsPayload);
      const flagsRoot = asRecord(flagsPayload);
      cachedVersion = string(flagsRoot?.version) ?? cachedVersion;
      cachedProviderKind = string(flagsRoot?.provider) ?? cachedProviderKind;
      cachedEmbeddingProvider = string(flagsRoot?.embeddingProvider) ?? cachedEmbeddingProvider;
      lastFlagsAt = now;
    }

    if (health) {
      for (const event of tracker.ingest(parseMetrics(health), now)) {
        for (const subscriber of subscribers) {
          try {
            subscriber(event);
          } catch {
            // A viewer subscriber cannot interrupt telemetry polling.
          }
        }
      }
      const healthRoot = asRecord(health);
      cachedVersion = string(healthRoot?.version) ?? cachedVersion;
      const exactRoot = asRecord(exactTelemetry);
      const sourceInstanceId = string(exactRoot?.instanceId) ?? latest.sourceInstanceId;
      const calls = exactTelemetry ? parseCalls(exactTelemetry) : latest.calls;
      if (sourceInstanceId) for (const call of calls) {
        if (call.status !== "completed" || call.completedAt === null) continue;
        const key = `${sourceInstanceId}:${call.id}`;
        if (notifiedCalls.has(key)) continue;
        notifiedCalls.add(key);
        for (const subscriber of callSubscribers) {
          try { subscriber(call, sourceInstanceId); } catch { /* observers are isolated */ }
        }
      }
      while (notifiedCalls.size > 5_000) notifiedCalls.delete(notifiedCalls.values().next().value!);
      const today = Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), new Date(now).getUTCDate());
      const todayCalls = calls.filter((call) => call.completedAt !== null && call.completedAt >= today);
      const windowCalls = calls.filter((call) => call.completedAt !== null && call.completedAt >= now - LLM_WINDOW_MS);
      const estimateTotal = (rows: LlmCallTelemetry[]): number => rows.reduce((sum, call) => sum + (call.estimatedCostNanos ?? 0), 0);
      latest = {
        ts: now,
        sourceInstanceId,
        windowMs: LLM_WINDOW_MS,
        upstreamOk: true,
        version: cachedVersion,
        config: {
          ...safeConfig,
          keyHints: relevantKeyHints(),
          provider:
            safeConfig.provider === "configured LLM" && cachedProviderKind === "noop"
              ? "No LLM provider"
              : safeConfig.provider,
          embeddingProvider: safeConfig.embeddingProvider ?? cachedEmbeddingProvider,
        },
        circuitBreaker: parseCircuit(health),
        functions: tracker.summaries(now),
        features: cachedFeatures,
        calls,
        jobs: exactTelemetry ? parseJobs(exactTelemetry) : latest.jobs,
        queue: exactTelemetry ? parseQueue(exactTelemetry) : latest.queue,
        cost: {
          ...billing.snapshot(),
          estimatedTodayNanos: estimateTotal(todayCalls),
          estimatedWindowNanos: estimateTotal(windowCalls),
          pricedCallsToday: todayCalls.filter((call) => call.costCoverage === "priced").length,
          unpricedCallsToday: todayCalls.filter((call) => call.costCoverage === "unpriced").length,
        },
      };
    } else {
      latest = {
        ...latest,
        ts: now,
        upstreamOk: false,
        functions: tracker.summaries(now),
      };
    }
  } finally {
    polling = false;
  }
}

export const llmTelemetry: {
  start(): void;
  snapshot(): LlmSnapshot;
  subscribe(fn: (event: LlmCompletionEvent) => void): void;
  subscribeCalls(fn: (call: LlmCallTelemetry, sourceInstanceId: string) => void): void;
} = {
  start() {
    if (started) return;
    started = true;
    void poll();
    setInterval(() => void poll(), config.llmPollMs);
  },

  snapshot() {
    return latest;
  },

  subscribe(fn) {
    subscribers.push(fn);
  },

  subscribeCalls(fn) {
    callSubscribers.push(fn);
  },
};
