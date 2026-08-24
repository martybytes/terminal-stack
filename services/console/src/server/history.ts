import { randomUUID } from "node:crypto";
import { Worker } from "node:worker_threads";
import type {
  ContextAvoidedHistorySnapshot,
  HistoryStatus,
  LlmCallTelemetry,
  LlmCompletionEvent,
  MetricsTick,
  ObservationEvent,
  ReportMeta,
  RequestRecord,
} from "../shared/types.js";
import { config } from "./config.js";
import {
  LATENCY_BOUNDS_MS,
  blankSystemDelta,
  minuteBucket,
  type HistoryBatch,
  type HistoryCostSnapshot,
  type HistoryWorkerCommand,
  type HistoryWorkerCommandInput,
  type HistoryWorkerData,
  type HistoryWorkerResponse,
  type LlmMinuteDelta,
  type MemoryMinuteDelta,
  type LlmUsageRecord,
  type ObservationMinuteDelta,
  type ReportQuery,
  type RequestMinuteDelta,
  type SystemMinuteDelta,
  type ProviderCostDayRecord,
  type BillingScopeRecord,
  type BillingSyncStateRecord,
  type SessionFlowDelta,
} from "./historyProtocol.js";
import { memoryFlowForRequest, storedCount, storageAttempts } from "../shared/memoryFlow.js";
import { memoryEconomicsForRequest, retrievalMode } from "../shared/memoryEconomics.js";

const FLUSH_MS = 5_000;
const MAX_AGGREGATE_KEYS = 50_000;

function cleanDimension(value: string | null | undefined, fallback: string, max = 256): string {
  const clean = value?.trim();
  return clean ? clean.slice(0, max) : fallback;
}

function requestMethod(method: string): string {
  const normalized = method.toLowerCase();
  if (normalized === "get" || normalized === "post" || normalized === "delete") return normalized;
  if (normalized === "put" || normalized === "patch") return "put";
  return "other";
}

