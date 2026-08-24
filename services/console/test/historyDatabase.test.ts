import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { HistoryDatabase } from "../src/server/historyDatabase.js";
import { LATENCY_BOUNDS_MS, minuteBucket, type HistoryBatch } from "../src/server/historyProtocol.js";

const root = mkdtempSync(join(tmpdir(), "agent007memory-history-test-"));
after(() => {
  if (!root.startsWith(tmpdir()) || !root.includes("agent007memory-history-test-")) {
    throw new Error(`refusing to remove unexpected test directory: ${root}`);
  }
  rmSync(root, { recursive: true });
});

function latencyBins(duration: number): number[] {
  const bins = Array(LATENCY_BOUNDS_MS.length + 1).fill(0) as number[];
  const index = LATENCY_BOUNDS_MS.findIndex((bound) => duration <= bound);
  bins[index === -1 ? LATENCY_BOUNDS_MS.length : index] = 1;
  return bins;
}

test("aggregate batches survive restart and are idempotent", () => {
  const path = join(root, "history.sqlite");
  const now = minuteBucket(Date.now());
  const batch: HistoryBatch = {
    id: "batch-1",
    createdAt: now,
    requests: [
      { bucketMs: now - 60_000, project: "terminal-stack", agent: "codex", method: "post", statusClass: "2xx", count: 1, durationTotalMs: 1_800, latencyBins: latencyBins(1_800) },
      { bucketMs: now - 60_000, project: "terminal-stack", agent: "codex", method: "get", statusClass: "5xx", count: 1, durationTotalMs: 400, latencyBins: latencyBins(400) },
    ],
    observations: [{ bucketMs: now - 60_000, project: "terminal-stack", agent: "codex", kind: "raw", observationType: "tool_call", count: 2 }],
    memory: [
      { bucketMs: now - 60_000, project: "terminal-stack", agent: "codex", stage: "manual_search", requestCount: 2, retrievals: 2, hits: 1, misses: 1, unknown: 0, contextTokens: 320, contextBlocks: 2, unscopedResults: 1, crossProjectResults: 0, storageAttempts: 0, stored: 0, storageFailures: 0, retrievalFailures: 0, resultCount: 1, projectMatches: 1, estimatedAvoidedTokensLow: 1_000, estimatedAvoidedTokensHigh: 1_500, modeledRetrievals: 1, legacyEstimateCount: 1 },
      { bucketMs: now - 2 * 86_400_000, project: "terminal-stack", agent: "codex", stage: "context_recall", requestCount: 1, retrievals: 1, hits: 1, misses: 0, unknown: 0, contextTokens: 100, contextBlocks: 1, unscopedResults: 0, crossProjectResults: 0, storageAttempts: 0, stored: 0, storageFailures: 0, retrievalFailures: 0, resultCount: 1, projectMatches: 1, estimatedAvoidedTokensLow: 2_000, estimatedAvoidedTokensHigh: 3_000, modeledRetrievals: 2, legacyEstimateCount: 0 },
      { bucketMs: now - 8 * 86_400_000, project: "terminal-stack", agent: "codex", stage: "context_recall", requestCount: 1, retrievals: 1, hits: 1, misses: 0, unknown: 0, contextTokens: 100, contextBlocks: 1, unscopedResults: 0, crossProjectResults: 0, storageAttempts: 0, stored: 0, storageFailures: 0, retrievalFailures: 0, resultCount: 1, projectMatches: 1, estimatedAvoidedTokensLow: 4_000, estimatedAvoidedTokensHigh: 6_000, modeledRetrievals: 3, legacyEstimateCount: 0 },
    ],
    llm: [{ bucketMs: now - 60_000, functionId: "mem::compress", calls: 2, successes: 1, failures: 1, latencyTotalMs: 2_000 }],
    llmUsage: [
      { callKey: "instance:1", completedAt: now - 30_000, bucketMs: now - 60_000, provider: "openai", model: "gpt-5.6-luna", family: "compression", promptTokens: 100, cachedPromptTokens: 10, cacheWriteTokens: 0, completionTokens: 20, reasoningTokens: 5, totalTokens: 120, estimatedCostNanos: 42_000, pricedCalls: 1, unpricedCalls: 0, throughputMeasuredCalls: 1, throughputCompletionTokens: 20, throughputProviderLatencyMs: 2_000 },
      { callKey: "instance:2", completedAt: now - 20_000, bucketMs: now - 60_000, provider: "vllm", model: "qwen3-8b-awq", family: "summary", promptTokens: 80, cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 15, reasoningTokens: 0, totalTokens: 95, estimatedCostNanos: 0, pricedCalls: 0, unpricedCalls: 0, throughputMeasuredCalls: 1, throughputCompletionTokens: 15, throughputProviderLatencyMs: 1_000 },
    ],
    system: [{ bucketMs: now - 60_000, samples: 2, upstreamOkSamples: 1, memoriesFirst: 10, memoriesLast: 12, sessionsFirst: 3, sessionsLast: 4, sessionsActiveSum: 2, sessionsActiveCount: 2, sessionsActiveMax: 1, heapSumMb: 200, heapCount: 2, heapMaxMb: 110, rssSumMb: 400, rssCount: 2, rssMaxMb: 210, lagSumMs: 6, lagCount: 2, lagMaxMs: 4, uptimeLastSec: 120 }],
  };

  const first = new HistoryDatabase(path, 365, "run-1", now - 120_000);
  first.ingest(batch);
  first.ingest(batch);
  first.ingest({ ...batch, id: "batch-2", requests: [], memory: [], observations: [], llm: [], system: [] });
  first.setBillingScope({ provider: "openai", scopeType: "project", scopeId: "proj-agentmemory", scopeLabel: "Agentmemory" });
  first.recordProviderCosts([{ dayMs: now - 86_400_000, provider: "openai", scopeType: "project", scopeId: "proj-agentmemory", scopeLabel: "Agentmemory", amountNanos: 123_000_000, currency: "usd", syncedAt: now, source: "test" }]);
  const report = first.report({ section: "summary", from: now - 2 * 86_400_000, to: now + 1, bucketMs: 60_000, compare: false });
  assert.ok("current" in report);
  if (!("current" in report)) return;
  assert.equal(report.current.requests, 2);
  assert.equal(report.current.errors, 1);
  assert.equal(report.current.observations, 2);
  assert.equal(report.current.llmCalls, 2);
  assert.equal(report.current.memoriesEnd, 12);
  assert.equal(report.current.p95Ms, 2_500);
  assert.equal(report.current.estimatedLlmCostNanos, 42_000);
  assert.equal(report.current.billedProviderCostNanos, 123_000_000);
  const llmReport = first.report({ section: "llm", from: now - 2 * 86_400_000, to: now + 1, bucketMs: 60_000, compare: false });
  assert.ok("usageRows" in llmReport);
  if ("usageRows" in llmReport) {
    const paid = llmReport.usageRows.find((row) => row.model === "gpt-5.6-luna");
    const local = llmReport.usageRows.find((row) => row.model === "qwen3-8b-awq");
    assert.equal(paid?.calls, 1);
    assert.equal(paid?.pricedCalls, 1);
    assert.equal(paid?.localCalls, 0);
    assert.equal(paid?.outputTokensPerSecond, 10);
    assert.equal(local?.calls, 1);
    assert.equal(local?.pricedCalls, 0);
    assert.equal(local?.unpricedCalls, 0);
    assert.equal(local?.localCalls, 1);
    assert.equal(local?.outputTokensPerSecond, 15);
    assert.equal(llmReport.billedCostNanos, 123_000_000);
    assert.equal(llmReport.providerCosts[0]?.scopeLabel, "Agentmemory");
  }
  const memoryReport = first.report({ section: "memory", from: now - 3_600_000, to: now + 1, bucketMs: 60_000, compare: false, project: "terminal-stack", agent: "codex" });
  assert.ok("current" in memoryReport && "projects" in memoryReport);
  if ("current" in memoryReport && "projects" in memoryReport) {
    assert.equal(memoryReport.current.retrievals, 2);
    assert.equal(memoryReport.current.hits, 1);
    assert.equal(memoryReport.current.hitRate, 0.5);
    assert.equal(memoryReport.current.contextTokens, 320);
    assert.equal(memoryReport.projects[0]?.unscopedResults, 1);
  }
  const avoided = first.contextAvoidedHistory(now);
  assert.equal(avoided.past24Hours.estimatedAvoidedTokensLow, 1_000);
  assert.equal(avoided.past7Days.estimatedAvoidedTokensLow, 3_000);
  assert.equal(avoided.allTracked.estimatedAvoidedTokensLow, 7_000);
  assert.equal(avoided.allTracked.estimatedAvoidedTokensHigh, 10_500);
  assert.equal(avoided.allTracked.modeledRetrievals, 6);
  assert.equal(avoided.trackingSince, now - 8 * 86_400_000);
  first.close(now);

  const second = new HistoryDatabase(path, 365, "run-2", now);
  const projects = second.report({ section: "projects", from: now - 3_600_000, to: now + 1, bucketMs: 60_000, compare: false, project: "terminal-stack", agent: "codex" });
  assert.ok("rows" in projects);
  if (!("rows" in projects)) return;
  assert.equal(projects.rows[0]?.requests, 2);
  assert.equal(projects.rows[0]?.methods.get, 1);
  assert.equal(projects.rows[0]?.methods.post, 1);
  second.close(now + 1);

  const inspect = new DatabaseSync(path, { readOnly: true });
  const columns = inspect.prepare("PRAGMA table_info(request_minute)").all().map((row) => String(row.name));
  for (const forbidden of ["path", "route", "body", "prompt", "response", "session_id", "request_id"]) {
    assert.equal(columns.includes(forbidden), false);
  }
  inspect.close();
});

