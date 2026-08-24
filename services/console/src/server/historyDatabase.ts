import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { createHash, randomBytes } from "node:crypto";
import type {
  ContextAvoidedHistorySnapshot,
  ContextAvoidedHistoryWindow,
  ProjectMethodCounts,
  ReportLlmPoint,
  ReportLlmResponse,
  ReportLlmRow,
  ReportLlmUsageRow,
  ReportProviderCostPoint,
  ReportMeta,
  ReportMemoryPoint,
  ReportMemoryProjectRow,
  ReportMemoryResponse,
  ReportMemoryTotals,
  ReportProjectPoint,
  ReportProjectRow,
  ReportProjectsResponse,
  ReportSummaryPoint,
  ReportSummaryResponse,
  ReportSummaryTotals,
  ReportSystemPoint,
  ReportSystemResponse,
} from "../shared/types.js";
import {
  LATENCY_BOUNDS_MS,
  type BillingScopeRecord,
  type BillingSyncStateRecord,
  type HistoryBatch,
  type HistoryCostSnapshot,
  type ReportQuery,
} from "./historyProtocol.js";

const HIST_COLUMNS = [
  "lat_10", "lat_25", "lat_50", "lat_100", "lat_250", "lat_500", "lat_1000",
  "lat_2500", "lat_5000", "lat_10000", "lat_30000", "lat_60000", "lat_120000",
  "lat_inf",
] as const;

type DbRow = Record<string, unknown>;

