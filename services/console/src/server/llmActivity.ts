// Rolling completion activity derived from AgentMemory's cumulative
// functionMetrics counters. The upstream API exposes completions, not prompt
// bodies or in-flight calls, so the tracker intentionally stores only counts,
// latency totals, and timestamps.

import type {
  LlmCallBucket,
  LlmCompletionEvent,
  LlmFunctionSummary,
} from "../shared/types.js";

export const LLM_WINDOW_MS = 15 * 60_000;
const MINUTE_MS = 60_000;
const WINDOW_BUCKETS = LLM_WINDOW_MS / MINUTE_MS;

export interface UpstreamFunctionMetric {
  functionId: string;
  totalCalls: number;
  successCount: number;
  failureCount: number;
  avgLatencyMs: number;
  avgQualityScore: number;
}

interface MutableBucket {
  t: number;
  calls: number;
  successes: number;
  failures: number;
  latencyTotalMs: number;
}

const FUNCTIONS: Array<Pick<LlmFunctionSummary, "functionId" | "label" | "description">> = [
  {
    functionId: "mem::compress",
    label: "Observation compression",
    description: "Turns each raw agent observation into a concise, searchable memory representation.",
  },
  {
    functionId: "mem::summarize",
    label: "Session summarization",
    description: "Rolls a completed session into durable highlights and a higher-level summary.",
  },
];

function finiteNonNegative(value: number): number {
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

export class LlmActivityTracker {
  private readonly previous = new Map<string, UpstreamFunctionMetric>();
  private readonly latest = new Map<string, UpstreamFunctionMetric>();
  private readonly activity = new Map<string, Map<number, MutableBucket>>();
  private readonly lastCompletedAt = new Map<string, number>();
  private nextEventId = 1;

  ingest(metrics: UpstreamFunctionMetric[], now = Date.now()): LlmCompletionEvent[] {
    const events: LlmCompletionEvent[] = [];
    for (const metric of metrics) {
      const clean: UpstreamFunctionMetric = {
        functionId: metric.functionId,
        totalCalls: Math.floor(finiteNonNegative(metric.totalCalls)),
        successCount: Math.floor(finiteNonNegative(metric.successCount)),
        failureCount: Math.floor(finiteNonNegative(metric.failureCount)),
        avgLatencyMs: finiteNonNegative(metric.avgLatencyMs),
        avgQualityScore: finiteNonNegative(metric.avgQualityScore),
      };
      this.latest.set(clean.functionId, clean);
      const previous = this.previous.get(clean.functionId);
      this.previous.set(clean.functionId, clean);
      if (!previous || clean.totalCalls < previous.totalCalls) continue;

      const calls = clean.totalCalls - previous.totalCalls;
      if (calls <= 0) continue;
      const successes = Math.max(0, clean.successCount - previous.successCount);
      const failures = Math.max(0, clean.failureCount - previous.failureCount);
      const currentLatencyTotal = clean.avgLatencyMs * clean.totalCalls;
      const previousLatencyTotal = previous.avgLatencyMs * previous.totalCalls;
      const latencyDelta = Math.max(0, currentLatencyTotal - previousLatencyTotal);
      const avgLatencyMs = latencyDelta > 0 ? latencyDelta / calls : clean.avgLatencyMs;

      const minute = Math.floor(now / MINUTE_MS) * MINUTE_MS;
      let buckets = this.activity.get(clean.functionId);
      if (!buckets) {
        buckets = new Map();
        this.activity.set(clean.functionId, buckets);
      }
      const bucket = buckets.get(minute) ?? {
        t: minute,
        calls: 0,
        successes: 0,
        failures: 0,
        latencyTotalMs: 0,
      };
      bucket.calls += calls;
      bucket.successes += successes;
      bucket.failures += failures;
      bucket.latencyTotalMs += avgLatencyMs * calls;
      buckets.set(minute, bucket);
      this.lastCompletedAt.set(clean.functionId, now);

      events.push({
        id: this.nextEventId++,
        ts: now,
        functionId: clean.functionId,
        calls,
        successes,
        failures,
        avgLatencyMs,
      });
    }
    this.prune(now);
    return events;
  }

  summaries(now = Date.now()): LlmFunctionSummary[] {
    this.prune(now);
    const endMinute = Math.floor(now / MINUTE_MS) * MINUTE_MS;
    return FUNCTIONS.map((definition) => {
      const metric = this.latest.get(definition.functionId);
      const source = this.activity.get(definition.functionId);
      const buckets: LlmCallBucket[] = [];
      let recentCalls = 0;
      let recentSuccesses = 0;
      let recentFailures = 0;
      let recentLatencyTotal = 0;
      for (let i = WINDOW_BUCKETS - 1; i >= 0; i--) {
        const t = endMinute - i * MINUTE_MS;
        const bucket = source?.get(t);
        const calls = bucket?.calls ?? 0;
        const latencyTotal = bucket?.latencyTotalMs ?? 0;
        recentCalls += calls;
        recentSuccesses += bucket?.successes ?? 0;
        recentFailures += bucket?.failures ?? 0;
        recentLatencyTotal += latencyTotal;
        buckets.push({
          t,
          calls,
          successes: bucket?.successes ?? 0,
          failures: bucket?.failures ?? 0,
          avgLatencyMs: calls > 0 ? latencyTotal / calls : 0,
        });
      }
      return {
        ...definition,
        totalCalls: metric?.totalCalls ?? 0,
        successCount: metric?.successCount ?? 0,
        failureCount: metric?.failureCount ?? 0,
        avgLatencyMs: metric?.avgLatencyMs ?? 0,
        avgQualityScore: metric?.avgQualityScore ?? 0,
        recentCalls,
        recentSuccesses,
        recentFailures,
        recentAvgLatencyMs: recentCalls > 0 ? recentLatencyTotal / recentCalls : 0,
        lastCompletedAt: this.lastCompletedAt.get(definition.functionId) ?? null,
        buckets,
      };
    });
  }

  private prune(now: number): void {
    const oldestMinute =
      Math.floor(now / MINUTE_MS) * MINUTE_MS - (WINDOW_BUCKETS - 1) * MINUTE_MS;
    for (const buckets of this.activity.values()) {
      for (const t of buckets.keys()) {
        if (t < oldestMinute) buckets.delete(t);
      }
    }
  }
}
