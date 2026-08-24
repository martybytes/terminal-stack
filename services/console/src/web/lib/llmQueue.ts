import type { LlmSnapshot } from "../../shared/types";

export interface LlmQueueMetrics {
  exactCalls: boolean;
  completedCalls: number;
  failedCalls: number;
  averageProviderLatencyMs: number | null;
  averageQueueWaitMs: number | null;
  averageProviderGateWaitMs: number | null;
  averageJobRuntimeMs: number | null;
}

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

export function deriveLlmQueueMetrics(
  snapshot: LlmSnapshot,
  now = Date.now(),
): LlmQueueMetrics {
  const cutoff = now - snapshot.windowMs;
  const completedCalls = snapshot.calls.filter(
    (call) =>
      call.status === "completed" &&
      call.completedAt !== null &&
      call.completedAt >= cutoff,
  );
  const exactCalls = snapshot.calls.length > 0;
  const fallbackCalls = snapshot.functions.reduce(
    (total, summary) => total + summary.recentCalls,
    0,
  );
  const fallbackFailures = snapshot.functions.reduce(
    (total, summary) => total + summary.recentFailures,
    0,
  );
  const fallbackLatencyTotal = snapshot.functions.reduce(
    (total, summary) => total + summary.recentAvgLatencyMs * summary.recentCalls,
    0,
  );
  const startedJobs = snapshot.jobs.filter(
    (job) => job.startedAt !== null && job.startedAt >= cutoff,
  );
  const finishedJobs = snapshot.jobs.filter(
    (job) =>
      job.startedAt !== null &&
      job.completedAt !== null &&
      job.completedAt >= cutoff,
  );

  return {
    exactCalls,
    completedCalls: exactCalls ? completedCalls.length : fallbackCalls,
    failedCalls: exactCalls
      ? completedCalls.filter((call) => call.outcome !== "success").length
      : fallbackFailures,
    averageProviderLatencyMs: exactCalls
      ? average(
          completedCalls
            .map((call) => call.providerLatencyMs)
            .filter((value): value is number => value !== null),
        )
      : fallbackCalls > 0
        ? fallbackLatencyTotal / fallbackCalls
        : null,
    averageQueueWaitMs: average(
      startedJobs.map((job) => Math.max(0, job.startedAt! - job.queuedAt)),
    ),
    averageProviderGateWaitMs: average(
      completedCalls.map((call) => call.providerGateWaitMs),
    ),
    averageJobRuntimeMs: average(
      finishedJobs.map((job) => Math.max(0, job.completedAt! - job.startedAt!)),
    ),
  };
}