function statusClass(status: number): string {
  if (status === 0) return "network";
  if (status >= 500) return "5xx";
  if (status >= 400) return "4xx";
  if (status >= 300) return "3xx";
  return "2xx";
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

class HistoryService {
  private worker: Worker | null = null;
  private ready = false;
  private stopping = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private flushTimer: NodeJS.Timeout | null = null;
  private nextCommandId = 1;
  private readonly runId = randomUUID();
  private readonly startedAt = Date.now();
  private readonly pendingCommands = new Map<number, {
    resolve: (value: unknown) => void;
    reject: (error: Error) => void;
  }>();
  private requestRows = new Map<string, RequestMinuteDelta>();
  private memoryRows = new Map<string, MemoryMinuteDelta>();
  private sessionFlowRows = new Map<string, SessionFlowDelta>();
  private observationRows = new Map<string, ObservationMinuteDelta>();
  private llmRows = new Map<string, LlmMinuteDelta>();
  private llmUsageRows = new Map<string, LlmUsageRecord>();
  private systemRows = new Map<number, SystemMinuteDelta>();
  private readonly batches = new Map<string, HistoryBatch>();
  private draining: Promise<void> | null = null;
  private lastFlushAt: number | null = null;
  private lastError: string | null = null;

  async start(): Promise<void> {
    if (this.worker || this.stopping) return;
    await this.spawn();
    this.flushTimer = setInterval(() => void this.flush(), FLUSH_MS);
    this.flushTimer.unref();
  }

  private spawn(): Promise<void> {
    return new Promise((resolve) => {
      const source = import.meta.url.endsWith(".ts")
        ? new URL("./historyWorker.ts", import.meta.url)
        : new URL("./historyWorker.js", import.meta.url);
      const workerData: HistoryWorkerData = {
        dbPath: config.historyDbPath,
        retentionDays: config.historyRetentionDays,
        runId: this.runId,
        startedAt: this.startedAt,
      };
      const worker = new Worker(source, { workerData });
      this.worker = worker;
      let settled = false;
      const finish = (): void => {
        if (settled) return;
        settled = true;
        resolve();
      };
      const timeout = setTimeout(() => {
        this.lastError = "history worker startup timed out";
        finish();
      }, 5_000);
      timeout.unref();
      worker.on("message", (message: HistoryWorkerResponse) => {
        if (message.type === "ready") {
          clearTimeout(timeout);
          this.ready = true;
          this.lastError = null;
          finish();
          void this.drain();
          return;
        }
        const pending = this.pendingCommands.get(message.id);
        if (!pending) return;
        this.pendingCommands.delete(message.id);
        if (message.ok) pending.resolve(message.result);
        else pending.reject(new Error(message.error));
      });
      worker.on("error", (error) => {
        this.lastError = error.message;
        finish();
      });
      worker.on("exit", (code) => {
        clearTimeout(timeout);
        if (this.worker === worker) this.worker = null;
        this.ready = false;
        for (const pending of this.pendingCommands.values()) {
          pending.reject(new Error(`history worker exited (${code})`));
        }
        this.pendingCommands.clear();
        finish();
        if (!this.stopping) {
          this.lastError = `history worker exited (${code})`;
          this.restartTimer = setTimeout(() => void this.spawn(), 2_000);
          this.restartTimer.unref();
        }
      });
    });
  }

  private keyCount(): number {
    return this.requestRows.size + this.memoryRows.size + this.sessionFlowRows.size + this.observationRows.size + this.llmRows.size + this.llmUsageRows.size + this.systemRows.size;
  }

  noteRequest(request: RequestRecord): void {
    const project = cleanDimension(request.project, "Global", 512);
    const agent = cleanDimension(request.agent?.toLowerCase(), "unknown", 128);
    const method = requestMethod(request.method);
    const status = statusClass(request.status);
    const bucketMs = minuteBucket(request.ts);
    const key = `${bucketMs}\0${project}\0${agent}\0${method}\0${status}`;
    let row = this.requestRows.get(key);
    if (!row) {
      if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
        this.lastError = "history aggregate queue reached its safety limit";
        return;
      }
      row = {
        bucketMs,
        project,
        agent,
        method,
        statusClass: status,
        count: 0,
        durationTotalMs: 0,
        latencyBins: Array(LATENCY_BOUNDS_MS.length + 1).fill(0) as number[],
      };
      this.requestRows.set(key, row);
    }
    row.count++;
    const duration = Math.max(0, Number.isFinite(request.durMs) ? request.durMs : 0);
    row.durationTotalMs += duration;
    const index = LATENCY_BOUNDS_MS.findIndex((bound) => duration <= bound);
    row.latencyBins[index === -1 ? LATENCY_BOUNDS_MS.length : index]++;

    const memoryKey = `${bucketMs}\0${project}\0${agent}\0${request.lifecycle}`;
    let memoryRow = this.memoryRows.get(memoryKey);
    if (!memoryRow) {
      if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
        this.lastError = "history aggregate queue reached its safety limit";
        return;
      }
      memoryRow = {
        bucketMs, project, agent, stage: request.lifecycle, requestCount: 0,
        retrievals: 0, hits: 0, misses: 0, unknown: 0,
        contextTokens: 0, contextBlocks: 0, unscopedResults: 0, crossProjectResults: 0,
        storageAttempts: 0, stored: 0, storageFailures: 0, retrievalFailures: 0, resultCount: 0, projectMatches: 0,
        automaticRetrievals: 0, automaticHits: 0, automaticContextTokens: 0,
        manualRetrievals: 0, manualHits: 0, manualContextTokens: 0,
        capturePayloadBytes: 0, captureSamples: 0,
        estimatedAvoidedTokensLow: 0, estimatedAvoidedTokensHigh: 0,
        modeledRetrievals: 0, legacyEstimateCount: 0, budgetedRetrievals: 0,
        budgetTokens: 0, truncatedRetrievals: 0, oversizedRetrievals: 0,
        retrievalLatencyTotalMs: 0, scoredRetrievals: 0, topScoreTotal: 0,
      };
      this.memoryRows.set(memoryKey, memoryRow);
    }
    memoryRow.requestCount++;
    if (request.lifecycle === "session_start" || request.lifecycle === "context_recall" || request.lifecycle === "file_enrichment" || request.lifecycle === "manual_search") {
      memoryRow.retrievals++;
      if (request.outcome?.kind === "returned") memoryRow.hits++;
      else if (request.outcome?.kind === "empty") memoryRow.misses++;
      else if (request.outcome?.kind === "failed") memoryRow.retrievalFailures++;
      else memoryRow.unknown++;
    }
    const flow = memoryFlowForRequest(request);
    memoryRow.storageAttempts += storageAttempts(flow);
    memoryRow.stored += storedCount(flow);
    memoryRow.storageFailures += flow.storageFailures;
    memoryRow.resultCount += flow.resultCount;
    memoryRow.projectMatches += flow.projectMatches;
    memoryRow.contextTokens += request.outcome?.contextTokens ?? 0;
    memoryRow.contextBlocks += request.outcome?.contextBlocks ?? 0;
    memoryRow.unscopedResults += request.outcome?.unscopedResultCount ?? 0;
    memoryRow.crossProjectResults += request.outcome?.crossProjectResultCount ?? 0;
    const economics = memoryEconomicsForRequest(request);
    memoryRow.automaticRetrievals += economics.automaticAttempts;
    memoryRow.automaticHits += economics.automaticHits;
    memoryRow.automaticContextTokens += economics.automaticContextTokens;
    memoryRow.manualRetrievals += economics.manualAttempts;
    memoryRow.manualHits += economics.manualHits;
    memoryRow.manualContextTokens += economics.manualContextTokens;
    memoryRow.capturePayloadBytes += economics.capturePayloadBytes;
    memoryRow.captureSamples += economics.captureSamples;
    memoryRow.estimatedAvoidedTokensLow += economics.estimatedAvoidedTokensLow;
    memoryRow.estimatedAvoidedTokensHigh += economics.estimatedAvoidedTokensHigh;
    memoryRow.modeledRetrievals += economics.modeledRetrievals;
    memoryRow.legacyEstimateCount += economics.legacyEstimateCount;
    memoryRow.budgetedRetrievals += economics.budgetedRetrievals;
    memoryRow.budgetTokens += economics.budgetTokens;
    memoryRow.truncatedRetrievals += economics.truncatedRetrievals;
    memoryRow.oversizedRetrievals += economics.oversizedRetrievals;
    memoryRow.retrievalLatencyTotalMs += economics.retrievalLatencyTotalMs;
    memoryRow.scoredRetrievals += economics.scoredRetrievals;
    memoryRow.topScoreTotal += economics.topScoreTotal;

    if (request.sessionId) {
      const sessionKey = request.sessionId.slice(0, 512);
      let session = this.sessionFlowRows.get(sessionKey);
      if (!session) {
        session = {
          sessionId: sessionKey, project, agent, firstAt: request.ts, lastAt: request.ts,
          starts: 0, ends: 0, automaticRetrievals: 0, automaticHits: 0,
          automaticContextTokens: 0, manualRetrievals: 0, manualHits: 0, manualContextTokens: 0,
        };
        this.sessionFlowRows.set(sessionKey, session);
      }
      session.firstAt = Math.min(session.firstAt, request.ts);
      session.lastAt = Math.max(session.lastAt, request.ts);
      if (session.project === "Global" && project !== "Global") session.project = project;
      if (session.agent === "unknown" && agent !== "unknown") session.agent = agent;
      if (request.lifecycle === "session_start") session.starts++;
      if (request.lifecycle === "session_end") session.ends++;
      const mode = retrievalMode(request.lifecycle);
      if (mode === "automatic") {
        session.automaticRetrievals++;
        if (request.outcome?.kind === "returned") session.automaticHits++;
        session.automaticContextTokens += request.outcome?.contextTokens ?? 0;
      } else if (mode === "manual") {
        session.manualRetrievals++;
        if (request.outcome?.kind === "returned") session.manualHits++;
        session.manualContextTokens += request.outcome?.contextTokens ?? 0;
      }
    }
  }

  noteObservation(event: ObservationEvent, project: string | null): void {
    const bucketMs = minuteBucket(event.ts);
    const scopedProject = cleanDimension(project, "Global", 512);
    const agent = cleanDimension(event.agent?.toLowerCase(), "unknown", 128);
    const observationType = cleanDimension(event.type, "unknown", 128);
    const key = `${bucketMs}\0${scopedProject}\0${agent}\0${event.kind}\0${observationType}`;
    let row = this.observationRows.get(key);
    if (!row) {
      if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
        this.lastError = "history aggregate queue reached its safety limit";
        return;
      }
      row = {
        bucketMs,
        project: scopedProject,
        agent,
        kind: event.kind,
        observationType,
        count: 0,
      };
      this.observationRows.set(key, row);
    }
    row.count++;
  }

  noteLlm(event: LlmCompletionEvent): void {
    const bucketMs = minuteBucket(event.ts);
    const functionId = cleanDimension(event.functionId, "unknown", 128);
    const key = `${bucketMs}\0${functionId}`;
    let row = this.llmRows.get(key);
    if (!row) {
      if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
        this.lastError = "history aggregate queue reached its safety limit";
        return;
      }
      row = { bucketMs, functionId, calls: 0, successes: 0, failures: 0, latencyTotalMs: 0 };
      this.llmRows.set(key, row);
    }
    row.calls += Math.max(0, event.calls);
    row.successes += Math.max(0, event.successes);
    row.failures += Math.max(0, event.failures);
    row.latencyTotalMs += Math.max(0, event.avgLatencyMs) * Math.max(0, event.calls);
  }

  noteLlmCall(call: LlmCallTelemetry, sourceInstanceId: string): void {
    if (call.status !== "completed" || call.completedAt === null) return;
    const callKey = `${cleanDimension(sourceInstanceId, "unknown", 128)}:${call.id}`;
    if (this.llmUsageRows.has(callKey)) return;
    if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
      this.lastError = "history aggregate queue reached its safety limit";
      return;
    }
    const throughputMeasured = call.outcome === "success" && call.completionTokens !== null &&
      call.completionTokens >= 0 && call.providerLatencyMs !== null && call.providerLatencyMs > 0;
    this.llmUsageRows.set(callKey, {
      callKey,
      completedAt: call.completedAt,
      bucketMs: minuteBucket(call.completedAt),
      provider: cleanDimension(call.provider.toLowerCase(), "unknown", 64),
      model: cleanDimension(call.model, "unknown", 128),
      family: cleanDimension(call.family, "other", 64),
      promptTokens: Math.max(0, call.promptTokens ?? 0),
      cachedPromptTokens: Math.max(0, call.cachedPromptTokens ?? 0),
      cacheWriteTokens: Math.max(0, call.cacheWriteTokens ?? 0),
      completionTokens: Math.max(0, call.completionTokens ?? 0),
      reasoningTokens: Math.max(0, call.reasoningTokens ?? 0),
      totalTokens: Math.max(0, call.totalTokens ?? 0),
      estimatedCostNanos: call.estimatedCostNanos ?? 0,
      pricedCalls: call.costCoverage === "priced" ? 1 : 0,
      unpricedCalls: call.costCoverage === "unpriced" ? 1 : 0,
      throughputMeasuredCalls: throughputMeasured ? 1 : 0,
      throughputCompletionTokens: throughputMeasured ? call.completionTokens ?? 0 : 0,
      throughputProviderLatencyMs: throughputMeasured ? call.providerLatencyMs ?? 0 : 0,
    });
  }

  noteMetrics(tick: MetricsTick): void {
    const bucketMs = minuteBucket(tick.ts);
    let row = this.systemRows.get(bucketMs);
    if (!row) {
      if (this.keyCount() >= MAX_AGGREGATE_KEYS) {
        this.lastError = "history aggregate queue reached its safety limit";
        return;
      }
      row = blankSystemDelta(tick);
      this.systemRows.set(bucketMs, row);
    }
    row.samples++;
    if (tick.upstreamOk) row.upstreamOkSamples++;
    const memories = finite(tick.memoriesTotal);
    if (memories !== null) { row.memoriesFirst ??= memories; row.memoriesLast = memories; }
    const sessions = finite(tick.sessionsTotal);
    if (sessions !== null) { row.sessionsFirst ??= sessions; row.sessionsLast = sessions; }
    const active = finite(tick.sessionsActive);
    if (active !== null) {
      row.sessionsActiveSum += active;
      row.sessionsActiveCount++;
      row.sessionsActiveMax = Math.max(row.sessionsActiveMax ?? active, active);
    }
    const heap = finite(tick.health?.heapMb);
    if (heap !== null) { row.heapSumMb += heap; row.heapCount++; row.heapMaxMb = Math.max(row.heapMaxMb ?? heap, heap); }
    const rss = finite(tick.health?.rssMb);
    if (rss !== null) { row.rssSumMb += rss; row.rssCount++; row.rssMaxMb = Math.max(row.rssMaxMb ?? rss, rss); }
    const lag = finite(tick.health?.lagMs);
    if (lag !== null) { row.lagSumMs += lag; row.lagCount++; row.lagMaxMs = Math.max(row.lagMaxMs ?? lag, lag); }
    row.uptimeLastSec = finite(tick.health?.uptimeSec) ?? row.uptimeLastSec;
  }

  private snapshotBatch(): void {
    if (this.keyCount() === 0) return;
    const batch: HistoryBatch = {
      id: randomUUID(),
      createdAt: Date.now(),
      requests: [...this.requestRows.values()],
      memory: [...this.memoryRows.values()],
      sessionFlows: [...this.sessionFlowRows.values()],
      observations: [...this.observationRows.values()],
      llm: [...this.llmRows.values()],
      llmUsage: [...this.llmUsageRows.values()],
      system: [...this.systemRows.values()],
    };
    this.requestRows = new Map();
    this.memoryRows = new Map();
    this.sessionFlowRows = new Map();
    this.observationRows = new Map();
    this.llmRows = new Map();
    this.llmUsageRows = new Map();
    this.systemRows = new Map();
    this.batches.set(batch.id, batch);
  }

  async flush(): Promise<void> {
    this.snapshotBatch();
    await this.drain();
  }

  private async drain(): Promise<void> {
    if (this.draining) return this.draining;
    this.draining = (async () => {
      if (!this.ready) return;
      for (const [id, batch] of this.batches) {
        try {
          await this.call({ type: "ingest", batch });
          this.batches.delete(id);
          this.lastFlushAt = Date.now();
          this.lastError = null;
        } catch (error) {
          this.lastError = error instanceof Error ? error.message : String(error);
          break;
        }
      }
    })().finally(() => { this.draining = null; });
    return this.draining;
  }

  private call(command: HistoryWorkerCommandInput): Promise<unknown> {
    if (!this.worker || !this.ready) return Promise.reject(new Error("history database unavailable"));
    const id = this.nextCommandId++;
    return new Promise((resolve, reject) => {
      this.pendingCommands.set(id, { resolve, reject });
      this.worker!.postMessage({ ...command, id } as HistoryWorkerCommand);
    });
  }

  status(): HistoryStatus {
    return {
      ok: this.ready && this.lastError === null,
      writable: this.ready,
      lastFlushAt: this.lastFlushAt,
      lastError: this.lastError,
      pendingBatches: this.batches.size + (this.keyCount() > 0 ? 1 : 0),
    };
  }

  async meta(): Promise<ReportMeta> {
    await this.flush();
    const meta = await this.call({ type: "meta" }) as ReportMeta;
    return { ...meta, status: this.status() };
  }

  async report<T>(query: ReportQuery): Promise<T> {
    await this.flush();
    return await this.call({ type: "report", query }) as T;
  }

  async contextAvoidedHistory(now = Date.now()): Promise<ContextAvoidedHistorySnapshot> {
    await this.flush();
    return await this.call({ type: "context-avoided-history", now }) as ContextAvoidedHistorySnapshot;
  }

  async costSnapshot(now = Date.now()): Promise<HistoryCostSnapshot> {
    await this.flush();
    return await this.call({ type: "cost-snapshot", now }) as HistoryCostSnapshot;
  }

  async recordProviderCosts(rows: ProviderCostDayRecord[]): Promise<void> {
    if (rows.length === 0) return;
    await this.call({ type: "provider-costs", rows });
  }

  async setBillingScope(scope: BillingScopeRecord): Promise<void> {
    await this.call({ type: "billing-scope", scope });
  }

  async billingState(scope: BillingScopeRecord): Promise<BillingSyncStateRecord | null> {
    return await this.call({ type: "billing-state-get", scope }) as BillingSyncStateRecord | null;
  }

  async setBillingState(state: BillingSyncStateRecord): Promise<void> {
    await this.call({ type: "billing-state-set", state });
  }

  async shutdown(): Promise<void> {
    if (this.stopping) return;
    this.stopping = true;
    if (this.flushTimer) clearInterval(this.flushTimer);
    if (this.restartTimer) clearTimeout(this.restartTimer);
    await this.flush().catch(() => undefined);
    if (this.worker && this.ready) {
      await this.call({ type: "shutdown", endedAt: Date.now() }).catch(() => undefined);
    }
    await this.worker?.terminate().catch(() => undefined);
    this.worker = null;
    this.ready = false;
  }
}

export const history = new HistoryService();