test("schema migration preserves legacy key costs but reports only the active project", () => {
  const path = join(root, "billing-scope-migration.sqlite");
  const now = minuteBucket(Date.now());
  const seed = new HistoryDatabase(path, 365, "scope-seed", now);
  seed.close(now);
  const legacy = new DatabaseSync(path);
  legacy.exec(`
    DROP TABLE provider_cost_day;
    DROP TABLE billing_sync_state;
    DROP TABLE billing_active_scope;
    CREATE TABLE provider_cost_day (
      day_ms INTEGER NOT NULL, provider TEXT NOT NULL, api_key_id TEXT NOT NULL,
      amount_nanos INTEGER NOT NULL, currency TEXT NOT NULL, synced_at INTEGER NOT NULL, source TEXT NOT NULL,
      PRIMARY KEY (day_ms,provider,api_key_id)
    ) WITHOUT ROWID;
    CREATE TABLE billing_sync_state (
      provider TEXT PRIMARY KEY, last_sync_at INTEGER, last_success_at INTEGER, last_error TEXT
    ) WITHOUT ROWID;
    PRAGMA user_version=2;
  `);
  legacy.prepare("INSERT INTO provider_cost_day VALUES (?,?,?,?,?,?,?)")
    .run(now - 86_400_000, "openai", "legacy-key", 900_000_000, "usd", now, "legacy");
  legacy.close();

  const database = new HistoryDatabase(path, 365, "scope-project", now);
  database.setBillingScope({ provider: "openai", scopeType: "project", scopeId: "proj-agentmemory", scopeLabel: "Agentmemory" });
  database.recordProviderCosts([{ dayMs: now - 86_400_000, provider: "openai", scopeType: "project", scopeId: "proj-agentmemory", scopeLabel: "Agentmemory", amountNanos: 125_000_000, currency: "usd", syncedAt: now, source: "test" }]);
  const report = database.report({ section: "llm", from: now - 2 * 86_400_000, to: now + 1, bucketMs: 86_400_000, compare: false });
  assert.ok("providerCosts" in report);
  if ("providerCosts" in report) {
    assert.equal(report.billedCostNanos, 125_000_000);
    assert.equal(report.providerCosts.length, 1);
    assert.equal(report.providerCosts[0]?.scopeId, "proj-agentmemory");
  }
  database.close(now + 1);

  const inspect = new DatabaseSync(path, { readOnly: true });
  const legacyRows = inspect.prepare("SELECT COUNT(*) AS count FROM provider_cost_day WHERE scope_type='api_key'").get() as { count: number };
  assert.equal(legacyRows.count, 1);
  inspect.close();
});

test("retention removes minute aggregates older than the configured window", () => {
  const path = join(root, "retention.sqlite");
  const now = minuteBucket(Date.now());
  const database = new HistoryDatabase(path, 1, "retention-run", now);
  database.ingest({ id: "old", createdAt: now, requests: [{ bucketMs: now - 2 * 86_400_000, project: "old", agent: "unknown", method: "get", statusClass: "2xx", count: 1, durationTotalMs: 10, latencyBins: latencyBins(10) }], observations: [], llm: [], llmUsage: [], system: [] });
  database.prune(now);
  assert.equal(database.meta(1).earliestTs, null);
  database.close(now + 1);
});
