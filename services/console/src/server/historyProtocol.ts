import type { MetricsTick, ReportSection } from "../shared/types.js";

export const REPORT_MINUTE_MS = 60_000;
export const LATENCY_BOUNDS_MS = [
  10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000,
  120_000,
] as const;

export interface RequestMinuteDelta {
  bucketMs: number;
  project: string;
  agent: string;
  method: string;
  statusClass: string;
  count: number;
  durationTotalMs: number;
  latencyBins: number[];
}

export interface MemoryMinuteDelta {
  bucketMs: number;
  project: string;
  agent: string;
  stage: string;
  requestCount: number;
  retrievals: number;
  hits: number;
  misses: number;
  unknown: number;
  contextTokens: number;
  contextBlocks: number;
  unscopedResults: number;
  crossProjectResults: number;
  storageAttempts: number;
  stored: number;
  storageFailures: number;
  retrievalFailures: number;
  resultCount: number;
  projectMatches: number;
  automaticRetrievals: number;
  automaticHits: number;
  automaticContextTokens: number;
  manualRetrievals: number;
  manualHits: number;
  manualContextTokens: number;
  capturePayloadBytes: number;
  captureSamples: number;
  estimatedAvoidedTokensLow: number;
  estimatedAvoidedTokensHigh: number;
  modeledRetrievals: number;
  legacyEstimateCount: number;
  budgetedRetrievals: number;
  budgetTokens: number;
  truncatedRetrievals: number;
  oversizedRetrievals: number;
  retrievalLatencyTotalMs: number;
  scoredRetrievals: number;
  topScoreTotal: number;
}

export interface SessionFlowDelta {
  sessionId: string;
  project: string;
  agent: string;
  firstAt: number;
  lastAt: number;
  starts: number;
  ends: number;
  automaticRetrievals: number;
  automaticHits: number;
  automaticContextTokens: number;
  manualRetrievals: number;
  manualHits: number;
  manualContextTokens: number;
}

export interface ObservationMinuteDelta {
  bucketMs: number;
  project: string;
  agent: string;
  kind: string;
  observationType: string;
  count: number;
}

export interface LlmMinuteDelta {
  bucketMs: number;
  functionId: string;
  calls: number;
  successes: number;
  failures: number;
  latencyTotalMs: number;
}

export interface LlmUsageRecord {
  callKey: string;
  completedAt: number;
  bucketMs: number;
  provider: string;
  model: string;
  family: string;
  promptTokens: number;
  cachedPromptTokens: number;
  cacheWriteTokens: number;
  completionTokens: number;
  reasoningTokens: number;
  totalTokens: number;
  estimatedCostNanos: number;
  pricedCalls: number;
  unpricedCalls: number;
  throughputMeasuredCalls?: number;
  throughputCompletionTokens?: number;
  throughputProviderLatencyMs?: number;
}

export interface ProviderCostDayRecord {
  dayMs: number;
  provider: string;
  scopeType: "project" | "api_key";
  scopeId: string;
  scopeLabel: string;
  amountNanos: number;
  currency: string;
  syncedAt: number;
  source: string;
}

export interface BillingScopeRecord {
  provider: string;
  scopeType: "project";
  scopeId: string;
  scopeLabel: string;
}

export interface BillingSyncStateRecord extends BillingScopeRecord {
  lastAttemptAt: number | null;
  lastSuccessAt: number | null;
  nextAllowedAt: number | null;
  lastError: string | null;
  backfillComplete: boolean;
}

export interface HistoryCostSnapshot {
  estimatedTodayNanos: number;
  billedMonthToDateNanos: number | null;
}

export interface SystemMinuteDelta {
  bucketMs: number;
  samples: number;
  upstreamOkSamples: number;
  memoriesFirst: number | null;
  memoriesLast: number | null;
  sessionsFirst: number | null;
  sessionsLast: number | null;
  sessionsActiveSum: number;
  sessionsActiveCount: number;
  sessionsActiveMax: number | null;
  heapSumMb: number;
  heapCount: number;
  heapMaxMb: number | null;
  rssSumMb: number;
  rssCount: number;
  rssMaxMb: number | null;
  lagSumMs: number;
  lagCount: number;
  lagMaxMs: number | null;
  uptimeLastSec: number | null;
}

export interface HistoryBatch {
  id: string;
  createdAt: number;
  requests: RequestMinuteDelta[];
  memory: MemoryMinuteDelta[];
  sessionFlows?: SessionFlowDelta[];
  observations: ObservationMinuteDelta[];
  llm: LlmMinuteDelta[];
  llmUsage: LlmUsageRecord[];
  system: SystemMinuteDelta[];
}

export interface ReportQuery {
  section: ReportSection;
  from: number;
  to: number;
  bucketMs: number;
  compare: boolean;
  project?: string;
  agent?: string;
  functionId?: string;
}

export type HistoryWorkerCommand =
  | { id: number; type: "ingest"; batch: HistoryBatch }
  | { id: number; type: "meta" }
  | { id: number; type: "context-avoided-history"; now: number }
  | { id: number; type: "report"; query: ReportQuery }
  | { id: number; type: "cost-snapshot"; now: number }
  | { id: number; type: "provider-costs"; rows: ProviderCostDayRecord[] }
  | { id: number; type: "billing-scope"; scope: BillingScopeRecord }
  | { id: number; type: "billing-state-get"; scope: BillingScopeRecord }
  | { id: number; type: "billing-state-set"; state: BillingSyncStateRecord }
  | { id: number; type: "shutdown"; endedAt: number };

export type HistoryWorkerCommandInput =
  | { type: "ingest"; batch: HistoryBatch }
  | { type: "meta" }
  | { type: "context-avoided-history"; now: number }
  | { type: "report"; query: ReportQuery }
  | { type: "cost-snapshot"; now: number }
  | { type: "provider-costs"; rows: ProviderCostDayRecord[] }
  | { type: "billing-scope"; scope: BillingScopeRecord }
  | { type: "billing-state-get"; scope: BillingScopeRecord }
  | { type: "billing-state-set"; state: BillingSyncStateRecord }
  | { type: "shutdown"; endedAt: number };

export type HistoryWorkerResponse =
  | { type: "ready" }
  | { type: "response"; id: number; ok: true; result: unknown }
  | { type: "response"; id: number; ok: false; error: string };

export interface HistoryWorkerData {
  dbPath: string;
  retentionDays: number;
  runId: string;
  startedAt: number;
}

export function minuteBucket(ts: number): number {
  return Math.floor(ts / REPORT_MINUTE_MS) * REPORT_MINUTE_MS;
}

export function blankSystemDelta(tick: MetricsTick): SystemMinuteDelta {
  const health = tick.health;
  return {
    bucketMs: minuteBucket(tick.ts),
    samples: 0,
    upstreamOkSamples: 0,
    memoriesFirst: null,
    memoriesLast: null,
    sessionsFirst: null,
    sessionsLast: null,
    sessionsActiveSum: 0,
    sessionsActiveCount: 0,
    sessionsActiveMax: null,
    heapSumMb: 0,
    heapCount: 0,
    heapMaxMb: health?.heapMb ?? null,
    rssSumMb: 0,
    rssCount: 0,
    rssMaxMb: health?.rssMb ?? null,
    lagSumMs: 0,
    lagCount: 0,
    lagMaxMs: health?.lagMs ?? null,
    uptimeLastSec: health?.uptimeSec ?? null,
  };
}
