import assert from "node:assert/strict";
import test from "node:test";
import { LlmActivityTracker } from "../src/server/llmActivity.js";
import type { UpstreamFunctionMetric } from "../src/server/llmActivity.js";

function metric(
  functionId: string,
  totalCalls: number,
  successCount: number,
  failureCount: number,
  avgLatencyMs: number,
  avgQualityScore = 96,
): UpstreamFunctionMetric {
  return {
    functionId,
    totalCalls,
    successCount,
    failureCount,
    avgLatencyMs,
    avgQualityScore,
  };
}

test("uses the first cumulative sample as a baseline", () => {
  const tracker = new LlmActivityTracker();
  const now = Date.now();
  assert.deepEqual(tracker.ingest([metric("mem::compress", 100, 90, 10, 1_000)], now), []);
  const compress = tracker.summaries(now).find((summary) => summary.functionId === "mem::compress")!;
  assert.equal(compress.totalCalls, 100);
  assert.equal(compress.recentCalls, 0);
  assert.equal(compress.buckets.length, 15);
});

test("derives rolling calls, failures, and latency from counter changes", () => {
  const tracker = new LlmActivityTracker();
  const now = Math.floor(Date.now() / 60_000) * 60_000 + 1_000;
  tracker.ingest([metric("mem::compress", 10, 9, 1, 1_000)], now);
  const events = tracker.ingest([metric("mem::compress", 12, 10, 2, 1_500, 97)], now + 5_000);

  assert.equal(events.length, 1);
  assert.equal(events[0].calls, 2);
  assert.equal(events[0].successes, 1);
  assert.equal(events[0].failures, 1);
  assert.equal(events[0].avgLatencyMs, 4_000);

  const compress = tracker.summaries(now + 5_000).find(
    (summary) => summary.functionId === "mem::compress",
  )!;
  assert.equal(compress.recentCalls, 2);
  assert.equal(compress.recentFailures, 1);
  assert.equal(compress.recentAvgLatencyMs, 4_000);
  assert.equal(compress.lastCompletedAt, now + 5_000);
});

test("does not turn a reset cumulative counter into new activity", () => {
  const tracker = new LlmActivityTracker();
  const now = Date.now();
  tracker.ingest([metric("mem::summarize", 20, 18, 2, 900)], now);
  assert.deepEqual(
    tracker.ingest([metric("mem::summarize", 1, 1, 0, 500)], now + 2_000),
    [],
  );
  assert.equal(
    tracker.summaries(now + 2_000).find((summary) => summary.functionId === "mem::summarize")!
      .recentCalls,
    0,
  );
});
