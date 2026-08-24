import { isRetrievalStage, isStorageStage } from "./memoryLifecycle.js";
import type { MemoryFlowCounts, RequestRecord } from "./types.js";

export function emptyMemoryFlowCounts(): MemoryFlowCounts {
  return {
    observationAttempts: 0, observationStored: 0, explicitMemoryAttempts: 0, explicitMemoriesStored: 0,
    storageFailures: 0, storageUnknown: 0, retrievalAttempts: 0, retrievalHits: 0,
    retrievalMisses: 0, retrievalFailures: 0, retrievalUnknown: 0, contextTokens: 0,
    contextBlocks: 0, resultCount: 0, projectMatches: 0, unscopedResults: 0, crossProjectResults: 0,
  };
}

export function memoryFlowForRequest(request: RequestRecord): MemoryFlowCounts {
  const flow = emptyMemoryFlowCounts();
  if (isStorageStage(request.lifecycle)) {
    if (request.lifecycle === "observation_capture") flow.observationAttempts++;
    else flow.explicitMemoryAttempts++;
    if (request.outcome?.kind === "stored" || request.outcome?.kind === "accepted") {
      if (request.lifecycle === "observation_capture") flow.observationStored++;
      else flow.explicitMemoriesStored++;
    } else if (request.outcome?.kind === "failed") flow.storageFailures++;
    else flow.storageUnknown++;
  }
  if (isRetrievalStage(request.lifecycle)) {
    flow.retrievalAttempts++;
    if (request.outcome?.kind === "returned") flow.retrievalHits++;
    else if (request.outcome?.kind === "empty") flow.retrievalMisses++;
    else if (request.outcome?.kind === "failed") flow.retrievalFailures++;
    else flow.retrievalUnknown++;
  }
  flow.contextTokens += request.outcome?.contextTokens ?? 0;
  flow.contextBlocks += request.outcome?.contextBlocks ?? 0;
  flow.resultCount += request.outcome?.resultCount ?? 0;
  flow.projectMatches += request.outcome?.projectMatchCount ?? 0;
  flow.unscopedResults += request.outcome?.unscopedResultCount ?? 0;
  flow.crossProjectResults += request.outcome?.crossProjectResultCount ?? 0;
  return flow;
}

export function addMemoryFlow(target: MemoryFlowCounts, source: MemoryFlowCounts): MemoryFlowCounts {
  for (const key of Object.keys(target) as Array<keyof MemoryFlowCounts>) target[key] += source[key];
  return target;
}

export function storedCount(flow: MemoryFlowCounts): number {
  return flow.observationStored + flow.explicitMemoriesStored;
}

export function storageAttempts(flow: MemoryFlowCounts): number {
  return flow.observationAttempts + flow.explicitMemoryAttempts;
}
