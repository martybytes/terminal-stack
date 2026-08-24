import assert from "node:assert/strict";
import test from "node:test";
import { requestIntent } from "../src/shared/requestIntent.js";

function intent(method: string, path: string, operation: string | null = null) {
  return requestIntent({ method, path, operation });
}

test("separates semantic lookups from HTTP transport methods", () => {
  assert.equal(intent("GET", "/agentmemory/sessions?limit=20"), "lookup");
  assert.equal(intent("POST", "/agentmemory/smart-search"), "lookup");
  assert.equal(intent("POST", "/agentmemory/context"), "lookup");
  assert.equal(intent("POST", "/agentmemory/enrich"), "lookup");
  assert.equal(intent("POST", "/agentmemory/observe"), "write");
  assert.equal(intent("POST", "/agentmemory/remember"), "write");
});

test("uses bounded MCP operation metadata when the route is generic", () => {
  assert.equal(intent("POST", "/agentmemory/mcp/call", "memory_smart_search"), "lookup");
  assert.equal(intent("POST", "/agentmemory/mcp/call", "memory_sessions"), "lookup");
  assert.equal(intent("POST", "/agentmemory/mcp/call", "memory_save"), "write");
  assert.equal(intent("POST", "/agentmemory/mcp/call"), "other");
});

test("keeps health and administrative traffic separate", () => {
  assert.equal(intent("GET", "/agentmemory/livez"), "health");
  assert.equal(intent("GET", "/agentmemory/llm/telemetry?limit=20"), "health");
  assert.equal(intent("GET", "/agentmemory/mcp/tools"), "admin");
  assert.equal(intent("POST", "/agentmemory/admin/graph-migration"), "admin");
});
