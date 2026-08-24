// Shared contracts between the server and the web UI.
// Server modules and web pages both import from here — change with care.

export const KNOWN_AGENTS = ["claude", "codex", "cursor"] as const;
export type KnownAgent = (typeof KNOWN_AGENTS)[number];

export interface RequestRecord {
  id: number; // monotonically increasing capture id
  ts: number; // epoch ms
  method: string;
  path: string; // full path including query string
  route: string; // normalized route: ids and query stripped
  operation: string | null; // bounded MCP tool name when present; never request content
  project: string | null; // exact request metadata/session attribution; null when unscoped
  sessionId: string | null; // exact lifecycle correlation id; never prompt or memory content
  agent: string | null; // tagged client/session attribution; null for legacy or untagged traffic
  lifecycle: import("./memoryLifecycle.js").MemoryLifecycleStage;
  requestedTokenBudget: number | null; // bounded request scalar only; never prompt or query text
  outcome: MemoryRequestOutcome | null;
  status: number; // 0 = upstream unreachable (proxy emitted 502)
  durMs: number;
  reqBytes: number; // -1 when unknown (chunked)
  resBytes: number; // -1 when unknown (chunked)
}

export type MemoryOutcomeKind = "returned" | "empty" | "stored" | "accepted" | "failed" | "unknown";

export interface MemoryRequestOutcome {
  kind: MemoryOutcomeKind;
  resultCount: number | null;
  contextBlocks: number | null;
  contextTokens: number | null;
  contextChars: number | null;
  topScore: number | null;
  projectMatchCount: number | null;
  unscopedResultCount: number | null;
  crossProjectResultCount: number | null;
  returnedProject: string | null;
  truncated: boolean | null;
  reportedTokenBudget: number | null;
  estimatedAvoidedTokensLow: number | null;
  estimatedAvoidedTokensHigh: number | null;
  estimateConfidence: MemoryEstimateConfidence | null;
}

export type MemoryEstimateConfidence = "live" | "legacy_low" | "insufficient";
export type MemoryRetrievalMode = "automatic" | "manual" | "none";

export interface MemoryEconomicsCounts {
  automaticAttempts: number;
  automaticHits: number;
  automaticMisses: number;
  automaticFailures: number;
  automaticUnknown: number;
  automaticContextTokens: number;
  automaticContextBlocks: number;
  manualAttempts: number;
  manualHits: number;
  manualMisses: number;
  manualFailures: number;
  manualUnknown: number;
  manualContextTokens: number;
  manualContextBlocks: number;
  capturePayloadBytes: number;
  captureSamples: number;
  corpusObservations: number;
  estimatedAvoidedTokensLow: number;
  estimatedAvoidedTokensHigh: number;
  modeledRetrievals: number;
  liveEstimateCount: number;
  legacyEstimateCount: number;
  budgetedRetrievals: number;
  budgetTokens: number;
  truncatedRetrievals: number;
  oversizedRetrievals: number;
  retrievalLatencyTotalMs: number;
  scoredRetrievals: number;
  topScoreTotal: number;
}

export interface MemoryQualityCounts {
  total: number;
  scoped: number;
  conceptTagged: number;
  sourceLinked: number;
  active: number;
  superseded: number;
}

export interface DerivedWorkCounts {
  queued: number;
  running: number;
  failed: number;
  oldestWaitMs: number | null;
}

export interface RollupBucket {
  t: number; // bucket start, epoch ms
  count: number;
  ok: number; // 2xx/3xx
  err4: number; // 4xx
  err5: number; // 5xx and status 0
  p50: number; // ms
  p95: number; // ms
}

export type DepState = "ok" | "warn" | "down" | "unknown";

export interface DepStatus {
  id: string;
  label: string;
  state: DepState;
  detail?: string;
}

export interface HealthSample {
  ts: number;
  heapMb: number | null;
  rssMb: number | null;
  lagMs: number | null;
  uptimeSec: number | null;
}

