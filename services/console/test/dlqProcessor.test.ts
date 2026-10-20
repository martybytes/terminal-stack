import assert from "node:assert/strict";
import test from "node:test";
import { AUTO_BATCH, AUTO_WINDOW_MS, PAUSE_MS, llmHealthy, planAutoRedrive } from "../src/server/dlqProcessor.js";
import type { DlqMessage, DlqProcessorState, LlmCallTelemetry, LlmSnapshot } from "../src/shared/types.js";

const NOW = 1_800_000_000_000;
const HOUR = 60 * 60_000;
const IDLE: DlqProcessorState = { lastRunAt: null, lastRedriven: 0, lastReason: null, pausedUntil: null };
const HEALTHY = { ok: true, reason: "ok" };

function message(id: string, ageMs: number): DlqMessage {
  return { id, family: "compression", failedAt: NOW - ageMs, queuedAt: NOW - ageMs - 90_000, retries: 3, project: null, sessionId: "s", observationId: "o" };
}

function call(outcome: string, providerLatencyMs: number | null, completedAt: number): LlmCallTelemetry {
  return { id: completedAt, status: "completed", outcome, providerLatencyMs, completedAt, family: "compression" } as unknown as LlmCallTelemetry;
}

function llm(calls: LlmCallTelemetry[], over: Partial<LlmSnapshot> = {}): Pick<LlmSnapshot, "upstreamOk" | "circuitBreaker" | "queue" | "calls"> {
  return {
    upstreamOk: true,
    circuitBreaker: { state: "closed", failures: 0, lastFailureAt: null, openedAt: null },
    queue: { name: "agentmemory-llm", depth: 0, consumers: 2, dlqDepth: 3, activeJobs: 0 },
    calls,
    ...over,
  };
}

test("a free, healthy model redrives only dead letters under 24 hours, newest first", () => {
  const plan = planAutoRedrive([message("old", AUTO_WINDOW_MS + HOUR), message("a", 2 * HOUR), message("b", HOUR)], NOW, "local", HEALTHY, IDLE);
  assert.deepEqual(plan.redrive, ["b", "a"]);
});

test("one tick redrives a bounded batch, so a big backlog cannot swamp the live queue", () => {
  const many = Array.from({ length: AUTO_BATCH * 3 }, (_, i) => message(`m${i}`, i * 60_000));
  assert.equal(planAutoRedrive(many, NOW, "local", HEALTHY, IDLE).redrive.length, AUTO_BATCH);
});

test("a paid or unrecognised model never redrives on its own", () => {
  for (const applicability of ["paid", "unknown"] as const) {
    assert.deepEqual(planAutoRedrive([message("a", HOUR)], NOW, applicability, HEALTHY, IDLE).redrive, []);
  }
});

test("an unhealthy model redrives nothing", () => {
  const plan = planAutoRedrive([message("a", HOUR)], NOW, "local", { ok: false, reason: "down" }, IDLE);
  assert.deepEqual(plan.redrive, []);
  assert.equal(plan.pause, false);
});

test("a pause holds until it expires", () => {
  const paused = { ...IDLE, pausedUntil: NOW + 1 };
  assert.deepEqual(planAutoRedrive([message("a", HOUR)], NOW, "local", HEALTHY, paused).redrive, []);
  const expired = { ...IDLE, pausedUntil: NOW - 1 };
  assert.deepEqual(planAutoRedrive([message("a", HOUR)], NOW, "local", HEALTHY, expired).redrive, ["a"]);
});

test("jobs that bounce straight back after a redrive pause the processor", () => {
  const justRan = { ...IDLE, lastRunAt: NOW - 120_000, lastRedriven: 10 };
  assert.equal(planAutoRedrive([message("a", HOUR)], NOW, "local", { ok: false, reason: "failing" }, justRan).pause, true);
  const longAgo = { ...justRan, lastRunAt: NOW - PAUSE_MS - 1 };
  assert.equal(planAutoRedrive([message("a", HOUR)], NOW, "local", { ok: false, reason: "failing" }, longAgo).pause, false);
});

test("health needs a call that reached the provider, not just a success outcome", () => {
  // The outage this exists for logged outcome "success" at 0 ms with no provider configured.
  assert.equal(llmHealthy(llm([call("success", 0, NOW)])).ok, false);
  assert.equal(llmHealthy(llm([call("success", 4_800, NOW)])).ok, true);
});

test("health follows the newest completed call", () => {
  assert.equal(llmHealthy(llm([call("success", 4_800, NOW - 10), call("timeout", null, NOW)])).ok, false);
  assert.equal(llmHealthy(llm([call("timeout", null, NOW - 10), call("success", 4_800, NOW)])).ok, true);
});

test("an open breaker, no consumers, or no calls at all is not healthy", () => {
  const good = [call("success", 4_800, NOW)];
  assert.equal(llmHealthy(llm(good, { circuitBreaker: { state: "open", failures: 3, lastFailureAt: NOW, openedAt: NOW } })).ok, false);
  assert.equal(llmHealthy(llm(good, { queue: { name: "q", depth: 0, consumers: 0, dlqDepth: 1, activeJobs: 0 } })).ok, false);
  assert.equal(llmHealthy(llm([])).ok, false);
});
