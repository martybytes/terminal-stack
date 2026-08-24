import type {
  MemoryEconomicsCounts,
  MemoryEstimateConfidence,
  MemoryRetrievalMode,
  RequestRecord,
} from "./types.js";

export function retrievalMode(stage: RequestRecord["lifecycle"]): MemoryRetrievalMode {
  if (stage === "session_start" || stage === "context_recall" || stage === "file_enrichment") return "automatic";
  if (stage === "manual_search") return "manual";
  return "none";
}

export function emptyMemoryEconomicsCounts(): MemoryEconomicsCounts {
  return {
    automaticAttempts: 0, automaticHits: 0, automaticMisses: 0, automaticFailures: 0,
    automaticUnknown: 0, automaticContextTokens: 0, automaticContextBlocks: 0,
    manualAttempts: 0, manualHits: 0, manualMisses: 0, manualFailures: 0,
    manualUnknown: 0, manualContextTokens: 0, manualContextBlocks: 0,
    capturePayloadBytes: 0, captureSamples: 0, corpusObservations: 0,
    estimatedAvoidedTokensLow: 0, estimatedAvoidedTokensHigh: 0, modeledRetrievals: 0,
    liveEstimateCount: 0, legacyEstimateCount: 0, budgetedRetrievals: 0,
    budgetTokens: 0, truncatedRetrievals: 0, oversizedRetrievals: 0,
    retrievalLatencyTotalMs: 0, scoredRetrievals: 0, topScoreTotal: 0,
  };
}

export function addMemoryEconomics(
  target: MemoryEconomicsCounts,
  source: MemoryEconomicsCounts,
): MemoryEconomicsCounts {
  for (const key of Object.keys(target) as Array<keyof MemoryEconomicsCounts>) target[key] += source[key];
  return target;
}

export function memoryEconomicsForRequest(request: RequestRecord): MemoryEconomicsCounts {
  const counts = emptyMemoryEconomicsCounts();
  if (request.lifecycle === "observation_capture" && request.reqBytes >= 0) {
    counts.capturePayloadBytes = request.reqBytes;
    counts.captureSamples = 1;
  }

  const mode = retrievalMode(request.lifecycle);
  if (mode === "none") return counts;
  const prefix = mode === "automatic" ? "automatic" : "manual";
  counts[`${prefix}Attempts`]++;
  const kind = request.outcome?.kind;
  if (kind === "returned") counts[`${prefix}Hits`]++;
  else if (kind === "empty") counts[`${prefix}Misses`]++;
  else if (kind === "failed") counts[`${prefix}Failures`]++;
  else counts[`${prefix}Unknown`]++;
  counts[`${prefix}ContextTokens`] += request.outcome?.contextTokens ?? 0;
  counts[`${prefix}ContextBlocks`] += request.outcome?.contextBlocks ?? 0;
  counts.retrievalLatencyTotalMs += Math.max(0, request.durMs);

  const budget = request.outcome?.reportedTokenBudget ?? request.requestedTokenBudget;
  if (budget !== null && budget > 0) {
    counts.budgetedRetrievals++;
    counts.budgetTokens += budget;
    if ((request.outcome?.contextTokens ?? 0) > budget) counts.oversizedRetrievals++;
  }
  if (request.outcome?.truncated === true) counts.truncatedRetrievals++;
  if (request.outcome?.topScore !== null && request.outcome?.topScore !== undefined) {
    counts.scoredRetrievals++;
    counts.topScoreTotal += request.outcome.topScore;
  }
  if (mode === "automatic" && request.outcome?.estimatedAvoidedTokensLow !== null && request.outcome?.estimatedAvoidedTokensLow !== undefined) {
    counts.estimatedAvoidedTokensLow += request.outcome.estimatedAvoidedTokensLow;
    counts.estimatedAvoidedTokensHigh += request.outcome.estimatedAvoidedTokensHigh ?? request.outcome.estimatedAvoidedTokensLow;
    counts.modeledRetrievals++;
    if (request.outcome.estimateConfidence === "legacy_low") counts.legacyEstimateCount++;
    else if (request.outcome.estimateConfidence === "live") counts.liveEstimateCount++;
  }
  return counts;
}

export function estimateLabel(counts: MemoryEconomicsCounts): MemoryEstimateConfidence {
  if (counts.legacyEstimateCount > 0) return "legacy_low";
  if (counts.liveEstimateCount > 0) return "live";
  return "insufficient";
}

export function averageRetrievalLatency(counts: MemoryEconomicsCounts): number | null {
  const attempts = counts.automaticAttempts + counts.manualAttempts;
  return attempts > 0 ? counts.retrievalLatencyTotalMs / attempts : null;
}

export function averageTopScore(counts: MemoryEconomicsCounts): number | null {
  return counts.scoredRetrievals > 0 ? counts.topScoreTotal / counts.scoredRetrievals : null;
}