export interface ObservationEvent {
  ts: number;
  kind: "raw" | "compressed";
  sessionId: string | null;
  agent: string | null;
  type: string | null; // tool_call / file_edit / message / summary / ...
  title: string | null;
  excerpt: string | null;
  importance: number | null;
}

export interface MetricsTick {
  ts: number;
  reqPerMin: number;
  errLast15m: number;
  p50: number;
  p95: number;
  memoriesTotal: number | null;
  sessionsTotal: number | null;
  sessionsActive: number | null;
  obsToday: number | null;
  health: HealthSample | null;
  deps: DepStatus[];
  upstreamOk: boolean;
}

export interface ObsBucket {
  t: number;
  raw: number;
  compressed: number;
}

export interface DashboardSnapshot {
  tick: MetricsTick | null;
  requests: RequestRecord[]; // most recent first, capped
  buckets5s: RollupBucket[]; // last 15 minutes
  buckets1m: RollupBucket[]; // last 24 hours
  obsBuckets1m: ObsBucket[]; // last 24 hours
  healthSeries: HealthSample[]; // last 24 hours of /health samples
}

export const PROJECT_METHODS = ["get", "post", "put", "delete", "other"] as const;
export type ProjectMethod = (typeof PROJECT_METHODS)[number];

export const PROJECT_AGENTS = [...KNOWN_AGENTS, "unknown"] as const;
export type ProjectAgent = (typeof PROJECT_AGENTS)[number];

export type ProjectMethodCounts = Record<ProjectMethod, number>;
export type ProjectAgentCounts = Record<ProjectAgent, number>;

export interface MemoryFlowCounts {
  observationAttempts: number;
  observationStored: number;
  explicitMemoryAttempts: number;
  explicitMemoriesStored: number;
  storageFailures: number;
  storageUnknown: number;
  retrievalAttempts: number;
  retrievalHits: number;
  retrievalMisses: number;
  retrievalFailures: number;
  retrievalUnknown: number;
  contextTokens: number;
  contextBlocks: number;
  resultCount: number;
  projectMatches: number;
  unscopedResults: number;
  crossProjectResults: number;
}

export interface ProjectActivityBucket {
  t: number; // one-minute bucket start, epoch ms
  methods: ProjectMethodCounts;
  memory: MemoryFlowCounts;
  economics: MemoryEconomicsCounts;
}

export interface ProjectSummary {
  project: string;
  lastActivityAt: number | null; // latest request completion or session activity
  lastRequestAt: number | null;
  lastAgent: ProjectAgent | null; // most recent session agent, used when the window is idle
  requestCount: number;
  requestsPerMinute: number;
  errorCount: number;
  p95Ms: number;
  methods: ProjectMethodCounts;
  intents: import("./requestIntent.js").RequestIntentCounts;
  lifecycle: import("./memoryLifecycle.js").MemoryLifecycleCounts;
  retrievals: number;
  retrievalHits: number;
  retrievalMisses: number;
  contextTokens: number;
  contextBlocks: number;
  unscopedResults: number;
  crossProjectResults: number;
  agents: ProjectAgentCounts;
  memory: MemoryFlowCounts;
  economics: MemoryEconomicsCounts;
  quality: MemoryQualityCounts;
  derivedWork: DerivedWorkCounts;
  longTermMemories: number | null;
  buckets: ProjectActivityBucket[]; // oldest first, exactly 15 one-minute buckets
}

export interface MemoryEffectivenessWarning {
  id: string;
  severity: "info" | "warn" | "bad";
  title: string;
  detail: string;
}

