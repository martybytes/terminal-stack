import assert from "node:assert/strict";
import test from "node:test";
import type { LlmCallTelemetry } from "../src/shared/types.js";
import { callTokensPerSecond, llmFamilyForFunction, llmOutputThroughput } from "../src/shared/llmThroughput.js";

function call(overrides: Partial<LlmCallTelemetry> = {}): LlmCallTelemetry {
  return {
    id: 1, jobId: null, family: "summary", status: "completed", outcome: "success",
    model: "qwen", promptChars: 100, estimatedPromptTokens: 25, promptTokens: 25,
    cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 40, reasoningTokens: 0,
    totalTokens: 65, provider: "vllm", project: "test", sessionId: null,
    estimatedCostNanos: 0, costCoverage: "local", queuedAt: 1, startedAt: 2,
    completedAt: 2_002, queueWaitMs: 1, providerGateWaitMs: 0, providerLatencyMs: 2_000,
    ...overrides,
  };
}

test("calculates effective output throughput from exact successful calls", () => {
  assert.equal(callTokensPerSecond(call()), 20);
  const result = llmOutputThroughput([
    call(),
    call({ id: 2, completionTokens: 20, providerLatencyMs: 1_000 }),
    call({ id: 3, outcome: "error", completionTokens: 999 }),
  ]);
  assert.equal(result.measuredCalls, 2);
  assert.equal(result.completionTokens, 60);
  assert.equal(result.providerLatencyMs, 3_000);
  assert.equal(result.tokensPerSecond, 20);
});

test("excludes missing usage, failures, old calls, and other families", () => {
  const result = llmOutputThroughput([
    call({ completionTokens: null }),
    call({ id: 2, family: "compression", completedAt: 10_000 }),
    call({ id: 3, completedAt: 100 }),
  ], { family: "summary", since: 1_000 });
  assert.equal(result.tokensPerSecond, null);
  assert.equal(result.measuredCalls, 0);
  assert.equal(llmFamilyForFunction("mem::compress"), "compression");
  assert.equal(llmFamilyForFunction("reflect_and_consolidate"), "consolidation");
});
