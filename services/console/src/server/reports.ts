import type {
  ReportLlmResponse,
  ReportMemoryResponse,
  ReportProjectsResponse,
  ReportSection,
  ReportSummaryResponse,
  ReportSystemResponse,
} from "../shared/types.js";
import type { ReportQuery } from "./historyProtocol.js";

const DAY_MS = 86_400_000;

export interface ReportQueryInput {
  from?: string;
  to?: string;
  compare?: string;
  project?: string;
  agent?: string;
  functionId?: string;
}

export function parseReportQuery(section: ReportSection, input: ReportQueryInput): ReportQuery {
  const now = Date.now();
  const to = input.to === undefined ? now : Number(input.to);
  const from = input.from === undefined ? to - DAY_MS : Number(input.from);
  if (!Number.isFinite(from) || !Number.isFinite(to) || from < 0 || to <= from) {
    throw new Error("from and to must define a valid epoch-millisecond range");
  }
  if (to - from > 365 * DAY_MS) throw new Error("report ranges cannot exceed 365 days");
  const span = to - from;
  const bucketMs =
    span <= 6 * 3_600_000 ? 60_000
      : span <= DAY_MS ? 5 * 60_000
        : span <= 7 * DAY_MS ? 30 * 60_000
          : span <= 30 * DAY_MS ? 2 * 3_600_000
            : span <= 90 * DAY_MS ? 6 * 3_600_000
              : DAY_MS;
  const clean = (value: string | undefined, max: number): string | undefined => {
    const result = value?.trim();
    return result ? result.slice(0, max) : undefined;
  };
  return {
    section,
    from,
    to,
    bucketMs,
    compare: input.compare !== "false",
    project: clean(input.project, 512),
    agent: clean(input.agent, 128),
    functionId: clean(input.functionId, 128),
  };
}

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "number" ? String(value) : String(value);
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function csv(headers: string[], rows: unknown[][]): string {
  return `${headers.map(csvCell).join(",")}\r\n${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

function periodRows<T>(current: T[], previous: T[] | null): Array<{ period: string; row: T }> {
  return [
    ...current.map((row) => ({ period: "current", row })),
    ...(previous ?? []).map((row) => ({ period: "previous", row })),
  ];
}

export function reportCsv(
  section: ReportSection,
  current: ReportSummaryResponse | ReportProjectsResponse | ReportMemoryResponse | ReportLlmResponse | ReportSystemResponse,
  previous: ReportSummaryResponse | ReportProjectsResponse | ReportMemoryResponse | ReportLlmResponse | ReportSystemResponse | null,
): string {
  if (section === "summary") {
    const now = current as ReportSummaryResponse;
    const before = previous as ReportSummaryResponse | null;
    return csv(
      ["period", "timestamp_utc", "requests", "errors", "estimated_p95_ms", "raw_observations", "compressed_observations", "llm_calls", "llm_failures", "estimated_llm_cost_nanos", "billed_provider_cost_nanos", "memories_total", "sessions_total", "sampled_availability"],
      periodRows(now.series, before?.series ?? null).map(({ period, row }) => [period, new Date(row.t).toISOString(), row.requests, row.errors, row.p95Ms, row.rawObservations, row.compressedObservations, row.llmCalls, row.llmFailures, row.estimatedLlmCostNanos, row.billedProviderCostNanos, row.memoriesTotal, row.sessionsTotal, row.sampledAvailability]),
    );
  }
  if (section === "projects") {
    const now = current as ReportProjectsResponse;
    const before = previous as ReportProjectsResponse | null;
    return csv(
      ["period", "project", "requests", "errors", "error_rate", "estimated_p95_ms", "observations", "get", "post", "put", "delete", "other", "agents"],
      periodRows(now.rows, before?.rows ?? null).map(({ period, row }) => [period, row.project, row.requests, row.errors, row.errorRate, row.p95Ms, row.observations, row.methods.get, row.methods.post, row.methods.put, row.methods.delete, row.methods.other, row.agents.map((agent) => `${agent.agent}:${agent.count}`).join("; ")]),
    );
  }
  if (section === "memory") {
    const now = current as ReportMemoryResponse;
    const before = previous as ReportMemoryResponse | null;
    return csv(
      ["period", "timestamp_utc", "storage_attempts", "stored", "storage_failures", "save_reliability", "retrievals", "hits", "misses", "retrieval_failures", "unknown", "recall_delivery_rate", "context_tokens_returned", "context_blocks_returned", "automatic_retrievals", "automatic_hits", "automatic_context_tokens", "manual_retrievals", "manual_hits", "manual_context_tokens", "estimated_avoided_tokens_low", "estimated_avoided_tokens_high", "modeled_retrievals", "legacy_estimates", "capture_payload_bytes", "capture_samples", "budgeted_retrievals", "budget_tokens", "truncated_retrievals", "oversized_retrievals", "retrieval_latency_ms", "average_top_score", "result_count", "project_matches", "unscoped_results", "cross_project_results", "session_starts", "session_ends", "observations_captured", "memories_saved", "consolidations"],
      periodRows(now.series, before?.series ?? null).map(({ period, row }) => [period, new Date(row.t).toISOString(), row.storageAttempts, row.stored, row.storageFailures, row.saveReliability, row.retrievals, row.hits, row.misses, row.retrievalFailures, row.unknown, row.recallDeliveryRate, row.contextTokens, row.contextBlocks, row.automaticRetrievals, row.automaticHits, row.automaticContextTokens, row.manualRetrievals, row.manualHits, row.manualContextTokens, row.estimatedAvoidedTokensLow, row.estimatedAvoidedTokensHigh, row.modeledRetrievals, row.legacyEstimateCount, row.capturePayloadBytes, row.captureSamples, row.budgetedRetrievals, row.budgetTokens, row.truncatedRetrievals, row.oversizedRetrievals, row.retrievalLatencyMs, row.averageTopScore, row.resultCount, row.projectMatches, row.unscopedResults, row.crossProjectResults, row.sessionStarts, row.sessionEnds, row.observationsCaptured, row.memoriesSaved, row.consolidations]),
    );
  }
  if (section === "llm") {
    const now = current as ReportLlmResponse;
    const before = previous as ReportLlmResponse | null;
    const rows: unknown[][] = [];
    for (const { period, row } of periodRows(now.series, before?.series ?? null)) rows.push([period, "function", new Date(row.t).toISOString(), row.functionId, "", "", "", row.calls, row.successes, row.failures, row.avgLatencyMs, "", "", "", "", "", "", row.estimatedCostNanos, "", "", "", "", "", "", "", "", ""]);
    for (const { period, row } of periodRows(now.usageRows, before?.usageRows ?? null)) rows.push([period, "usage", "", "", row.provider, row.model, row.family, row.calls, "", "", "", row.promptTokens, row.cachedPromptTokens, row.cacheWriteTokens, row.completionTokens, row.reasoningTokens, row.totalTokens, row.estimatedCostNanos, row.pricedCalls, row.unpricedCalls, row.localCalls, row.throughputMeasuredCalls, row.throughputProviderLatencyMs, row.outputTokensPerSecond, "", "", ""]);
    for (const { period, row } of periodRows(now.providerCosts, before?.providerCosts ?? null)) rows.push([period, "provider_cost", new Date(row.t).toISOString(), "", row.provider, "", "", "", "", "", "", "", "", "", "", "", "", row.billedCostNanos, "", "", "", "", "", "", row.scopeType, row.scopeId, row.scopeLabel]);
    return csv(
      ["period", "row_type", "timestamp_utc", "function_id", "provider", "model", "family", "calls", "successes", "failures", "average_latency_ms", "prompt_tokens", "cached_prompt_tokens", "cache_write_tokens", "completion_tokens", "reasoning_tokens", "total_tokens", "cost_nanos", "priced_calls", "unpriced_calls", "local_calls", "throughput_measured_calls", "throughput_provider_latency_ms", "output_tokens_per_second", "billing_scope_type", "billing_scope_id", "billing_scope_label"],
      rows,
    );
  }
  const now = current as ReportSystemResponse;
  const before = previous as ReportSystemResponse | null;
  return csv(
    ["period", "timestamp_utc", "memories_total", "sessions_total", "sessions_active_average", "heap_average_mb", "heap_max_mb", "rss_average_mb", "rss_max_mb", "event_loop_lag_average_ms", "event_loop_lag_max_ms", "uptime_seconds", "sampled_availability"],
    periodRows(now.series, before?.series ?? null).map(({ period, row }) => [period, new Date(row.t).toISOString(), row.memoriesTotal, row.sessionsTotal, row.sessionsActiveAvg, row.heapAvgMb, row.heapMaxMb, row.rssAvgMb, row.rssMaxMb, row.lagAvgMs, row.lagMaxMs, row.uptimeSec, row.sampledAvailability]),
  );
}