export interface MemoryEffectivenessSnapshot {
  ts: number;
  windowMs: number;
  lifecycle: import("./memoryLifecycle.js").MemoryLifecycleCounts;
  retrievals: number;
  retrievalHits: number;
  retrievalMisses: number;
  retrievalUnknown: number;
  hitRate: number | null;
  contextTokens: number;
  contextBlocks: number;
  contextChars: number;
  projectAttributedRequests: number;
  projectCoverageRate: number | null;
  unscopedResults: number;
  crossProjectResults: number;
  storedMemories: number | null;
  scopedMemories: number | null;
  unscopedMemories: number | null;
  memoryProjectCoverageRate: number | null;
  semanticFacts: number | null;
  graphNodes: number | null;
  graphEdges: number | null;
  graphUpdatedAt: number | null;
  featureFlags: Array<{ key: string; label: string; enabled: boolean }>;
  economics: MemoryEconomicsCounts;
  quality: MemoryQualityCounts;
  sessionStartsAssisted: number;
  sessionStartsEmpty: number;
  sessionCloseouts: number;
  warnings: MemoryEffectivenessWarning[];
  memory: MemoryFlowCounts;
  buckets: Array<{ t: number; memory: MemoryFlowCounts; economics: MemoryEconomicsCounts }>;
}

export interface ProjectsSnapshot {
  ts: number;
  windowMs: number;
  latestRequestId: number;
  projects: ProjectSummary[];
}

export interface ProjectFlowEvent {
  id: number;
  ts: number;
  project: string;
  direction: "in" | "out";
  tone: "ok" | "warn" | "bad";
}

export type LlmCircuitState = "closed" | "half-open" | "open" | "unknown";

export interface LlmCircuitBreaker {
  state: LlmCircuitState;
  failures: number;
  lastFailureAt: number | null;
  openedAt: number | null;
}

export interface LlmCallBucket {
  t: number;
  calls: number;
  successes: number;
  failures: number;
  avgLatencyMs: number;
}

export interface LlmFunctionSummary {
  functionId: string;
  label: string;
  description: string;
  totalCalls: number;
  successCount: number;
  failureCount: number;
  avgLatencyMs: number;
  avgQualityScore: number;
  recentCalls: number;
  recentSuccesses: number;
  recentFailures: number;
  recentAvgLatencyMs: number;
  lastCompletedAt: number | null;
  buckets: LlmCallBucket[];
}

export interface LlmFeatureFlag {
  key: string;
  label: string;
  enabled: boolean;
  default: boolean;
  needsLlm: boolean;
  description: string;
  affects: string[];
}

export interface LlmSafeConfig {
  provider: string;
  endpointLabel: string | null;
  model: string | null;
  endpoint: string | null;
  timeoutMs: number | null;
  maxTokens: number | null;
  summarizeConcurrency: number | null;
  providerConcurrency: number | null;
  recoveryBatchSize: number | null;
  graphBatchSize: number | null;
  embeddingProvider: string | null;
  keyHints: LlmKeyHint[];
  costApplicability: import("./llmEndpoint.js").LlmCostApplicability;
  costReason: string;
  inferenceActive: boolean;
}

export interface LlmKeyHint {
  purpose: "inference" | "billing_admin";
  label: string;
  masked: string | null;
  configured: boolean;
  source: "file" | "safe_hint" | "unavailable";
}

export type LlmCallFamily = "compression" | "summary" | "graph" | "consolidation" | "other";

export interface LlmCallTelemetry {
  id: number;
  jobId: string | null;
  family: LlmCallFamily;
  status: "running" | "completed";
  outcome: string | null;
  model: string | null;
  promptChars: number;
  estimatedPromptTokens: number;
  promptTokens: number | null;
  cachedPromptTokens: number | null;
  cacheWriteTokens: number | null;
  completionTokens: number | null;
  reasoningTokens: number | null;
  totalTokens: number | null;
  provider: string;
  project: string | null;
  sessionId: string | null;
  estimatedCostNanos: number | null;
  costCoverage: "priced" | "local" | "unpriced";
  queuedAt: number | null;
  startedAt: number;
  completedAt: number | null;
  queueWaitMs: number;
  providerGateWaitMs: number;
  providerLatencyMs: number | null;
}

