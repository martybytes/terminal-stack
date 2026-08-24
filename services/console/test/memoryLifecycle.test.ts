import assert from "node:assert/strict";
import test from "node:test";
import { requestLifecycle } from "../src/shared/memoryLifecycle.js";

function stage(method: string, path: string, operation: string | null = null) {
  return requestLifecycle({ method, path, operation });
}

test("classifies the agent memory lifecycle independently of HTTP verbs", () => {
  assert.equal(stage("POST", "/agentmemory/session/start"), "session_start");
  assert.equal(stage("POST", "/agentmemory/context"), "context_recall");
  assert.equal(stage("POST", "/agentmemory/enrich"), "file_enrichment");
  assert.equal(stage("POST", "/agentmemory/search"), "manual_search");
  assert.equal(stage("POST", "/agentmemory/observe"), "observation_capture");
  assert.equal(stage("POST", "/agentmemory/remember"), "memory_save");
  assert.equal(stage("POST", "/agentmemory/session/end"), "session_end");
});

test("uses the bounded MCP operation name as the lifecycle source", () => {
  assert.equal(stage("POST", "/agentmemory/mcp/call", "memory_recall"), "manual_search");
  assert.equal(stage("POST", "/agentmemory/mcp/call", "memory_save"), "memory_save");
  assert.equal(stage("POST", "/agentmemory/mcp/call", "memory_consolidate"), "consolidate");
  assert.equal(stage("POST", "/agentmemory/mcp/call"), "other");
});
