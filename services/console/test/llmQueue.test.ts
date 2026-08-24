import assert from "node:assert/strict";
import test from "node:test";
import { deriveLlmQueueMetrics } from "../src/web/lib/llmQueue.js";
import type { LlmSnapshot } from "../src/shared/types.js";

function snapshot(): LlmSnapshot {
  return {
    ts: 1_000_000,
    windowMs: 900_000,
    upstreamOk: true,
    version: "test",
    config: {
      provider: "test",
      endpointLabel: null,
      model: null,
      endpoint: null,
      timeoutMs: null,
      maxTokens: null,
      summarizeConcurrency: null,
      providerConcurrency: 1,
      recoveryBatchSize: 25,
      graphBatchSize: null,
      embeddingProvider: null,
    },
    circuitBreaker: { state: "closed", failures: 0, lastFailureAt: null, openedAt: null },
    features: [],
    functions: [],
    queue: { name: "agentmemory-llm", depth: 2, consumers: 2, dlqDepth: 1, activeJobs: 1 },
    calls: [
      {
        id: 1,
        jobId: "job-1",
        family: "compression",
        status: "completed",
        outcome: "success",
        model: "test",
        promptChars: 100,
        estimatedPromptTokens: 25,
        promptTokens: 25,
        completionTokens: 5,
        totalTokens: 30,
        queuedAt: 990_000,
        startedAt: 995_000,
        completedAt: 999_000,
        queueWaitMs: 5_000,
        providerGateWaitMs: 2_000,
        providerLatencyMs: 4_000,
      },
      {
        id: 2,
        jobId: "job-2",
        family: "graph",
        status: "completed",
        outcome: "timeout",
        model: "test",
        promptChars: 200,
        estimatedPromptTokens: 50,
        promptTokens: null,
        completionTokens: null,
        totalTokens: null,
        queuedAt: 991_000,
        startedAt: 998_000,
        completedAt: 1_000_000,
        queueWaitMs: 7_000,
        providerGateWaitMs: 1_000,
        providerLatencyMs: 2_000,
      },
      {
        id: 3,
        jobId: "job-3",
        family: "summary",
        status: "running",
        outcome: null,
        model: "test",
        promptChars: 300,
        estimatedPromptTokens: 75,
        promptTokens: null,
        completionTokens: null,
        totalTokens: null,
        queuedAt: 999_000,
        startedAt: 1_000_000,
        completedAt: null,
        queueWaitMs: 1_000,
        providerGateWaitMs: 500,
        providerLatencyMs: null,
      },
    ],
    jobs: [
      {
        id: "job-1",
        family: "compression",
        status: "completed",
        attempt: 1,
        queuedAt: 990_000,
        startedAt: 992_000,
        completedAt: 999_000,
        outcome: "success",
      },
      {
        id: "job-2",
        family: "graph",
        status: "completed",
        attempt: 1,
        queuedAt: 991_000,
        startedAt: 995_000,
        completedAt: 1_000_000,
        outcome: "failure",
      },
    ],
  };
}

test("derives separate durable queue, provider gate, and job timing averages", () => {
  const metrics = deriveLlmQueueMetrics(snapshot(), 1_000_000);

  assert.equal(metrics.exactCalls, true);
  assert.equal(metrics.completedCalls, 2);
  assert.equal(metrics.failedCalls, 1);
  assert.equal(metrics.averageProviderLatencyMs, 3_000);
  assert.equal(metrics.averageQueueWaitMs, 3_000);
  assert.equal(metrics.averageProviderGateWaitMs, 1_500);
  assert.equal(metrics.averageJobRuntimeMs, 6_000);
});

test("excludes running calls from completed and failed counts", () => {
  const value = snapshot();
  value.calls = value.calls.filter((call) => call.status === "running");
  const metrics = deriveLlmQueueMetrics(value, 1_000_000);

  assert.equal(metrics.completedCalls, 0);
  assert.equal(metrics.failedCalls, 0);
  assert.equal(metrics.averageProviderLatencyMs, null);
  assert.equal(metrics.averageProviderGateWaitMs, null);
});