export interface LlmJobTelemetry {
  id: string;
  family: LlmCallFamily;
  status: "queued" | "running" | "completed" | "failed";
  attempt: number;
  queuedAt: number;
  startedAt: number | null;
  completedAt: number | null;
  outcome: string | null;
  project: string | null;
  sessionId: string | null;
}

export interface BillingStatusSnapshot {
  currency: "USD";
  billedMonthToDateNanos: number | null;
  billedThrough: number | null;
  billingStatus: "ready" | "syncing" | "setup_required" | "error";
  billingDetail: string;
  billingScope: { type: "project"; id: string; name: string | null } | null;
  lastBillingAttemptAt: number | null;
  lastBillingSuccessAt: number | null;
  nextBillingSyncAllowedAt: number | null;
  /** Compatibility alias for lastBillingSuccessAt. */
  lastBillingSyncAt: number | null;
  pricingCatalogEffective: string;
}

export interface LlmCostSnapshot extends BillingStatusSnapshot {
  estimatedTodayNanos: number;
  estimatedWindowNanos: number;
  pricedCallsToday: number;
  unpricedCallsToday: number;
}

export interface LlmQueueTelemetry {
  name: string;
  depth: number;
  consumers: number;
  dlqDepth: number;
  activeJobs: number;
}

export interface LlmSnapshot {
  ts: number;
  sourceInstanceId: string | null;
  windowMs: number;
  upstreamOk: boolean;
  version: string | null;
  config: LlmSafeConfig;
  circuitBreaker: LlmCircuitBreaker;
  functions: LlmFunctionSummary[];
  features: LlmFeatureFlag[];
  calls: LlmCallTelemetry[];
  jobs: LlmJobTelemetry[];
  queue: LlmQueueTelemetry | null;
  cost: LlmCostSnapshot;
}

export interface LlmCompletionEvent {
  id: number;
  ts: number;
  functionId: string;
  calls: number;
  successes: number;
  failures: number;
  avgLatencyMs: number;
}

// Historical reporting contracts. Ranges are [from, to): inclusive start,
// exclusive end. The server chooses bucketMs so chart payloads stay bounded.
export type ReportSection = "summary" | "projects" | "memory" | "llm" | "system";

export interface HistoryStatus {
  ok: boolean;
  writable: boolean;
  lastFlushAt: number | null;
  lastError: string | null;
  pendingBatches: number;
}

export interface ReportMeta {
  status: HistoryStatus;
  earliestTs: number | null;
  latestTs: number | null;
  retentionDays: number;
  projects: string[];
  agents: string[];
  llmFunctions: string[];
  llmModels: string[];
  llmFamilies: string[];
}

export interface ReportRange {
  from: number;
  to: number;
  bucketMs: number;
}

export interface ReportSummaryTotals {
  requests: number;
  errors: number;
  errorRate: number;
  requestsPerMinute: number;
  p95Ms: number;
  observations: number;
  rawObservations: number;
  compressedObservations: number;
  llmCalls: number;
  llmFailures: number;
  pricedLlmCalls: number;
  unpricedLlmCalls: number;
  localLlmCalls: number;
  memoriesEnd: number | null;
  memoriesChange: number | null;
  sessionsEnd: number | null;
  sessionsChange: number | null;
  sampledAvailability: number | null;
  estimatedLlmCostNanos: number;
  billedProviderCostNanos: number | null;
}

export interface ReportSummaryPoint {
  t: number;
  requests: number;
  errors: number;
  p95Ms: number;
  rawObservations: number;
  compressedObservations: number;
  llmCalls: number;
  llmFailures: number;
  memoriesTotal: number | null;
  sessionsTotal: number | null;
  sampledAvailability: number | null;
  estimatedLlmCostNanos: number;
  billedProviderCostNanos: number | null;
}

export interface ReportSummaryResponse {
  range: ReportRange;
  current: ReportSummaryTotals;
  previous: ReportSummaryTotals | null;
  series: ReportSummaryPoint[];
}

