import assert from "node:assert/strict";
import test from "node:test";
import { Readable } from "node:stream";
import {
  attributedPath,
  injectAgentId,
  isAgentPersistenceRoute,
} from "../src/server/requestAgent.js";

async function inject(chunks: string[], agent: "claude" | "codex" | "cursor"): Promise<string> {
  const source = Readable.from(chunks.map((chunk) => Buffer.from(chunk)));
  const output: Buffer[] = [];
  for await (const chunk of injectAgentId(source, agent)) output.push(Buffer.from(chunk));
  return Buffer.concat(output).toString("utf8");
}

test("extracts known client tags and preserves the canonical upstream path", () => {
  assert.deepEqual(attributedPath("/_agent/claude/agentmemory/session/start?x=1"), {
    agent: "claude",
    path: "/agentmemory/session/start?x=1",
  });
  assert.deepEqual(attributedPath("/_agent/codex/agentmemory/remember"), {
    agent: "codex",
    path: "/agentmemory/remember",
  });
  assert.deepEqual(attributedPath("/_agent/cursor"), { agent: "cursor", path: "/" });
});

test("leaves untagged and unknown-tag paths unchanged", () => {
  assert.deepEqual(attributedPath("/agentmemory/livez"), {
    agent: null,
    path: "/agentmemory/livez",
  });
  assert.deepEqual(attributedPath("/_agent/other/agentmemory/livez"), {
    agent: null,
    path: "/_agent/other/agentmemory/livez",
  });
});

test("identifies only upstream writes that persist agentId", () => {
  assert.equal(isAgentPersistenceRoute("/agentmemory/session/start"), true);
  assert.equal(isAgentPersistenceRoute("/agentmemory/remember?source=mcp"), true);
  assert.equal(isAgentPersistenceRoute("/agentmemory/observe"), false);
  assert.equal(isAgentPersistenceRoute("/agentmemory/search"), false);
});

test("injects agentId into streaming JSON objects without retaining the body", async () => {
  assert.equal(
    await inject(['{"sessionId":"s1",', '"project":"p"}'], "codex"),
    '{"agentId":"codex","sessionId":"s1","project":"p"}',
  );
  assert.equal(await inject(["{", "}"], "claude"), '{"agentId":"claude"}');
  assert.equal(
    await inject([" \r\n{  ", '"content":"private"}'], "cursor"),
    ' \r\n{  "agentId":"cursor","content":"private"}',
  );
});

test("passes non-object payloads through unchanged", async () => {
  assert.equal(await inject(["[1,2,3]"], "codex"), "[1,2,3]");
  assert.equal(await inject(["null"], "codex"), "null");
});
