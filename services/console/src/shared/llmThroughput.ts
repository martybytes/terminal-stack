import type { LlmCallFamily, LlmCallTelemetry } from "./types.js";

export interface LlmThroughput {
  tokensPerSecond: number | null;
  measuredCalls: number;
  completionTokens: number;
  providerLatencyMs: number;
}

export function llmFamilyForFunction(functionId: string): LlmCallFamily {
  const value = functionId.toLowerCase();
  if (value.includes("compress")) return "compression";
  if (value.includes("summar")) return "summary";
  if (value.includes("graph")) return "graph";
  if (value.includes("consolidat") || value.includes("reflect")) return "consolidation";
  return "other";
}

export function callTokensPerSecond(call: LlmCallTelemetry): number | null {
  if (
    call.status !== "completed" ||
    call.outcome !== "success" ||
    call.completionTokens === null ||
    call.providerLatencyMs === null ||
    call.completionTokens < 0 ||
    call.providerLatencyMs <= 0
  ) return null;
  return call.completionTokens / (call.providerLatencyMs / 1_000);
}

export function llmOutputThroughput(
  calls: LlmCallTelemetry[],
  options: { since?: number; family?: LlmCallFamily } = {},
): LlmThroughput {
  let measuredCalls = 0;
  let completionTokens = 0;
  let providerLatencyMs = 0;
  for (const call of calls) {
    if (options.family && call.family !== options.family) continue;
    if (options.since !== undefined && (call.completedAt === null || call.completedAt < options.since)) continue;
    if (callTokensPerSecond(call) === null) continue;
    measuredCalls++;
    completionTokens += call.completionTokens ?? 0;
    providerLatencyMs += call.providerLatencyMs ?? 0;
  }
  return {
    tokensPerSecond: measuredCalls > 0 && providerLatencyMs > 0
      ? completionTokens / (providerLatencyMs / 1_000)
      : null,
    measuredCalls,
    completionTokens,
    providerLatencyMs,
  };
}