function n(row: DbRow | undefined, key: string): number {
  const value = row?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullable(row: DbRow | undefined, key: string): number | null {
  const value = row?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function s(row: DbRow, key: string): string {
  return typeof row[key] === "string" ? row[key] : "";
}

function histogramSelect(): string {
  return HIST_COLUMNS.map((column) => `SUM(${column}) AS ${column}`).join(", ");
}

function percentile95(row: DbRow | undefined): number {
  if (!row) return 0;
  const counts = HIST_COLUMNS.map((column) => n(row, column));
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (total <= 0) return 0;
  const target = Math.ceil(total * 0.95);
  let cumulative = 0;
  for (let i = 0; i < counts.length; i++) {
    cumulative += counts[i];
    if (cumulative >= target) {
      return i < LATENCY_BOUNDS_MS.length
        ? LATENCY_BOUNDS_MS[i]
        : LATENCY_BOUNDS_MS[LATENCY_BOUNDS_MS.length - 1];
    }
  }
  return 0;
}

function safeRate(numerator: number, denominator: number): number {
  return denominator > 0 ? numerator / denominator : 0;
}

function methodCounts(): ProjectMethodCounts {
  return { get: 0, post: 0, put: 0, delete: 0, other: 0 };
}

function durationMinutes(from: number, to: number): number {
  return Math.max(1, (to - from) / 60_000);
}

function functionFamily(functionId: string): string {
  const value = functionId.toLowerCase();
  if (value.includes("compress")) return "compression";
  if (value.includes("summar")) return "summary";
  if (value.includes("graph")) return "graph";
  if (value.includes("consolidat") || value.includes("reflect")) return "consolidation";
  return "other";
}

export class HistoryDatabase {
  private readonly db: DatabaseSync;
  private readonly retentionMs: number;
  private readonly runId: string;
  private readonly sessionSalt: string;

  constructor(path: string, retentionDays: number, runId: string, startedAt: number) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new DatabaseSync(path);
    this.retentionMs = retentionDays * 86_400_000;
    this.runId = runId;
    this.db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;");
    this.migrate();
    const saltRow = this.db.prepare("SELECT value FROM history_meta WHERE key='session_salt'").get() as DbRow | undefined;
    const existingSalt = typeof saltRow?.value === "string" ? saltRow.value : "";
    this.sessionSalt = existingSalt || randomBytes(32).toString("hex");
    if (!existingSalt) this.db.prepare("INSERT INTO history_meta(key,value) VALUES('session_salt',?)").run(this.sessionSalt);
    this.db.prepare("INSERT OR IGNORE INTO console_runs(run_id, started_at) VALUES (?, ?)").run(runId, startedAt);
    this.prune(Date.now());
  }

  private migrate(): void {
    const version = Number((this.db.prepare("PRAGMA user_version").get() as DbRow | undefined)?.user_version ?? 0);
    if (version > 7) throw new Error(`history schema ${version} is newer than this console supports`);
    if (version === 0) this.db.exec(`
      BEGIN IMMEDIATE;
      CREATE TABLE request_minute (
        bucket_ms INTEGER NOT NULL, project TEXT NOT NULL, agent TEXT NOT NULL,
        method TEXT NOT NULL, status_class TEXT NOT NULL,
        request_count INTEGER NOT NULL, duration_total_ms REAL NOT NULL,
        lat_10 INTEGER NOT NULL, lat_25 INTEGER NOT NULL, lat_50 INTEGER NOT NULL,
        lat_100 INTEGER NOT NULL, lat_250 INTEGER NOT NULL, lat_500 INTEGER NOT NULL,
        lat_1000 INTEGER NOT NULL, lat_2500 INTEGER NOT NULL, lat_5000 INTEGER NOT NULL,
        lat_10000 INTEGER NOT NULL, lat_30000 INTEGER NOT NULL, lat_60000 INTEGER NOT NULL,
        lat_120000 INTEGER NOT NULL, lat_inf INTEGER NOT NULL,
        PRIMARY KEY (bucket_ms, project, agent, method, status_class)
      ) WITHOUT ROWID;
      CREATE INDEX request_minute_project_time ON request_minute(project, bucket_ms);
      CREATE INDEX request_minute_agent_time ON request_minute(agent, bucket_ms);
      CREATE TABLE observation_minute (
        bucket_ms INTEGER NOT NULL, project TEXT NOT NULL, agent TEXT NOT NULL,
        kind TEXT NOT NULL, observation_type TEXT NOT NULL, observation_count INTEGER NOT NULL,
        PRIMARY KEY (bucket_ms, project, agent, kind, observation_type)
      ) WITHOUT ROWID;
      CREATE INDEX observation_minute_project_time ON observation_minute(project, bucket_ms);
      CREATE TABLE llm_minute (
        bucket_ms INTEGER NOT NULL, function_id TEXT NOT NULL,
        calls INTEGER NOT NULL, successes INTEGER NOT NULL, failures INTEGER NOT NULL,
        latency_total_ms REAL NOT NULL,
        PRIMARY KEY (bucket_ms, function_id)
      ) WITHOUT ROWID;
      CREATE TABLE system_minute (
        bucket_ms INTEGER PRIMARY KEY, samples INTEGER NOT NULL, upstream_ok_samples INTEGER NOT NULL,
        memories_first INTEGER, memories_last INTEGER, sessions_first INTEGER, sessions_last INTEGER,
        sessions_active_sum REAL NOT NULL, sessions_active_count INTEGER NOT NULL, sessions_active_max INTEGER,
        heap_sum_mb REAL NOT NULL, heap_count INTEGER NOT NULL, heap_max_mb REAL,
        rss_sum_mb REAL NOT NULL, rss_count INTEGER NOT NULL, rss_max_mb REAL,
        lag_sum_ms REAL NOT NULL, lag_count INTEGER NOT NULL, lag_max_ms REAL,
        uptime_last_sec REAL
      );
      CREATE TABLE console_runs (
        run_id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, ended_at INTEGER
      ) WITHOUT ROWID;
      CREATE INDEX console_runs_started_at ON console_runs(started_at);
      CREATE TABLE applied_batches (
        batch_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL
      ) WITHOUT ROWID;
      PRAGMA user_version=1;
      COMMIT;
    `);
    if (version < 2) this.db.exec(`
      BEGIN IMMEDIATE;
      CREATE TABLE llm_usage_minute (
        bucket_ms INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, family TEXT NOT NULL,
        calls INTEGER NOT NULL, prompt_tokens INTEGER NOT NULL, cached_prompt_tokens INTEGER NOT NULL,
        cache_write_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
        reasoning_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
        estimated_cost_nanos INTEGER NOT NULL, priced_calls INTEGER NOT NULL, unpriced_calls INTEGER NOT NULL,
        PRIMARY KEY (bucket_ms, provider, model, family)
      ) WITHOUT ROWID;
      CREATE INDEX llm_usage_minute_model_time ON llm_usage_minute(model, bucket_ms);
      CREATE INDEX llm_usage_minute_family_time ON llm_usage_minute(family, bucket_ms);
      CREATE TABLE processed_llm_calls (
        call_key TEXT PRIMARY KEY, completed_at INTEGER NOT NULL
      ) WITHOUT ROWID;
      CREATE INDEX processed_llm_calls_completed ON processed_llm_calls(completed_at);
      CREATE TABLE provider_cost_day (
        day_ms INTEGER NOT NULL, provider TEXT NOT NULL, api_key_id TEXT NOT NULL,
        amount_nanos INTEGER NOT NULL, currency TEXT NOT NULL, synced_at INTEGER NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY (day_ms, provider, api_key_id)
      ) WITHOUT ROWID;
      CREATE TABLE billing_sync_state (
        provider TEXT PRIMARY KEY, last_sync_at INTEGER, last_success_at INTEGER, last_error TEXT
      ) WITHOUT ROWID;
      PRAGMA user_version=2;
      COMMIT;
    `);
    if (version < 3) this.db.exec(`
      BEGIN IMMEDIATE;
      CREATE TABLE provider_cost_day_v3 (
        day_ms INTEGER NOT NULL, provider TEXT NOT NULL,
        scope_type TEXT NOT NULL CHECK(scope_type IN ('project','api_key')),
        scope_id TEXT NOT NULL, scope_label TEXT NOT NULL,
        amount_nanos INTEGER NOT NULL, currency TEXT NOT NULL, synced_at INTEGER NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY (day_ms, provider, scope_type, scope_id)
      ) WITHOUT ROWID;
      INSERT INTO provider_cost_day_v3
        SELECT day_ms,provider,'api_key',api_key_id,'',amount_nanos,currency,synced_at,source
        FROM provider_cost_day;
      DROP TABLE provider_cost_day;
      ALTER TABLE provider_cost_day_v3 RENAME TO provider_cost_day;
      CREATE INDEX provider_cost_scope_time ON provider_cost_day(provider,scope_type,scope_id,day_ms);
      DROP TABLE billing_sync_state;
      CREATE TABLE billing_sync_state (
        provider TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, scope_label TEXT NOT NULL,
        last_attempt_at INTEGER, last_success_at INTEGER, next_allowed_at INTEGER, last_error TEXT,
        backfill_complete INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (provider,scope_type,scope_id)
      ) WITHOUT ROWID;
      CREATE TABLE billing_active_scope (
        provider TEXT PRIMARY KEY, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
        scope_label TEXT NOT NULL, updated_at INTEGER NOT NULL
      ) WITHOUT ROWID;
      PRAGMA user_version=3;
      COMMIT;
    `);
    if (version < 4) this.db.exec(`
      BEGIN IMMEDIATE;
      CREATE TABLE IF NOT EXISTS memory_minute (
        bucket_ms INTEGER NOT NULL, project TEXT NOT NULL, agent TEXT NOT NULL, stage TEXT NOT NULL,
        request_count INTEGER NOT NULL, retrievals INTEGER NOT NULL, hits INTEGER NOT NULL,
        misses INTEGER NOT NULL, unknown INTEGER NOT NULL, context_tokens INTEGER NOT NULL,
        context_blocks INTEGER NOT NULL, unscoped_results INTEGER NOT NULL,
        cross_project_results INTEGER NOT NULL,
        PRIMARY KEY (bucket_ms, project, agent, stage)
      ) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS memory_minute_project_time ON memory_minute(project,bucket_ms);
      CREATE INDEX IF NOT EXISTS memory_minute_stage_time ON memory_minute(stage,bucket_ms);
      PRAGMA user_version=4;
      COMMIT;
    `);
    if (version < 5) {
      const existing = new Set((this.db.prepare("PRAGMA table_info(memory_minute)").all() as DbRow[]).map((row) => String(row.name)));
      const additions = ["storage_attempts", "stored", "storage_failures", "retrieval_failures", "result_count", "project_matches"];
      this.db.exec("BEGIN IMMEDIATE");
      try {
        for (const column of additions) if (!existing.has(column)) this.db.exec(`ALTER TABLE memory_minute ADD COLUMN ${column} INTEGER NOT NULL DEFAULT 0`);
        this.db.exec("PRAGMA user_version=5; COMMIT");
      } catch (error) {
        this.db.exec("ROLLBACK");
        throw error;
      }
    }
    if (version < 6) {
      const existing = new Set((this.db.prepare("PRAGMA table_info(memory_minute)").all() as DbRow[]).map((row) => String(row.name)));
      const integerColumns = [
        "automatic_retrievals", "automatic_hits", "automatic_context_tokens",
        "manual_retrievals", "manual_hits", "manual_context_tokens",
        "capture_payload_bytes", "capture_samples", "estimated_avoided_tokens_low",
        "estimated_avoided_tokens_high", "modeled_retrievals", "legacy_estimate_count",
        "budgeted_retrievals", "budget_tokens", "truncated_retrievals",
        "oversized_retrievals", "scored_retrievals",
      ];
      this.db.exec("BEGIN IMMEDIATE");
      try {
        for (const column of integerColumns) if (!existing.has(column)) this.db.exec(`ALTER TABLE memory_minute ADD COLUMN ${column} INTEGER NOT NULL DEFAULT 0`);
        if (!existing.has("retrieval_latency_total_ms")) this.db.exec("ALTER TABLE memory_minute ADD COLUMN retrieval_latency_total_ms REAL NOT NULL DEFAULT 0");
        if (!existing.has("top_score_total")) this.db.exec("ALTER TABLE memory_minute ADD COLUMN top_score_total REAL NOT NULL DEFAULT 0");
        this.db.exec(`
          CREATE TABLE IF NOT EXISTS history_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
          CREATE TABLE IF NOT EXISTS session_memory_flow (
            session_hash TEXT PRIMARY KEY, project TEXT NOT NULL, agent TEXT NOT NULL,
            first_at INTEGER NOT NULL, last_at INTEGER NOT NULL, starts INTEGER NOT NULL,
            ends INTEGER NOT NULL, automatic_retrievals INTEGER NOT NULL,
            automatic_hits INTEGER NOT NULL, automatic_context_tokens INTEGER NOT NULL,
            manual_retrievals INTEGER NOT NULL, manual_hits INTEGER NOT NULL,
            manual_context_tokens INTEGER NOT NULL
          ) WITHOUT ROWID;
          CREATE INDEX IF NOT EXISTS session_memory_flow_project_time ON session_memory_flow(project,first_at);
          CREATE INDEX IF NOT EXISTS session_memory_flow_last_time ON session_memory_flow(last_at);
          PRAGMA user_version=6;
          COMMIT;
        `);
      } catch (error) {
        this.db.exec("ROLLBACK");
        throw error;
      }
    }
    if (version < 7) {
      const existing = new Set((this.db.prepare("PRAGMA table_info(llm_usage_minute)").all() as DbRow[]).map((row) => String(row.name)));
      this.db.exec("BEGIN IMMEDIATE");
      try {
        if (!existing.has("throughput_measured_calls")) this.db.exec("ALTER TABLE llm_usage_minute ADD COLUMN throughput_measured_calls INTEGER NOT NULL DEFAULT 0");
        if (!existing.has("throughput_completion_tokens")) this.db.exec("ALTER TABLE llm_usage_minute ADD COLUMN throughput_completion_tokens INTEGER NOT NULL DEFAULT 0");
        if (!existing.has("throughput_provider_latency_ms")) this.db.exec("ALTER TABLE llm_usage_minute ADD COLUMN throughput_provider_latency_ms REAL NOT NULL DEFAULT 0");
        this.db.exec("PRAGMA user_version=7; COMMIT");
      } catch (error) {
        this.db.exec("ROLLBACK");
        throw error;
      }
    }
  }

  private sessionHash(sessionId: string): string {
    return createHash("sha256").update(this.sessionSalt).update("\0").update(sessionId).digest("hex");
  }

  ingest(batch: HistoryBatch): void {
    const histAssignments = HIST_COLUMNS.map((column) => `${column}=${column}+excluded.${column}`).join(",");
    const requestSql = `INSERT INTO request_minute VALUES (${Array(21).fill("?").join(",")})
      ON CONFLICT(bucket_ms,project,agent,method,status_class) DO UPDATE SET
      request_count=request_count+excluded.request_count,
      duration_total_ms=duration_total_ms+excluded.duration_total_ms,${histAssignments}`;
    const requestStatement = this.db.prepare(requestSql);
    const observationStatement = this.db.prepare(`INSERT INTO observation_minute VALUES (?,?,?,?,?,?)
      ON CONFLICT(bucket_ms,project,agent,kind,observation_type) DO UPDATE SET
      observation_count=observation_count+excluded.observation_count`);
    const memoryStatement = this.db.prepare(`INSERT INTO memory_minute
      (bucket_ms,project,agent,stage,request_count,retrievals,hits,misses,unknown,context_tokens,context_blocks,unscoped_results,cross_project_results,storage_attempts,stored,storage_failures,retrieval_failures,result_count,project_matches,
      automatic_retrievals,automatic_hits,automatic_context_tokens,manual_retrievals,manual_hits,manual_context_tokens,capture_payload_bytes,capture_samples,estimated_avoided_tokens_low,estimated_avoided_tokens_high,modeled_retrievals,legacy_estimate_count,budgeted_retrievals,budget_tokens,truncated_retrievals,oversized_retrievals,retrieval_latency_total_ms,scored_retrievals,top_score_total)
      VALUES (${Array(38).fill("?").join(",")})
      ON CONFLICT(bucket_ms,project,agent,stage) DO UPDATE SET
      request_count=request_count+excluded.request_count,retrievals=retrievals+excluded.retrievals,
      hits=hits+excluded.hits,misses=misses+excluded.misses,unknown=unknown+excluded.unknown,
      context_tokens=context_tokens+excluded.context_tokens,context_blocks=context_blocks+excluded.context_blocks,
      unscoped_results=unscoped_results+excluded.unscoped_results,
      cross_project_results=cross_project_results+excluded.cross_project_results,
      storage_attempts=storage_attempts+excluded.storage_attempts,stored=stored+excluded.stored,
      storage_failures=storage_failures+excluded.storage_failures,retrieval_failures=retrieval_failures+excluded.retrieval_failures,
      result_count=result_count+excluded.result_count,project_matches=project_matches+excluded.project_matches,
      automatic_retrievals=automatic_retrievals+excluded.automatic_retrievals,
      automatic_hits=automatic_hits+excluded.automatic_hits,
      automatic_context_tokens=automatic_context_tokens+excluded.automatic_context_tokens,
      manual_retrievals=manual_retrievals+excluded.manual_retrievals,
      manual_hits=manual_hits+excluded.manual_hits,manual_context_tokens=manual_context_tokens+excluded.manual_context_tokens,
      capture_payload_bytes=capture_payload_bytes+excluded.capture_payload_bytes,capture_samples=capture_samples+excluded.capture_samples,
      estimated_avoided_tokens_low=estimated_avoided_tokens_low+excluded.estimated_avoided_tokens_low,
      estimated_avoided_tokens_high=estimated_avoided_tokens_high+excluded.estimated_avoided_tokens_high,
      modeled_retrievals=modeled_retrievals+excluded.modeled_retrievals,legacy_estimate_count=legacy_estimate_count+excluded.legacy_estimate_count,
      budgeted_retrievals=budgeted_retrievals+excluded.budgeted_retrievals,budget_tokens=budget_tokens+excluded.budget_tokens,
      truncated_retrievals=truncated_retrievals+excluded.truncated_retrievals,oversized_retrievals=oversized_retrievals+excluded.oversized_retrievals,
      retrieval_latency_total_ms=retrieval_latency_total_ms+excluded.retrieval_latency_total_ms,
      scored_retrievals=scored_retrievals+excluded.scored_retrievals,top_score_total=top_score_total+excluded.top_score_total`);
    const sessionFlowStatement = this.db.prepare(`INSERT INTO session_memory_flow
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(session_hash) DO UPDATE SET
      project=CASE WHEN session_memory_flow.project='Global' THEN excluded.project ELSE session_memory_flow.project END,
      agent=CASE WHEN session_memory_flow.agent='unknown' THEN excluded.agent ELSE session_memory_flow.agent END,
      first_at=MIN(session_memory_flow.first_at,excluded.first_at),last_at=MAX(session_memory_flow.last_at,excluded.last_at),
      starts=starts+excluded.starts,ends=ends+excluded.ends,
      automatic_retrievals=automatic_retrievals+excluded.automatic_retrievals,
      automatic_hits=automatic_hits+excluded.automatic_hits,
      automatic_context_tokens=automatic_context_tokens+excluded.automatic_context_tokens,
      manual_retrievals=manual_retrievals+excluded.manual_retrievals,
      manual_hits=manual_hits+excluded.manual_hits,manual_context_tokens=manual_context_tokens+excluded.manual_context_tokens`);
    const llmStatement = this.db.prepare(`INSERT INTO llm_minute VALUES (?,?,?,?,?,?)
      ON CONFLICT(bucket_ms,function_id) DO UPDATE SET calls=calls+excluded.calls,
      successes=successes+excluded.successes, failures=failures+excluded.failures,
      latency_total_ms=latency_total_ms+excluded.latency_total_ms`);
    const processedCallStatement = this.db.prepare("INSERT OR IGNORE INTO processed_llm_calls VALUES (?, ?)");
    const usageStatement = this.db.prepare(`INSERT INTO llm_usage_minute
      (bucket_ms,provider,model,family,calls,prompt_tokens,cached_prompt_tokens,cache_write_tokens,completion_tokens,reasoning_tokens,total_tokens,estimated_cost_nanos,priced_calls,unpriced_calls,throughput_measured_calls,throughput_completion_tokens,throughput_provider_latency_ms)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(bucket_ms,provider,model,family) DO UPDATE SET
      calls=calls+excluded.calls,prompt_tokens=prompt_tokens+excluded.prompt_tokens,
      cached_prompt_tokens=cached_prompt_tokens+excluded.cached_prompt_tokens,
      cache_write_tokens=cache_write_tokens+excluded.cache_write_tokens,
      completion_tokens=completion_tokens+excluded.completion_tokens,
      reasoning_tokens=reasoning_tokens+excluded.reasoning_tokens,total_tokens=total_tokens+excluded.total_tokens,
      estimated_cost_nanos=estimated_cost_nanos+excluded.estimated_cost_nanos,
      priced_calls=priced_calls+excluded.priced_calls,unpriced_calls=unpriced_calls+excluded.unpriced_calls,
      throughput_measured_calls=throughput_measured_calls+excluded.throughput_measured_calls,
      throughput_completion_tokens=throughput_completion_tokens+excluded.throughput_completion_tokens,
      throughput_provider_latency_ms=throughput_provider_latency_ms+excluded.throughput_provider_latency_ms`);
    const systemStatement = this.db.prepare(`INSERT INTO system_minute VALUES (${Array(20).fill("?").join(",")})
      ON CONFLICT(bucket_ms) DO UPDATE SET
      samples=samples+excluded.samples, upstream_ok_samples=upstream_ok_samples+excluded.upstream_ok_samples,
      memories_first=COALESCE(system_minute.memories_first,excluded.memories_first),
      memories_last=COALESCE(excluded.memories_last,system_minute.memories_last),
      sessions_first=COALESCE(system_minute.sessions_first,excluded.sessions_first),
      sessions_last=COALESCE(excluded.sessions_last,system_minute.sessions_last),
      sessions_active_sum=sessions_active_sum+excluded.sessions_active_sum,
      sessions_active_count=sessions_active_count+excluded.sessions_active_count,
      sessions_active_max=MAX(COALESCE(system_minute.sessions_active_max,excluded.sessions_active_max),COALESCE(excluded.sessions_active_max,system_minute.sessions_active_max)),
      heap_sum_mb=heap_sum_mb+excluded.heap_sum_mb, heap_count=heap_count+excluded.heap_count,
      heap_max_mb=MAX(COALESCE(system_minute.heap_max_mb,excluded.heap_max_mb),COALESCE(excluded.heap_max_mb,system_minute.heap_max_mb)),
      rss_sum_mb=rss_sum_mb+excluded.rss_sum_mb, rss_count=rss_count+excluded.rss_count,
      rss_max_mb=MAX(COALESCE(system_minute.rss_max_mb,excluded.rss_max_mb),COALESCE(excluded.rss_max_mb,system_minute.rss_max_mb)),
      lag_sum_ms=lag_sum_ms+excluded.lag_sum_ms, lag_count=lag_count+excluded.lag_count,
      lag_max_ms=MAX(COALESCE(system_minute.lag_max_ms,excluded.lag_max_ms),COALESCE(excluded.lag_max_ms,system_minute.lag_max_ms)),
      uptime_last_sec=COALESCE(excluded.uptime_last_sec,system_minute.uptime_last_sec)`);

    this.db.exec("BEGIN IMMEDIATE");
    try {
      const inserted = this.db.prepare("INSERT OR IGNORE INTO applied_batches VALUES (?, ?)").run(batch.id, batch.createdAt);
      if (inserted.changes === 0) {
        this.db.exec("COMMIT");
        return;
      }
      for (const row of batch.requests) {
        requestStatement.run(
          row.bucketMs, row.project, row.agent, row.method, row.statusClass,
          row.count, row.durationTotalMs, ...row.latencyBins,
        );
      }
      for (const row of batch.observations) {
        observationStatement.run(row.bucketMs, row.project, row.agent, row.kind, row.observationType, row.count);
      }
      for (const row of batch.memory ?? []) {
        memoryStatement.run(
          row.bucketMs, row.project, row.agent, row.stage, row.requestCount,
          row.retrievals, row.hits, row.misses, row.unknown, row.contextTokens,
          row.contextBlocks, row.unscopedResults, row.crossProjectResults,
          row.storageAttempts ?? 0, row.stored ?? 0, row.storageFailures ?? 0,
          row.retrievalFailures ?? 0, row.resultCount ?? 0, row.projectMatches ?? 0,
          row.automaticRetrievals ?? 0, row.automaticHits ?? 0, row.automaticContextTokens ?? 0,
          row.manualRetrievals ?? 0, row.manualHits ?? 0, row.manualContextTokens ?? 0,
          row.capturePayloadBytes ?? 0, row.captureSamples ?? 0,
          row.estimatedAvoidedTokensLow ?? 0, row.estimatedAvoidedTokensHigh ?? 0,
          row.modeledRetrievals ?? 0, row.legacyEstimateCount ?? 0,
          row.budgetedRetrievals ?? 0, row.budgetTokens ?? 0,
          row.truncatedRetrievals ?? 0, row.oversizedRetrievals ?? 0,
          row.retrievalLatencyTotalMs ?? 0, row.scoredRetrievals ?? 0, row.topScoreTotal ?? 0,
        );
      }
      for (const row of batch.sessionFlows ?? []) {
        sessionFlowStatement.run(
          this.sessionHash(row.sessionId), row.project, row.agent, row.firstAt, row.lastAt,
          row.starts, row.ends, row.automaticRetrievals, row.automaticHits,
          row.automaticContextTokens, row.manualRetrievals, row.manualHits, row.manualContextTokens,
        );
      }
      for (const row of batch.llm) {
        llmStatement.run(row.bucketMs, row.functionId, row.calls, row.successes, row.failures, row.latencyTotalMs);
      }
      for (const row of batch.llmUsage ?? []) {
        if (processedCallStatement.run(row.callKey, row.completedAt).changes === 0) continue;
        usageStatement.run(
          row.bucketMs, row.provider, row.model, row.family, 1, row.promptTokens,
          row.cachedPromptTokens, row.cacheWriteTokens, row.completionTokens,
          row.reasoningTokens, row.totalTokens, row.estimatedCostNanos,
          row.pricedCalls, row.unpricedCalls, row.throughputMeasuredCalls ?? 0,
          row.throughputCompletionTokens ?? 0, row.throughputProviderLatencyMs ?? 0,
        );
      }
      for (const row of batch.system) {
        systemStatement.run(
          row.bucketMs, row.samples, row.upstreamOkSamples, row.memoriesFirst, row.memoriesLast,
          row.sessionsFirst, row.sessionsLast, row.sessionsActiveSum, row.sessionsActiveCount,
          row.sessionsActiveMax, row.heapSumMb, row.heapCount, row.heapMaxMb, row.rssSumMb,
          row.rssCount, row.rssMaxMb, row.lagSumMs, row.lagCount, row.lagMaxMs, row.uptimeLastSec,
        );
      }
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  recordProviderCosts(rows: import("./historyProtocol.js").ProviderCostDayRecord[]): void {
    const statement = this.db.prepare(`INSERT INTO provider_cost_day VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(day_ms,provider,scope_type,scope_id) DO UPDATE SET scope_label=excluded.scope_label,
      amount_nanos=excluded.amount_nanos,currency=excluded.currency,synced_at=excluded.synced_at,source=excluded.source`);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const row of rows) statement.run(row.dayMs, row.provider, row.scopeType, row.scopeId, row.scopeLabel, row.amountNanos, row.currency, row.syncedAt, row.source);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  setBillingScope(scope: BillingScopeRecord): void {
    this.db.prepare(`INSERT INTO billing_active_scope VALUES (?,?,?,?,?)
      ON CONFLICT(provider) DO UPDATE SET scope_type=excluded.scope_type,scope_id=excluded.scope_id,
      scope_label=excluded.scope_label,updated_at=excluded.updated_at`)
      .run(scope.provider, scope.scopeType, scope.scopeId, scope.scopeLabel, Date.now());
  }

  billingState(scope: BillingScopeRecord): BillingSyncStateRecord | null {
    const row = this.db.prepare(`SELECT * FROM billing_sync_state
      WHERE provider=? AND scope_type=? AND scope_id=?`).get(scope.provider, scope.scopeType, scope.scopeId) as DbRow | undefined;
    if (!row) return null;
    return {
      ...scope,
      scopeLabel: s(row, "scope_label"),
      lastAttemptAt: nullable(row, "last_attempt_at"),
      lastSuccessAt: nullable(row, "last_success_at"),
      nextAllowedAt: nullable(row, "next_allowed_at"),
      lastError: typeof row.last_error === "string" ? row.last_error : null,
      backfillComplete: n(row, "backfill_complete") === 1,
    };
  }

  setBillingState(state: BillingSyncStateRecord): void {
    this.db.prepare(`INSERT INTO billing_sync_state VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(provider,scope_type,scope_id) DO UPDATE SET scope_label=excluded.scope_label,
      last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,
      next_allowed_at=excluded.next_allowed_at,last_error=excluded.last_error,
      backfill_complete=excluded.backfill_complete`)
      .run(state.provider, state.scopeType, state.scopeId, state.scopeLabel, state.lastAttemptAt,
        state.lastSuccessAt, state.nextAllowedAt, state.lastError, state.backfillComplete ? 1 : 0);
  }

  prune(now: number): void {
    const cutoff = now - this.retentionMs;
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const table of ["request_minute", "memory_minute", "observation_minute", "llm_minute", "llm_usage_minute", "system_minute"]) {
        this.db.prepare(`DELETE FROM ${table} WHERE bucket_ms < ?`).run(cutoff);
      }
      this.db.prepare("DELETE FROM provider_cost_day WHERE day_ms < ?").run(cutoff);
      this.db.prepare("DELETE FROM processed_llm_calls WHERE completed_at < ?").run(cutoff);
      this.db.prepare("DELETE FROM session_memory_flow WHERE last_at < ?").run(cutoff);
      this.db.prepare("DELETE FROM console_runs WHERE started_at < ?").run(cutoff);
      this.db.prepare("DELETE FROM applied_batches WHERE created_at < ?").run(now - 86_400_000);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  meta(retentionDays: number): ReportMeta {
    const range = this.db.prepare(`SELECT MIN(earliest) AS earliest,MAX(latest) AS latest FROM (
      SELECT MIN(bucket_ms) AS earliest,MAX(bucket_ms) AS latest FROM request_minute UNION ALL
      SELECT MIN(bucket_ms),MAX(bucket_ms) FROM memory_minute UNION ALL
      SELECT MIN(bucket_ms),MAX(bucket_ms) FROM observation_minute UNION ALL
      SELECT MIN(bucket_ms),MAX(bucket_ms) FROM llm_minute UNION ALL
      SELECT MIN(bucket_ms),MAX(bucket_ms) FROM llm_usage_minute UNION ALL
      SELECT MIN(day_ms),MAX(day_ms) FROM provider_cost_day c
        WHERE EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id) UNION ALL
      SELECT MIN(bucket_ms),MAX(bucket_ms) FROM system_minute
    )`).get() as DbRow | undefined;
    const dimensions = (sql: string, key: string): string[] =>
      (this.db.prepare(sql).all() as DbRow[]).map((row) => s(row, key)).filter(Boolean);
    return {
      status: { ok: true, writable: true, lastFlushAt: null, lastError: null, pendingBatches: 0 },
      earliestTs: nullable(range, "earliest"),
      latestTs: nullable(range, "latest"),
      retentionDays,
      projects: dimensions("SELECT DISTINCT project FROM request_minute ORDER BY project", "project"),
      agents: dimensions("SELECT DISTINCT agent FROM request_minute ORDER BY agent", "agent"),
      llmFunctions: dimensions("SELECT DISTINCT function_id FROM llm_minute ORDER BY function_id", "function_id"),
      llmModels: dimensions("SELECT DISTINCT model FROM llm_usage_minute ORDER BY model", "model"),
      llmFamilies: dimensions("SELECT DISTINCT family FROM llm_usage_minute ORDER BY family", "family"),
    };
  }

  contextAvoidedHistory(now: number): ContextAvoidedHistorySnapshot {
    const dayFrom = now - 86_400_000;
    const weekFrom = now - 7 * 86_400_000;
    const row = this.db.prepare(`WITH bounds AS (SELECT ? AS day_from,? AS week_from,? AS to_ms)
      SELECT MIN(CASE WHEN modeled_retrievals>0 THEN bucket_ms END) AS tracking_since,
      SUM(CASE WHEN bucket_ms>=day_from THEN estimated_avoided_tokens_low ELSE 0 END) AS low_24h,
      SUM(CASE WHEN bucket_ms>=day_from THEN estimated_avoided_tokens_high ELSE 0 END) AS high_24h,
      SUM(CASE WHEN bucket_ms>=day_from THEN modeled_retrievals ELSE 0 END) AS modeled_24h,
      SUM(CASE WHEN bucket_ms>=day_from THEN legacy_estimate_count ELSE 0 END) AS legacy_24h,
      SUM(CASE WHEN bucket_ms>=week_from THEN estimated_avoided_tokens_low ELSE 0 END) AS low_7d,
      SUM(CASE WHEN bucket_ms>=week_from THEN estimated_avoided_tokens_high ELSE 0 END) AS high_7d,
      SUM(CASE WHEN bucket_ms>=week_from THEN modeled_retrievals ELSE 0 END) AS modeled_7d,
      SUM(CASE WHEN bucket_ms>=week_from THEN legacy_estimate_count ELSE 0 END) AS legacy_7d,
      SUM(estimated_avoided_tokens_low) AS low_all,
      SUM(estimated_avoided_tokens_high) AS high_all,
      SUM(modeled_retrievals) AS modeled_all,
      SUM(legacy_estimate_count) AS legacy_all
      FROM memory_minute CROSS JOIN bounds WHERE bucket_ms<to_ms`)
      .get(dayFrom, weekFrom, now) as DbRow | undefined;
    const trackingSince = nullable(row, "tracking_since");
    const window = (from: number, prefix: string): ContextAvoidedHistoryWindow => ({
      from,
      to: now,
      estimatedAvoidedTokensLow: n(row, `low_${prefix}`),
      estimatedAvoidedTokensHigh: n(row, `high_${prefix}`),
      modeledRetrievals: n(row, `modeled_${prefix}`),
      legacyEstimateCount: n(row, `legacy_${prefix}`),
    });
    return {
      generatedAt: now,
      trackingSince,
      past24Hours: window(dayFrom, "24h"),
      past7Days: window(weekFrom, "7d"),
      allTracked: window(trackingSince ?? now, "all"),
    };
  }

  report(query: ReportQuery): ReportSummaryResponse | ReportProjectsResponse | ReportMemoryResponse | ReportLlmResponse | ReportSystemResponse {
    if (query.section === "summary") return this.summary(query);
    if (query.section === "projects") return this.projects(query);
    if (query.section === "memory") return this.memory(query);
    if (query.section === "llm") return this.llm(query);
    return this.system(query);
  }

  costSnapshot(now: number): HistoryCostSnapshot {
    const date = new Date(now);
    const todayStart = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
    const monthStart = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1);
    const estimated = this.db.prepare(`SELECT SUM(estimated_cost_nanos) AS amount
      FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(todayStart, now + 1) as DbRow | undefined;
    const billed = this.db.prepare(`SELECT SUM(amount_nanos) AS amount,COUNT(*) AS rows
      FROM provider_cost_day c WHERE day_ms>=? AND day_ms<?
      AND EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id)`)
      .get(monthStart, now + 1) as DbRow | undefined;
    return {
      estimatedTodayNanos: n(estimated, "amount"),
      billedMonthToDateNanos: n(billed, "rows") > 0 ? n(billed, "amount") : null,
    };
  }

  private requestWhere(from: number, to: number, project?: string, agent?: string): { sql: string; params: Array<string | number> } {
    let sql = "bucket_ms >= ? AND bucket_ms < ?";
    const params: Array<string | number> = [from, to];
    if (project) { sql += " AND project = ?"; params.push(project); }
    if (agent) { sql += " AND agent = ?"; params.push(agent); }
    return { sql, params };
  }

  private hasData(from: number, to: number): boolean {
    const row = this.db.prepare(`SELECT EXISTS(
      SELECT 1 FROM request_minute WHERE bucket_ms>=? AND bucket_ms<? UNION ALL
      SELECT 1 FROM memory_minute WHERE bucket_ms>=? AND bucket_ms<? UNION ALL
      SELECT 1 FROM observation_minute WHERE bucket_ms>=? AND bucket_ms<? UNION ALL
      SELECT 1 FROM llm_minute WHERE bucket_ms>=? AND bucket_ms<? UNION ALL
      SELECT 1 FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<? UNION ALL
      SELECT 1 FROM provider_cost_day c WHERE day_ms>=? AND day_ms<?
        AND EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id) UNION ALL
      SELECT 1 FROM system_minute WHERE bucket_ms>=? AND bucket_ms<?
    ) AS present`).get(from, to, from, to, from, to, from, to, from, to, from, to, from, to) as DbRow | undefined;
    return n(row, "present") > 0;
  }

  private summaryTotals(from: number, to: number): ReportSummaryTotals {
    const request = this.db.prepare(`SELECT SUM(request_count) AS requests,
      SUM(CASE WHEN status_class IN ('4xx','5xx','network') THEN request_count ELSE 0 END) AS errors,
      ${histogramSelect()} FROM request_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(from, to) as DbRow | undefined;
    const obs = this.db.prepare(`SELECT SUM(observation_count) AS observations,
      SUM(CASE WHEN kind='raw' THEN observation_count ELSE 0 END) AS raw,
      SUM(CASE WHEN kind='compressed' THEN observation_count ELSE 0 END) AS compressed
      FROM observation_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(from, to) as DbRow | undefined;
    const llm = this.db.prepare(`SELECT SUM(calls) AS calls, SUM(failures) AS failures
      FROM llm_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(from, to) as DbRow | undefined;
    const usage = this.db.prepare(`SELECT SUM(estimated_cost_nanos) AS estimated,
      SUM(priced_calls) AS priced,SUM(unpriced_calls) AS unpriced,
      SUM(calls-priced_calls-unpriced_calls) AS local,
      SUM(throughput_measured_calls) AS throughput_calls,
      SUM(throughput_completion_tokens) AS throughput_completion,
      SUM(throughput_provider_latency_ms) AS throughput_latency
      FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(from, to) as DbRow | undefined;
    const billed = this.db.prepare(`SELECT SUM(amount_nanos) AS billed
      FROM provider_cost_day c WHERE day_ms>=? AND day_ms<?
      AND EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id)`)
      .get(from, to) as DbRow | undefined;
    const system = this.db.prepare(`SELECT SUM(samples) AS samples, SUM(upstream_ok_samples) AS ok
      FROM system_minute WHERE bucket_ms>=? AND bucket_ms<?`).get(from, to) as DbRow | undefined;
    const first = this.db.prepare(`SELECT memories_first,sessions_first FROM system_minute
      WHERE bucket_ms>=? AND bucket_ms<? AND (memories_first IS NOT NULL OR sessions_first IS NOT NULL)
      ORDER BY bucket_ms LIMIT 1`).get(from, to) as DbRow | undefined;
    const last = this.db.prepare(`SELECT memories_last,sessions_last FROM system_minute
      WHERE bucket_ms>=? AND bucket_ms<? AND (memories_last IS NOT NULL OR sessions_last IS NOT NULL)
      ORDER BY bucket_ms DESC LIMIT 1`).get(from, to) as DbRow | undefined;
    const requests = n(request, "requests");
    const errors = n(request, "errors");
    const memoriesEnd = nullable(last, "memories_last");
    const memoriesStart = nullable(first, "memories_first");
    const sessionsEnd = nullable(last, "sessions_last");
    const sessionsStart = nullable(first, "sessions_first");
    const samples = n(system, "samples");
    return {
      requests,
      errors,
      errorRate: safeRate(errors, requests),
      requestsPerMinute: requests / durationMinutes(from, to),
      p95Ms: percentile95(request),
      observations: n(obs, "observations"),
      rawObservations: n(obs, "raw"),
      compressedObservations: n(obs, "compressed"),
      llmCalls: n(llm, "calls"),
      llmFailures: n(llm, "failures"),
      pricedLlmCalls: n(usage, "priced"),
      unpricedLlmCalls: n(usage, "unpriced"),
      localLlmCalls: n(usage, "local"),
      memoriesEnd,
      memoriesChange: memoriesEnd !== null && memoriesStart !== null ? memoriesEnd - memoriesStart : null,
      sessionsEnd,
      sessionsChange: sessionsEnd !== null && sessionsStart !== null ? sessionsEnd - sessionsStart : null,
      sampledAvailability: samples > 0 ? n(system, "ok") / samples : null,
      estimatedLlmCostNanos: n(usage, "estimated"),
      billedProviderCostNanos: nullable(billed, "billed"),
    };
  }

  private summary(query: ReportQuery): ReportSummaryResponse {
    const points = new Map<number, ReportSummaryPoint>();
    const ensure = (t: number): ReportSummaryPoint => {
      let point = points.get(t);
      if (!point) {
        point = { t, requests: 0, errors: 0, p95Ms: 0, rawObservations: 0,
          compressedObservations: 0, llmCalls: 0, llmFailures: 0,
          memoriesTotal: null, sessionsTotal: null, sampledAvailability: null,
          estimatedLlmCostNanos: 0, billedProviderCostNanos: null };
        points.set(t, point);
      }
      return point;
    };
    const requestRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,
      SUM(request_count) AS requests,
      SUM(CASE WHEN status_class IN ('4xx','5xx','network') THEN request_count ELSE 0 END) AS errors,
      ${histogramSelect()} FROM request_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    for (const row of requestRows) {
      const point = ensure(n(row, "t")); point.requests = n(row, "requests"); point.errors = n(row, "errors"); point.p95Ms = percentile95(row);
    }
    const obsRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,
      SUM(CASE WHEN kind='raw' THEN observation_count ELSE 0 END) AS raw,
      SUM(CASE WHEN kind='compressed' THEN observation_count ELSE 0 END) AS compressed
      FROM observation_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    for (const row of obsRows) { const point = ensure(n(row, "t")); point.rawObservations = n(row, "raw"); point.compressedObservations = n(row, "compressed"); }
    const llmRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,SUM(calls) AS calls,SUM(failures) AS failures
      FROM llm_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    for (const row of llmRows) { const point = ensure(n(row, "t")); point.llmCalls = n(row, "calls"); point.llmFailures = n(row, "failures"); }
    const usageRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,SUM(estimated_cost_nanos) AS estimated
      FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    for (const row of usageRows) ensure(n(row, "t")).estimatedLlmCostNanos = n(row, "estimated");
    const costRows = this.db.prepare(`SELECT (day_ms / ?) * ? AS t,SUM(amount_nanos) AS billed
      FROM provider_cost_day c WHERE day_ms>=? AND day_ms<?
      AND EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id)
      GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    for (const row of costRows) ensure(n(row, "t")).billedProviderCostNanos = n(row, "billed");
    const systemRows = this.systemSeries(query.from, query.to, query.bucketMs);
    for (const row of systemRows) {
      const point = ensure(row.t); point.memoriesTotal = row.memoriesTotal; point.sessionsTotal = row.sessionsTotal; point.sampledAvailability = row.sampledAvailability;
    }
    for (let t = Math.floor(query.from / query.bucketMs) * query.bucketMs; t < query.to; t += query.bucketMs) ensure(t);
    const duration = query.to - query.from;
    const previousFrom = query.from - duration;
    return {
      range: { from: query.from, to: query.to, bucketMs: query.bucketMs },
      current: this.summaryTotals(query.from, query.to),
      previous: query.compare && this.hasData(previousFrom, query.from) ? this.summaryTotals(previousFrom, query.from) : null,
      series: [...points.values()].sort((a, b) => a.t - b.t),
    };
  }

  private projectRows(from: number, to: number, project?: string, agent?: string): Array<Omit<ReportProjectRow, "previousRequests">> {
    const where = this.requestWhere(from, to, project, agent);
    const rows = this.db.prepare(`SELECT project,SUM(request_count) AS requests,
      SUM(CASE WHEN status_class IN ('4xx','5xx','network') THEN request_count ELSE 0 END) AS errors,
      SUM(CASE WHEN method='get' THEN request_count ELSE 0 END) AS get_count,
      SUM(CASE WHEN method='post' THEN request_count ELSE 0 END) AS post_count,
      SUM(CASE WHEN method='put' THEN request_count ELSE 0 END) AS put_count,
      SUM(CASE WHEN method='delete' THEN request_count ELSE 0 END) AS delete_count,
      SUM(CASE WHEN method='other' THEN request_count ELSE 0 END) AS other_count,
      ${histogramSelect()} FROM request_minute WHERE ${where.sql} GROUP BY project ORDER BY requests DESC`)
      .all(...where.params) as DbRow[];
    const agents = this.db.prepare(`SELECT project,agent,SUM(request_count) AS count FROM request_minute
      WHERE ${where.sql} GROUP BY project,agent ORDER BY count DESC`).all(...where.params) as DbRow[];
    const observationsWhere = ["bucket_ms>=?", "bucket_ms<?"];
    const observationParams: Array<string | number> = [from, to];
    if (project) { observationsWhere.push("project=?"); observationParams.push(project); }
    if (agent) { observationsWhere.push("agent=?"); observationParams.push(agent); }
    const observations = this.db.prepare(`SELECT project,SUM(observation_count) AS count FROM observation_minute
      WHERE ${observationsWhere.join(" AND ")} GROUP BY project`).all(...observationParams) as DbRow[];
    const agentMap = new Map<string, Array<{ agent: string; count: number }>>();
    for (const row of agents) {
      const key = s(row, "project"); const list = agentMap.get(key) ?? [];
      list.push({ agent: s(row, "agent"), count: n(row, "count") }); agentMap.set(key, list);
    }
    const obsMap = new Map(observations.map((row) => [s(row, "project"), n(row, "count")]));
    return rows.map((row) => {
      const requests = n(row, "requests"); const errors = n(row, "errors");
      const methods = methodCounts();
      methods.get = n(row, "get_count"); methods.post = n(row, "post_count"); methods.put = n(row, "put_count"); methods.delete = n(row, "delete_count"); methods.other = n(row, "other_count");
      return { project: s(row, "project"), requests, errors, errorRate: safeRate(errors, requests), p95Ms: percentile95(row), observations: obsMap.get(s(row, "project")) ?? 0, methods, agents: agentMap.get(s(row, "project")) ?? [] };
    });
  }

  private projects(query: ReportQuery): ReportProjectsResponse {
    const current = this.projectRows(query.from, query.to, query.project, query.agent);
    const previousFrom = query.from - (query.to - query.from);
    const previous = query.compare ? this.projectRows(previousFrom, query.from, query.project, query.agent) : [];
    const previousAvailable = query.compare && previous.length > 0;
    const previousMap = new Map(previous.map((row) => [row.project, row.requests]));
    const where = this.requestWhere(query.from, query.to, query.project, query.agent);
    const seriesRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,SUM(request_count) AS requests,
      SUM(CASE WHEN status_class IN ('4xx','5xx','network') THEN request_count ELSE 0 END) AS errors
      FROM request_minute WHERE ${where.sql} GROUP BY t ORDER BY t`).all(query.bucketMs, query.bucketMs, ...where.params) as DbRow[];
    const seriesMap = new Map(seriesRows.map((row) => [n(row, "t"), { t: n(row, "t"), requests: n(row, "requests"), errors: n(row, "errors") }]));
    for (let t = Math.floor(query.from / query.bucketMs) * query.bucketMs; t < query.to; t += query.bucketMs) if (!seriesMap.has(t)) seriesMap.set(t, { t, requests: 0, errors: 0 });
    return {
      range: { from: query.from, to: query.to, bucketMs: query.bucketMs },
      rows: current.map((row) => ({ ...row, previousRequests: previousAvailable ? previousMap.get(row.project) ?? 0 : null })),
      series: [...seriesMap.values()].sort((a, b) => a.t - b.t) as ReportProjectPoint[],
    };
  }

  private memoryTotals(from: number, to: number, project?: string, agent?: string): ReportMemoryTotals {
    const where = this.requestWhere(from, to, project, agent);
    const row = this.db.prepare(`SELECT
      SUM(retrievals) AS retrievals,SUM(hits) AS hits,SUM(misses) AS misses,SUM(unknown) AS unknown,
      SUM(context_tokens) AS context_tokens,SUM(context_blocks) AS context_blocks,
      SUM(unscoped_results) AS unscoped_results,SUM(cross_project_results) AS cross_project_results,
      SUM(storage_attempts) AS storage_attempts,SUM(stored) AS stored,SUM(storage_failures) AS storage_failures,
      SUM(retrieval_failures) AS retrieval_failures,SUM(result_count) AS result_count,SUM(project_matches) AS project_matches,
      SUM(automatic_retrievals) AS automatic_retrievals,SUM(automatic_hits) AS automatic_hits,
      SUM(automatic_context_tokens) AS automatic_context_tokens,SUM(manual_retrievals) AS manual_retrievals,
      SUM(manual_hits) AS manual_hits,SUM(manual_context_tokens) AS manual_context_tokens,
      SUM(capture_payload_bytes) AS capture_payload_bytes,SUM(capture_samples) AS capture_samples,
      SUM(estimated_avoided_tokens_low) AS estimated_avoided_tokens_low,
      SUM(estimated_avoided_tokens_high) AS estimated_avoided_tokens_high,
      SUM(modeled_retrievals) AS modeled_retrievals,SUM(legacy_estimate_count) AS legacy_estimate_count,
      SUM(budgeted_retrievals) AS budgeted_retrievals,SUM(budget_tokens) AS budget_tokens,
      SUM(truncated_retrievals) AS truncated_retrievals,SUM(oversized_retrievals) AS oversized_retrievals,
      SUM(retrieval_latency_total_ms) AS retrieval_latency_total_ms,SUM(scored_retrievals) AS scored_retrievals,
      SUM(top_score_total) AS top_score_total,
      SUM(CASE WHEN stage='session_start' THEN request_count ELSE 0 END) AS session_starts,
      SUM(CASE WHEN stage='session_end' THEN request_count ELSE 0 END) AS session_ends,
      SUM(CASE WHEN stage='observation_capture' THEN request_count ELSE 0 END) AS observations_captured,
      SUM(CASE WHEN stage='memory_save' THEN request_count ELSE 0 END) AS memories_saved,
      SUM(CASE WHEN stage='consolidate' THEN request_count ELSE 0 END) AS consolidations
      FROM memory_minute WHERE ${where.sql}`).get(...where.params) as DbRow | undefined;
    const hits = n(row, "hits");
    const misses = n(row, "misses");
    const retrievals = n(row, "retrievals");
    const attempts = n(row, "storage_attempts");
    const stored = n(row, "stored");
    const coverage = this.sessionCoverage(from, to, project, agent);
    const retrievalLatencyCount = n(row, "automatic_retrievals") + n(row, "manual_retrievals");
    const scored = n(row, "scored_retrievals");
    return {
      retrievals,
      hits,
      misses,
      unknown: n(row, "unknown"),
      hitRate: hits + misses > 0 ? hits / (hits + misses) : null,
      contextTokens: n(row, "context_tokens"),
      contextBlocks: n(row, "context_blocks"),
      unscopedResults: n(row, "unscoped_results"),
      crossProjectResults: n(row, "cross_project_results"),
      sessionStarts: n(row, "session_starts"),
      sessionEnds: n(row, "session_ends"),
      observationsCaptured: n(row, "observations_captured"),
      memoriesSaved: n(row, "memories_saved"),
      consolidations: n(row, "consolidations"),
      storageAttempts: attempts, stored, storageFailures: n(row, "storage_failures"),
      retrievalFailures: n(row, "retrieval_failures"), resultCount: n(row, "result_count"),
      projectMatches: n(row, "project_matches"), saveReliability: attempts > 0 ? stored / attempts : null,
      recallDeliveryRate: retrievals > 0 ? hits / retrievals : null,
      automaticRetrievals: n(row, "automatic_retrievals"), automaticHits: n(row, "automatic_hits"),
      automaticContextTokens: n(row, "automatic_context_tokens"), manualRetrievals: n(row, "manual_retrievals"),
      manualHits: n(row, "manual_hits"), manualContextTokens: n(row, "manual_context_tokens"),
      capturePayloadBytes: n(row, "capture_payload_bytes"), captureSamples: n(row, "capture_samples"),
      estimatedAvoidedTokensLow: n(row, "estimated_avoided_tokens_low"), estimatedAvoidedTokensHigh: n(row, "estimated_avoided_tokens_high"),
      modeledRetrievals: n(row, "modeled_retrievals"), legacyEstimateCount: n(row, "legacy_estimate_count"),
      budgetedRetrievals: n(row, "budgeted_retrievals"), budgetTokens: n(row, "budget_tokens"),
      truncatedRetrievals: n(row, "truncated_retrievals"), oversizedRetrievals: n(row, "oversized_retrievals"),
      retrievalLatencyMs: retrievalLatencyCount > 0 ? n(row, "retrieval_latency_total_ms") / retrievalLatencyCount : null,
      averageTopScore: scored > 0 ? n(row, "top_score_total") / scored : null,
      uniqueSessionsStarted: coverage.started, sessionsAssisted: coverage.assisted, sessionsClosed: coverage.closed,
    };
  }

  private sessionCoverage(from: number, to: number, project?: string, agent?: string): { started: number; assisted: number; closed: number } {
    const where = ["first_at>=?", "first_at<?", "starts>0"];
    const params: Array<string | number> = [from, to];
    if (project) { where.push("project=?"); params.push(project); }
    if (agent) { where.push("agent=?"); params.push(agent); }
    const row = this.db.prepare(`SELECT COUNT(*) AS started,
      SUM(CASE WHEN automatic_hits>0 THEN 1 ELSE 0 END) AS assisted,
      SUM(CASE WHEN ends>0 THEN 1 ELSE 0 END) AS closed
      FROM session_memory_flow WHERE ${where.join(" AND ")}`).get(...params) as DbRow | undefined;
    return { started: n(row, "started"), assisted: n(row, "assisted"), closed: n(row, "closed") };
  }

  private memory(query: ReportQuery): ReportMemoryResponse {
    const where = this.requestWhere(query.from, query.to, query.project, query.agent);
    const selectTotals = `SUM(retrievals) AS retrievals,SUM(hits) AS hits,SUM(misses) AS misses,
      SUM(unknown) AS unknown,SUM(context_tokens) AS context_tokens,SUM(context_blocks) AS context_blocks,
      SUM(unscoped_results) AS unscoped_results,SUM(cross_project_results) AS cross_project_results,
      SUM(storage_attempts) AS storage_attempts,SUM(stored) AS stored,SUM(storage_failures) AS storage_failures,
      SUM(retrieval_failures) AS retrieval_failures,SUM(result_count) AS result_count,SUM(project_matches) AS project_matches,
      SUM(automatic_retrievals) AS automatic_retrievals,SUM(automatic_hits) AS automatic_hits,
      SUM(automatic_context_tokens) AS automatic_context_tokens,SUM(manual_retrievals) AS manual_retrievals,
      SUM(manual_hits) AS manual_hits,SUM(manual_context_tokens) AS manual_context_tokens,
      SUM(capture_payload_bytes) AS capture_payload_bytes,SUM(capture_samples) AS capture_samples,
      SUM(estimated_avoided_tokens_low) AS estimated_avoided_tokens_low,
      SUM(estimated_avoided_tokens_high) AS estimated_avoided_tokens_high,
      SUM(modeled_retrievals) AS modeled_retrievals,SUM(legacy_estimate_count) AS legacy_estimate_count,
      SUM(budgeted_retrievals) AS budgeted_retrievals,SUM(budget_tokens) AS budget_tokens,
      SUM(truncated_retrievals) AS truncated_retrievals,SUM(oversized_retrievals) AS oversized_retrievals,
      SUM(retrieval_latency_total_ms) AS retrieval_latency_total_ms,SUM(scored_retrievals) AS scored_retrievals,
      SUM(top_score_total) AS top_score_total,
      SUM(CASE WHEN stage='session_start' THEN request_count ELSE 0 END) AS session_starts,
      SUM(CASE WHEN stage='session_end' THEN request_count ELSE 0 END) AS session_ends,
      SUM(CASE WHEN stage='observation_capture' THEN request_count ELSE 0 END) AS observations_captured,
      SUM(CASE WHEN stage='memory_save' THEN request_count ELSE 0 END) AS memories_saved,
      SUM(CASE WHEN stage='consolidate' THEN request_count ELSE 0 END) AS consolidations`;
    const toTotals = (row: DbRow | undefined): ReportMemoryTotals => {
      const hits = n(row, "hits");
      const misses = n(row, "misses");
      const retrievals = n(row, "retrievals");
      const attempts = n(row, "storage_attempts");
      const stored = n(row, "stored");
      const retrievalLatencyCount = n(row, "automatic_retrievals") + n(row, "manual_retrievals");
      const scored = n(row, "scored_retrievals");
      return {
        retrievals, hits, misses, unknown: n(row, "unknown"),
        hitRate: hits + misses > 0 ? hits / (hits + misses) : null,
        contextTokens: n(row, "context_tokens"), contextBlocks: n(row, "context_blocks"),
        unscopedResults: n(row, "unscoped_results"), crossProjectResults: n(row, "cross_project_results"),
        sessionStarts: n(row, "session_starts"), sessionEnds: n(row, "session_ends"),
        observationsCaptured: n(row, "observations_captured"), memoriesSaved: n(row, "memories_saved"),
        consolidations: n(row, "consolidations"),
        storageAttempts: attempts, stored, storageFailures: n(row, "storage_failures"),
        retrievalFailures: n(row, "retrieval_failures"), resultCount: n(row, "result_count"),
        projectMatches: n(row, "project_matches"), saveReliability: attempts > 0 ? stored / attempts : null,
        recallDeliveryRate: retrievals > 0 ? hits / retrievals : null,
        automaticRetrievals: n(row, "automatic_retrievals"), automaticHits: n(row, "automatic_hits"),
        automaticContextTokens: n(row, "automatic_context_tokens"), manualRetrievals: n(row, "manual_retrievals"),
        manualHits: n(row, "manual_hits"), manualContextTokens: n(row, "manual_context_tokens"),
        capturePayloadBytes: n(row, "capture_payload_bytes"), captureSamples: n(row, "capture_samples"),
        estimatedAvoidedTokensLow: n(row, "estimated_avoided_tokens_low"), estimatedAvoidedTokensHigh: n(row, "estimated_avoided_tokens_high"),
        modeledRetrievals: n(row, "modeled_retrievals"), legacyEstimateCount: n(row, "legacy_estimate_count"),
        budgetedRetrievals: n(row, "budgeted_retrievals"), budgetTokens: n(row, "budget_tokens"),
        truncatedRetrievals: n(row, "truncated_retrievals"), oversizedRetrievals: n(row, "oversized_retrievals"),
        retrievalLatencyMs: retrievalLatencyCount > 0 ? n(row, "retrieval_latency_total_ms") / retrievalLatencyCount : null,
        averageTopScore: scored > 0 ? n(row, "top_score_total") / scored : null,
        uniqueSessionsStarted: n(row, "session_starts"), sessionsAssisted: 0, sessionsClosed: n(row, "session_ends"),
      };
    };
    const pointRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,${selectTotals}
      FROM memory_minute WHERE ${where.sql} GROUP BY t ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, ...where.params) as DbRow[];
    const pointMap = new Map<number, ReportMemoryPoint>(pointRows.map((row) => {
      const t = n(row, "t");
      return [t, { t, ...toTotals(row) }];
    }));
    for (let t = Math.floor(query.from / query.bucketMs) * query.bucketMs; t < query.to; t += query.bucketMs) {
      if (!pointMap.has(t)) pointMap.set(t, { t, ...toTotals(undefined) });
    }
    const projectRows = this.db.prepare(`SELECT project,${selectTotals}
      FROM memory_minute WHERE ${where.sql} GROUP BY project ORDER BY retrievals DESC,observations_captured DESC`)
      .all(...where.params) as DbRow[];
    const previousFrom = query.from - (query.to - query.from);
    const previousWhere = this.requestWhere(previousFrom, query.from, query.project, query.agent);
    const previousAvailable = query.compare && Boolean(this.db.prepare(`SELECT 1 FROM memory_minute WHERE ${previousWhere.sql} LIMIT 1`).get(...previousWhere.params));
    return {
      range: { from: query.from, to: query.to, bucketMs: query.bucketMs },
      current: this.memoryTotals(query.from, query.to, query.project, query.agent),
      previous: previousAvailable ? this.memoryTotals(previousFrom, query.from, query.project, query.agent) : null,
      series: [...pointMap.values()].sort((a, b) => a.t - b.t),
      projects: projectRows.map((row): ReportMemoryProjectRow => {
        const project = s(row, "project");
        const totals = toTotals(row);
        const coverage = this.sessionCoverage(query.from, query.to, project, query.agent);
        return { ...totals, project, uniqueSessionsStarted: coverage.started, sessionsAssisted: coverage.assisted, sessionsClosed: coverage.closed };
      }),
    };
  }

  private llmRows(from: number, to: number, functionId?: string): Array<Omit<ReportLlmRow, "previousCalls">> {
    const where = ["bucket_ms>=?", "bucket_ms<?"];
    const params: Array<string | number> = [from, to];
    if (functionId) { where.push("function_id=?"); params.push(functionId); }
    const rows = this.db.prepare(`SELECT function_id,SUM(calls) AS calls,SUM(successes) AS successes,
      SUM(failures) AS failures,SUM(latency_total_ms) AS latency FROM llm_minute
      WHERE ${where.join(" AND ")} GROUP BY function_id ORDER BY calls DESC`).all(...params) as DbRow[];
    const costs = this.db.prepare(`SELECT family,SUM(estimated_cost_nanos) AS cost FROM llm_usage_minute
      WHERE bucket_ms>=? AND bucket_ms<? GROUP BY family`).all(from, to) as DbRow[];
    const costByFamily = new Map(costs.map((row) => [s(row, "family"), n(row, "cost")]));
    return rows.map((row) => {
      const id = s(row, "function_id"); const calls = n(row, "calls"); const successes = n(row, "successes");
      return { functionId: id, calls, successes, failures: n(row, "failures"), successRate: safeRate(successes, calls), avgLatencyMs: calls > 0 ? n(row, "latency") / calls : 0, estimatedCostNanos: costByFamily.get(functionFamily(id)) ?? 0 };
    });
  }

  private llm(query: ReportQuery): ReportLlmResponse {
    const current = this.llmRows(query.from, query.to, query.functionId);
    const previousFrom = query.from - (query.to - query.from);
    const previous = query.compare ? this.llmRows(previousFrom, query.from, query.functionId) : [];
    const previousAvailable = query.compare && previous.length > 0;
    const previousMap = new Map(previous.map((row) => [row.functionId, row.calls]));
    const where = ["bucket_ms>=?", "bucket_ms<?"];
    const params: Array<string | number> = [query.from, query.to];
    if (query.functionId) { where.push("function_id=?"); params.push(query.functionId); }
    const rows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,function_id,SUM(calls) AS calls,
      SUM(successes) AS successes,SUM(failures) AS failures,SUM(latency_total_ms) AS latency
      FROM llm_minute WHERE ${where.join(" AND ")} GROUP BY t,function_id ORDER BY t`)
      .all(query.bucketMs, query.bucketMs, ...params) as DbRow[];
    const costSeriesRows = this.db.prepare(`SELECT (bucket_ms / ?) * ? AS t,family,SUM(estimated_cost_nanos) AS cost
      FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY t,family`)
      .all(query.bucketMs, query.bucketMs, query.from, query.to) as DbRow[];
    const seriesCost = new Map(costSeriesRows.map((row) => [`${n(row, "t")}\0${s(row, "family")}`, n(row, "cost")]));
    const series: ReportLlmPoint[] = rows.map((row) => {
      const t = n(row, "t"); const id = s(row, "function_id"); const calls = n(row, "calls");
      return { t, functionId: id, calls, successes: n(row, "successes"), failures: n(row, "failures"), avgLatencyMs: calls > 0 ? n(row, "latency") / calls : 0, estimatedCostNanos: seriesCost.get(`${t}\0${functionFamily(id)}`) ?? 0 };
    });
    const rawUsage = this.db.prepare(`SELECT provider,model,family,SUM(calls) AS calls,
      SUM(prompt_tokens) AS prompt,SUM(cached_prompt_tokens) AS cached,SUM(cache_write_tokens) AS cache_write,
      SUM(completion_tokens) AS completion,SUM(reasoning_tokens) AS reasoning,SUM(total_tokens) AS total,
      SUM(estimated_cost_nanos) AS cost,SUM(priced_calls) AS priced,SUM(unpriced_calls) AS unpriced,
      SUM(calls-priced_calls-unpriced_calls) AS local,
      SUM(throughput_measured_calls) AS throughput_calls,
      SUM(throughput_completion_tokens) AS throughput_completion,
      SUM(throughput_provider_latency_ms) AS throughput_latency
      FROM llm_usage_minute WHERE bucket_ms>=? AND bucket_ms<? GROUP BY provider,model,family ORDER BY cost DESC,calls DESC`)
      .all(query.from, query.to) as DbRow[];
    const usageRows: ReportLlmUsageRow[] = rawUsage.map((row) => {
      const throughputLatency = n(row, "throughput_latency");
      const throughputCompletion = n(row, "throughput_completion");
      return {
        provider: s(row, "provider"), model: s(row, "model"), family: s(row, "family"), calls: n(row, "calls"),
        promptTokens: n(row, "prompt"), cachedPromptTokens: n(row, "cached"), cacheWriteTokens: n(row, "cache_write"),
        completionTokens: n(row, "completion"), reasoningTokens: n(row, "reasoning"), totalTokens: n(row, "total"),
        estimatedCostNanos: n(row, "cost"), pricedCalls: n(row, "priced"), unpricedCalls: n(row, "unpriced"),
        localCalls: n(row, "local"), throughputMeasuredCalls: n(row, "throughput_calls"),
        throughputCompletionTokens: throughputCompletion, throughputProviderLatencyMs: throughputLatency,
        outputTokensPerSecond: throughputLatency > 0 ? throughputCompletion / (throughputLatency / 1_000) : null,
      };
    });
    const rawProviderCosts = this.db.prepare(`SELECT day_ms,provider,scope_type,scope_id,scope_label,amount_nanos,currency
      FROM provider_cost_day c WHERE day_ms>=? AND day_ms<?
      AND EXISTS (SELECT 1 FROM billing_active_scope s WHERE s.provider=c.provider AND s.scope_type=c.scope_type AND s.scope_id=c.scope_id)
      ORDER BY day_ms`).all(query.from, query.to) as DbRow[];
    const providerCosts: ReportProviderCostPoint[] = rawProviderCosts.map((row) => ({
      t: n(row, "day_ms"), provider: s(row, "provider"), scopeType: s(row, "scope_type") as "project" | "api_key",
      scopeId: s(row, "scope_id"), scopeLabel: s(row, "scope_label"),
      billedCostNanos: n(row, "amount_nanos"), currency: s(row, "currency"),
    }));
    const estimatedCostNanos = usageRows.reduce((sum, row) => sum + row.estimatedCostNanos, 0);
    const billedCostNanos = providerCosts.length > 0 ? providerCosts.reduce((sum, row) => sum + row.billedCostNanos, 0) : null;
    return { range: { from: query.from, to: query.to, bucketMs: query.bucketMs }, rows: current.map((row) => ({ ...row, previousCalls: previousAvailable ? previousMap.get(row.functionId) ?? 0 : null })), series, usageRows, providerCosts, estimatedCostNanos, billedCostNanos };
  }

  private systemSeries(from: number, to: number, bucketMs: number): ReportSystemPoint[] {
    const rows = this.db.prepare(`WITH base AS (
      SELECT (bucket_ms / ?) * ? AS t,*,ROW_NUMBER() OVER(PARTITION BY (bucket_ms / ?) ORDER BY bucket_ms DESC) AS rn
      FROM system_minute WHERE bucket_ms>=? AND bucket_ms<?
    ) SELECT t,SUM(samples) AS samples,SUM(upstream_ok_samples) AS ok,
      SUM(sessions_active_sum) AS active_sum,SUM(sessions_active_count) AS active_count,
      SUM(heap_sum_mb) AS heap_sum,SUM(heap_count) AS heap_count,MAX(heap_max_mb) AS heap_max,
      SUM(rss_sum_mb) AS rss_sum,SUM(rss_count) AS rss_count,MAX(rss_max_mb) AS rss_max,
      SUM(lag_sum_ms) AS lag_sum,SUM(lag_count) AS lag_count,MAX(lag_max_ms) AS lag_max,
      MAX(CASE WHEN rn=1 THEN memories_last END) AS memories_last,
      MAX(CASE WHEN rn=1 THEN sessions_last END) AS sessions_last,
      MAX(CASE WHEN rn=1 THEN uptime_last_sec END) AS uptime_last
      FROM base GROUP BY t ORDER BY t`).all(bucketMs, bucketMs, bucketMs, from, to) as DbRow[];
    return rows.map((row) => {
      const samples = n(row, "samples"); const activeCount = n(row, "active_count"); const heapCount = n(row, "heap_count"); const rssCount = n(row, "rss_count"); const lagCount = n(row, "lag_count");
      return { t: n(row, "t"), memoriesTotal: nullable(row, "memories_last"), sessionsTotal: nullable(row, "sessions_last"), sessionsActiveAvg: activeCount > 0 ? n(row, "active_sum") / activeCount : null, heapAvgMb: heapCount > 0 ? n(row, "heap_sum") / heapCount : null, heapMaxMb: nullable(row, "heap_max"), rssAvgMb: rssCount > 0 ? n(row, "rss_sum") / rssCount : null, rssMaxMb: nullable(row, "rss_max"), lagAvgMs: lagCount > 0 ? n(row, "lag_sum") / lagCount : null, lagMaxMs: nullable(row, "lag_max"), uptimeSec: nullable(row, "uptime_last"), sampledAvailability: samples > 0 ? n(row, "ok") / samples : null };
    });
  }

  private restartCount(from: number, to: number): number {
    const row = this.db.prepare("SELECT COUNT(*) AS count FROM console_runs WHERE started_at>=? AND started_at<?").get(from, to) as DbRow | undefined;
    return n(row, "count");
  }

  private system(query: ReportQuery): ReportSystemResponse {
    const previousFrom = query.from - (query.to - query.from);
    return { range: { from: query.from, to: query.to, bucketMs: query.bucketMs }, series: this.systemSeries(query.from, query.to, query.bucketMs), restartCount: this.restartCount(query.from, query.to), previousRestartCount: query.compare && this.hasData(previousFrom, query.from) ? this.restartCount(previousFrom, query.from) : null };
  }

  close(endedAt: number): void {
    this.db.prepare("UPDATE console_runs SET ended_at=? WHERE run_id=?").run(endedAt, this.runId);
    this.db.exec("PRAGMA wal_checkpoint(TRUNCATE)");
    this.db.close();
  }
}