export interface ReportProjectRow {
  project: string;
  requests: number;
  previousRequests: number | null;
  errors: number;
  errorRate: number;
  p95Ms: number;
  observations: number;
  methods: ProjectMethodCounts;
  agents: Array<{ agent: string; count: number }>;
}

export interface ReportProjectPoint {
  t: number;
  requests: number;
  errors: number;
}

export interface ReportProjectsResponse {
  range: ReportRange;
  rows: ReportProjectRow[];
  series: ReportProjectPoint[];
}

export interface ReportMemoryTotals {
  retrievals: number;
  hits: number;
  misses: number;
  unknown: number;
  hitRate: number | null;
  contextTokens: number;
  contextBlocks: number;
  unscopedResults: number;
  crossProjectResults: number;
  sessionStarts: number;
  sessionEnds: number;
  observationsCaptured: number;
  memoriesSaved: number;
  consolidations: number;
  storageAttempts: number;
  stored: number;
  storageFailures: number;
  retrievalFailures: number;
  resultCount: number;
  projectMatches: number;
  saveReliability: number | null;
  recallDeliveryRate: number | null;
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
  retrievalLatencyMs: number | null;
  averageTopScore: number | null;
  uniqueSessionsStarted: number;
  sessionsAssisted: number;
  sessionsClosed: number;
}

export interface ReportMemoryPoint extends ReportMemoryTotals {
  t: number;
}

export interface ReportMemoryProjectRow extends ReportMemoryTotals {
  project: string;
}

export interface ReportMemoryResponse {
  range: ReportRange;
  current: ReportMemoryTotals;
  previous: ReportMemoryTotals | null;
  series: ReportMemoryPoint[];
  projects: ReportMemoryProjectRow[];
}

export interface ContextAvoidedHistoryWindow {
  from: number;
  to: number;
  estimatedAvoidedTokensLow: number;
  estimatedAvoidedTokensHigh: number;
  modeledRetrievals: number;
  legacyEstimateCount: number;
}

export interface ContextAvoidedHistorySnapshot {
  generatedAt: number;
  trackingSince: number | null;
  past24Hours: ContextAvoidedHistoryWindow;
  past7Days: ContextAvoidedHistoryWindow;
  allTracked: ContextAvoidedHistoryWindow;
}

export interface ReportLlmRow {
  functionId: string;
  calls: number;
  previousCalls: number | null;
  successes: number;
  failures: number;
  successRate: number;
  avgLatencyMs: number;
  estimatedCostNanos: number;
}

export interface ReportLlmPoint {
  t: number;
  functionId: string;
  calls: number;
  successes: number;
  failures: number;
  avgLatencyMs: number;
  estimatedCostNanos: number;
}

export interface ReportLlmUsageRow {
  provider: string;
  model: string;
  family: string;
  calls: number;
  promptTokens: number;
  cachedPromptTokens: number;
  cacheWriteTokens: number;
  completionTokens: number;
  reasoningTokens: number;
  totalTokens: number;
  estimatedCostNanos: number;
  pricedCalls: number;
  unpricedCalls: number;
  localCalls: number;
  throughputMeasuredCalls: number;
  throughputCompletionTokens: number;
  throughputProviderLatencyMs: number;
  outputTokensPerSecond: number | null;
}

export interface ReportProviderCostPoint {
  t: number;
  provider: string;
  scopeType: "project" | "api_key";
  scopeId: string;
  scopeLabel: string;
  billedCostNanos: number;
  currency: string;
}

export interface ReportLlmResponse {
  range: ReportRange;
  rows: ReportLlmRow[];
  series: ReportLlmPoint[];
  usageRows: ReportLlmUsageRow[];
  providerCosts: ReportProviderCostPoint[];
  estimatedCostNanos: number;
  billedCostNanos: number | null;
}

export interface OperationScope {
  project?: string;
  allProjects?: boolean;
}

