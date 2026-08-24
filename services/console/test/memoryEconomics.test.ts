import assert from "node:assert/strict";
import test from "node:test";
import type { MemoryRequestOutcome, RequestRecord, SessionSummary } from "../src/shared/types.js";
import { memoryEconomicsForRequest, retrievalMode } from "../src/shared/memoryEconomics.js";
import { MemoryTokenEstimator } from "../src/server/memoryTokenEstimator.js";

function outcome(kind: MemoryRequestOutcome["kind"] = "returned"): MemoryRequestOutcome {
  return {
    kind, resultCount: 2, contextBlocks: 2, contextTokens: 80, contextChars: 240,
    topScore: 0.8, projectMatchCount: 2, unscopedResultCount: 0,
    crossProjectResultCount: 0, returnedProject: null, truncated: true,
    reportedTokenBudget: 100, estimatedAvoidedTokensLow: 500,
    estimatedAvoidedTokensHigh: 700, estimateConfidence: "live",
  };
}

function request(lifecycle: RequestRecord["lifecycle"], value = outcome()): RequestRecord {
  return {
    id: 1, ts: 1, method: "POST", path: "/agentmemory/context", route: "/agentmemory/context",
    operation: null, project: "alpha", sessionId: "session-1", agent: "codex", lifecycle,
    requestedTokenBudget: 120, outcome: value, status: 200, durMs: 25, reqBytes: 400, resBytes: 200,
  };
}

test("separates automatic retrieval from manual search economics", () => {
  assert.equal(retrievalMode("session_start"), "automatic");
  assert.equal(retrievalMode("manual_search"), "manual");
  const automatic = memoryEconomicsForRequest(request("context_recall"));
  assert.equal(automatic.automaticAttempts, 1);
  assert.equal(automatic.manualAttempts, 0);
  assert.equal(automatic.estimatedAvoidedTokensLow, 500);
  assert.equal(automatic.truncatedRetrievals, 1);
  assert.equal(automatic.budgetTokens, 100);
  const manual = memoryEconomicsForRequest(request("manual_search"));
  assert.equal(manual.manualAttempts, 1);
  assert.equal(manual.estimatedAvoidedTokensLow, 0);
});

test("models a conservative legacy corpus range without crediting manual search", () => {
  const estimator = new MemoryTokenEstimator();
  estimator.seed([{ project: "alpha", observationCount: 100 } as SessionSummary]);
  estimator.decorate({ lifecycle: "observation_capture", project: "alpha", status: 200, reqBytes: 400, outcome: outcome("stored") });
  const decorated = estimator.decorate({ lifecycle: "context_recall", project: "alpha", status: 200, reqBytes: 100, outcome: outcome() });
  assert.equal(decorated?.estimatedAvoidedTokensLow, 10_020);
  assert.equal(decorated?.estimatedAvoidedTokensHigh, 13_387);
  assert.equal(decorated?.estimateConfidence, "legacy_low");
  const manualOutcome = { ...outcome(), estimatedAvoidedTokensLow: null, estimatedAvoidedTokensHigh: null, estimateConfidence: null };
  const manual = estimator.decorate({ lifecycle: "manual_search", project: "alpha", status: 200, reqBytes: 100, outcome: manualOutcome });
  assert.equal(manual?.estimatedAvoidedTokensLow, null);
});

test("does not model unscoped or cross-project automatic results", () => {
  const estimator = new MemoryTokenEstimator();
  estimator.seed([]);
  estimator.decorate({ lifecycle: "observation_capture", project: "alpha", status: 200, reqBytes: 800, outcome: outcome("stored") });
  const unsafe = { ...outcome(), crossProjectResultCount: 1, estimatedAvoidedTokensLow: null, estimatedAvoidedTokensHigh: null, estimateConfidence: null };
  const decorated = estimator.decorate({ lifecycle: "session_start", project: "alpha", status: 200, reqBytes: 100, outcome: unsafe });
  assert.equal(decorated?.estimatedAvoidedTokensLow, null);
});
