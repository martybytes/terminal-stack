import assert from "node:assert/strict";
import test from "node:test";
import { Readable } from "node:stream";
import {
  REQUEST_METADATA_BODY_MAX,
  createRequestMetadataState,
  resolvedRequestMetadata,
  tapJsonRequestMetadata,
} from "../src/server/requestMetadata.js";
import { store } from "../src/server/observations.js";

async function runTap(
  bodyChunks: Array<string | Buffer>,
  options: {
    url?: string;
    contentType?: string;
    contentEncoding?: string;
    contentLength?: string;
  } = {},
) {
  const state = createRequestMetadataState(options.url ?? "/agentmemory/observe");
  const source = Readable.from(bodyChunks.map((chunk) => (Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))));
  const tapped = tapJsonRequestMetadata(source, state, {
    contentType: options.contentType ?? "application/json; charset=utf-8",
    contentEncoding: options.contentEncoding,
    contentLength: options.contentLength,
  });
  const forwarded: Buffer[] = [];
  for await (const chunk of tapped) forwarded.push(Buffer.from(chunk));
  return {
    forwarded: Buffer.concat(forwarded),
    metadata: resolvedRequestMetadata(state),
  };
}

test("extracts exact body metadata and forwards chunked bytes unchanged", async () => {
  const chunks = [
    '{"project":"agent',
    '007memory","sessionId":"ses_123","data":{"content":"héllo"}}',
  ];
  const result = await runTap(chunks, {
    url: "/agentmemory/observe?project=query-project&sessionId=query-session",
  });

  assert.deepEqual(result.metadata, {
    project: "agent007memory",
    sessionId: "ses_123",
    operation: null,
    tokenBudget: null,
  });
  assert.deepEqual(result.forwarded, Buffer.from(chunks.join("")));
});

test("extracts metadata from an MCP arguments envelope", async () => {
  const body = JSON.stringify({
    name: "memory_save",
    arguments: { project: "calibra", session_id: "session-2", content: "decision" },
  });
  const result = await runTap([body], { url: "/agentmemory/mcp/call" });

  assert.deepEqual(result.metadata, { project: "calibra", sessionId: "session-2", operation: "memory_save", tokenBudget: null });
  assert.equal(result.forwarded.toString(), body);
});

test("uses exact query metadata when no body metadata is available", async () => {
  const state = createRequestMetadataState(
    "/agentmemory/observations?project=docker-local&session_id=session%203",
  );
  assert.deepEqual(resolvedRequestMetadata(state), {
    project: "docker-local",
    sessionId: "session 3",
    operation: null,
    tokenBudget: null,
  });
});

test("ignores malformed, compressed, and oversized bodies", async () => {
  const malformed = await runTap(["{not-json"], { url: "/agentmemory/observe" });
  assert.deepEqual(malformed.metadata, { project: null, sessionId: null, operation: null, tokenBudget: null });

  const compressed = await runTap([JSON.stringify({ project: "hidden" })], {
    contentEncoding: "gzip",
  });
  assert.deepEqual(compressed.metadata, { project: null, sessionId: null, operation: null, tokenBudget: null });

  const oversizedBody = JSON.stringify({
    project: "must-not-be-inferred",
    content: "x".repeat(REQUEST_METADATA_BODY_MAX),
  });
  const oversized = await runTap([oversizedBody], {
    contentLength: String(Buffer.byteLength(oversizedBody)),
  });
  assert.deepEqual(oversized.metadata, { project: null, sessionId: null, operation: null, tokenBudget: null });
  assert.equal(oversized.forwarded.toString(), oversizedBody);
});

test("discards a chunked body after it crosses the metadata cap", async () => {
  const body = JSON.stringify({
    project: "must-not-be-inferred",
    content: "x".repeat(REQUEST_METADATA_BODY_MAX),
  });
  const midpoint = Math.floor(body.length / 2);
  const result = await runTap([body.slice(0, midpoint), body.slice(midpoint)]);

  assert.deepEqual(result.metadata, { project: null, sessionId: null, operation: null, tokenBudget: null });
  assert.equal(result.forwarded.toString(), body);
});

test("resolves a session-only request from an exact observed pair", async () => {
  store.noteSessionProject("session-cache-test", "intranet-portal");
  store.noteSessionAgent("session-cache-test", "codex");
  assert.equal(await store.projectForSession("session-cache-test"), "intranet-portal");
  assert.equal(await store.agentForSession("session-cache-test"), "codex");
});

test("notifies when request metadata has finished resolving", async () => {
  let resolved = 0;
  const state = createRequestMetadataState("/agentmemory/observe");
  const source = Readable.from([Buffer.from('{"project":"alpha"}')]);
  const tapped = tapJsonRequestMetadata(
    source,
    state,
    { contentType: "application/json" },
    () => resolved++,
  );
  for await (const _chunk of tapped) {
    // Drain the pass-through stream so its flush callback runs.
  }
  assert.equal(resolved, 1);
  assert.equal(resolvedRequestMetadata(state).project, "alpha");
});

test("extracts only bounded numeric retrieval budgets", async () => {
  const body = JSON.stringify({ project: "alpha", token_budget: 2048, query: "private" });
  const result = await runTap([body], { url: "/agentmemory/context?budget=999" });
  assert.equal(result.metadata.tokenBudget, 2048);
  assert.equal(JSON.stringify(result.metadata).includes("private"), false);
});
