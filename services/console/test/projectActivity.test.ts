import assert from "node:assert/strict";
import test from "node:test";
import { ProjectActivityTracker, PROJECT_WINDOW_MS } from "../src/server/projectActivity.js";
import type { RequestRecord, SessionSummary } from "../src/shared/types.js";

function request(
  id: number,
  ts: number,
  project: string | null,
  method: string,
  agent: string | null,
  status = 200,
  durMs = 20,
): RequestRecord {
  return {
    id,
    ts,
    project,
    method,
    agent,
    status,
    durMs,
    path: "/agentmemory/test",
    route: "/agentmemory/test",
    operation: null,
    reqBytes: 0,
    resBytes: 0,
  };
}

function session(
  id: string,
  project: string,
  agent: string | null,
  lastActiveAt: number,
): SessionSummary {
  return {
    id,
    project,
    agent,
    lastActiveAt,
    startedAt: lastActiveAt - 1_000,
    observationCount: 1,
    active: false,
  };
}

test("builds a rolling per-project snapshot and retains idle session projects", () => {
  const now = Date.now();
  const tracker = new ProjectActivityTracker();
  const recent = [
    request(1, now - 40_000, "alpha", "GET", "claude", 200, 10),
    request(2, now - 8_000, "alpha", "POST", "codex", 503, 80),
    request(3, now - 2_000, "alpha", "PATCH", null, 200, 30),
    request(4, now - 1_000, null, "GET", "codex"),
  ];
  for (const item of recent) tracker.record(item);

  const result = tracker.snapshot(
    [session("s1", "alpha", "cursor", now - 30_000), session("s2", "idle", "codex", now - 3_600_000)],
    recent,
    4,
    now,
  );

  assert.equal(result.windowMs, PROJECT_WINDOW_MS);
  assert.equal(result.latestRequestId, 4);
  assert.deepEqual(result.projects.map((project) => project.project), ["alpha", "idle"]);

  const alpha = result.projects[0];
  assert.equal(alpha.requestCount, 3);
  assert.equal(alpha.requestsPerMinute, 3);
  assert.equal(alpha.errorCount, 1);
  assert.deepEqual(alpha.methods, { get: 1, post: 1, put: 0, delete: 0, other: 1 });
  assert.deepEqual(alpha.intents, { lookup: 1, write: 2, health: 0, admin: 0, other: 0 });
  assert.deepEqual(alpha.agents, { claude: 1, codex: 1, cursor: 0, unknown: 1 });
  assert.equal(alpha.p95Ms, 80);
  assert.equal(alpha.lastAgent, "cursor");
  assert.equal(alpha.buckets.length, 15);
  assert.equal(
    alpha.buckets.reduce(
      (total, bucket) => total + Object.values(bucket.methods).reduce((sum, count) => sum + count, 0),
      0,
    ),
    3,
  );

  const idle = result.projects[1];
  assert.equal(idle.requestCount, 0);
  assert.equal(idle.lastAgent, "codex");
  assert.equal(idle.lastActivityAt, now - 3_600_000);
});

test("excludes expired activity from counts while keeping its last activity time", () => {
  const now = Date.now();
  const old = request(1, now - PROJECT_WINDOW_MS - 10_000, "old-project", "DELETE", "cursor", 200, 5);
  const tracker = new ProjectActivityTracker();
  tracker.record(old);

  const result = tracker.snapshot([], [old], 1, now);
  assert.equal(result.projects.length, 1);
  assert.equal(result.projects[0].requestCount, 0);
  assert.equal(result.projects[0].methods.delete, 0);
  assert.equal(result.projects[0].intents.write, 0);
  assert.equal(result.projects[0].lastRequestAt, old.ts + old.durMs);
});