export interface OperationPreview {
  success: boolean;
  dryRun: boolean;
  scope?: string;
  project?: string | null;
  sessions: number;
  observations?: number;
  compressedObservations?: number;
  rawObservations?: number;
  queuedCompression?: number;
  projectedSummaryJobs?: number;
  projectedGraphJobs?: number;
  queuedJobs?: number;
  projectedCostNanos?: number;
  scanErrors: number;
  hasMore?: boolean;
  jobs?: string[];
  confirmationToken?: string;
  confirmationExpiresAt?: number;
}

export interface OperationsSnapshot {
  ts: number;
  upstreamOk: boolean;
  projects: string[];
  sessions: SessionSummary[];
  activeJobs: LlmJobTelemetry[];
  queue: LlmQueueTelemetry | null;
  billing: BillingStatusSnapshot;
  costApplicability: import("./llmEndpoint.js").LlmCostApplicability;
  costReason: string;
}

export interface ReportSystemPoint {
  t: number;
  memoriesTotal: number | null;
  sessionsTotal: number | null;
  sessionsActiveAvg: number | null;
  heapAvgMb: number | null;
  heapMaxMb: number | null;
  rssAvgMb: number | null;
  rssMaxMb: number | null;
  lagAvgMs: number | null;
  lagMaxMs: number | null;
  uptimeSec: number | null;
  sampledAvailability: number | null;
}

export interface ReportSystemResponse {
  range: ReportRange;
  series: ReportSystemPoint[];
  restartCount: number;
  previousRestartCount: number | null;
}

export type WsServerMessage =
  | { type: "snapshot"; ts: number; data: DashboardSnapshot }
  | { type: "request"; ts: number; data: RequestRecord }
  | { type: "observation"; ts: number; data: ObservationEvent }
  | { type: "metrics"; ts: number; data: MetricsTick }
  | { type: "project-flow"; ts: number; data: ProjectFlowEvent }
  | { type: "llm-completion"; ts: number; data: LlmCompletionEvent }
  | {
      type: "upstream";
      ts: number;
      data: { ok: boolean; wsConnected: boolean; sinceTs: number };
    };

export interface TimelineItem {
  id: string;
  ts: number | null;
  sessionId: string;
  agent: string | null;
  type: string | null;
  title: string | null;
  content: string | null;
  importance: number | null;
}

export interface TimelinePage {
  total: number; // total AFTER filters, before paging
  page: number; // 0-based
  size: number;
  sort: "newest" | "oldest";
  items: TimelineItem[];
  types: string[]; // distinct types present in the session, for filter chips
}

export interface SessionSummary {
  id: string;
  project: string | null;
  agent: string | null;
  startedAt: number | null;
  lastActiveAt: number | null;
  observationCount: number | null;
  active: boolean;
  lifecycle: import("./memoryLifecycle.js").MemoryLifecycleCounts;
  retrievals: number;
  retrievalHits: number;
  contextTokens: number;
  contextBlocks: number;
  automaticRetrievals: number;
  automaticHits: number;
  automaticContextTokens: number;
  manualRetrievals: number;
  manualHits: number;
  manualContextTokens: number;
  startContextTokens: number;
  startContextDelivered: boolean;
  closeoutObserved: boolean;
  lifecycleFirstAt: number | null;
  lifecycleLastAt: number | null;
}

export interface MemoryItem {
  id: string;
  recordKind: "memory" | "observation";
  agent: string | null;
  type: string | null;
  title: string | null;
  content: string | null;
  score: number | null; // search relevance when searching, else null
  tags: string[];
  createdAt: number | null;
  updatedAt: number | null;
  project: string | null;
  files: string[];
  sessionIds: string[];
  sourceObservationIds: string[];
  strength: number | null;
  version: number | null;
  supersedes: string[];
  isLatest: boolean;
}

export interface MemoriesPage {
  total: number;
  page: number; // 0-based
  size: number;
  items: MemoryItem[];
  searchMode: "hybrid" | "list";
  projects: string[];
  scopedTotal: number;
  unscopedTotal: number;
  rejectedResults: number;
}
