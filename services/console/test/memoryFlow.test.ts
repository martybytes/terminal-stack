import assert from "node:assert/strict";
import test from "node:test";
import { addMemoryFlow, emptyMemoryFlowCounts, memoryFlowForRequest, storageAttempts, storedCount } from "../src/shared/memoryFlow.js";
import type { RequestRecord } from "../src/shared/types.js";

function request(lifecycle: RequestRecord["lifecycle"], kind: NonNullable<RequestRecord["outcome"]>["kind"]): RequestRecord {
  return {
    id: 1, ts: Date.now(), method: "POST", path: "/agentmemory/test", route: "/agentmemory/test",
    operation: null, project: "alpha", sessionId: "s1", agent: "codex", lifecycle,
    outcome: { kind, resultCount: kind === "returned" ? 3 : 0, contextBlocks: kind === "returned" ? 2 : 0,
      contextTokens: kind === "returned" ? 140 : 0, contextChars: null, topScore: null,
      projectMatchCount: kind === "returned" ? 3 : 0, unscopedResultCount: 0,
      crossProjectResultCount: 0, returnedProject: "alpha", truncated: false },
    status: kind === "failed" ? 500 : 200, durMs: 10, reqBytes: 1, resBytes: 1,
  };
}

test("memory flow separates observation and explicit storage outcomes", () => {
  const flow = emptyMemoryFlowCounts();
  addMemoryFlow(flow, memoryFlowForRequest(request("observation_capture", "stored")));
  addMemoryFlow(flow, memoryFlowForRequest(request("memory_save", "failed")));
  assert.equal(storageAttempts(flow), 2);
  assert.equal(storedCount(flow), 1);
  assert.equal(flow.observationStored, 1);
  assert.equal(flow.explicitMemoriesStored, 0);
  assert.equal(flow.storageFailures, 1);
});

test("recall delivery uses all attempts and keeps empty and failed distinct", () => {
  const flow = emptyMemoryFlowCounts();
  addMemoryFlow(flow, memoryFlowForRequest(request("context_recall", "returned")));
  addMemoryFlow(flow, memoryFlowForRequest(request("manual_search", "empty")));
  addMemoryFlow(flow, memoryFlowForRequest(request("session_start", "failed")));
  assert.equal(flow.retrievalAttempts, 3);
  assert.equal(flow.retrievalHits, 1);
  assert.equal(flow.retrievalMisses, 1);
  assert.equal(flow.retrievalFailures, 1);
  assert.equal(flow.contextTokens, 140);
  assert.equal(flow.projectMatches, 3);
});
