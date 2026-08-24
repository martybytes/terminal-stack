import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectSummary } from "../src/shared/types.js";
import {
  DEFAULT_REORDER_INTERVAL,
  parseReorderInterval,
  sortProjectNames,
} from "../src/web/lib/projectOrder.js";

function project(name: string, lastActivityAt: number | null): ProjectSummary {
  return {
    project: name,
    lastActivityAt,
    lastRequestAt: null,
    lastAgent: null,
    requestCount: 0,
    requestsPerMinute: 0,
    errorCount: 0,
    p95Ms: 0,
    methods: { get: 0, post: 0, put: 0, delete: 0, other: 0 },
    intents: { lookup: 0, write: 0, health: 0, admin: 0, other: 0 },
    agents: { claude: 0, codex: 0, cursor: 0, unknown: 0 },
    buckets: [],
  };
}

test("sorts projects by latest activity with a stable name tie-breaker", () => {
  assert.deepEqual(
    sortProjectNames([project("zeta", 20), project("beta", 20), project("alpha", null)]),
    ["beta", "zeta", "alpha"],
  );
});

test("accepts only supported persisted reorder values", () => {
  assert.equal(parseReorderInterval("15000"), 15_000);
  assert.equal(parseReorderInterval("manual"), "manual");
  assert.equal(parseReorderInterval("1000"), DEFAULT_REORDER_INTERVAL);
  assert.equal(parseReorderInterval(null), DEFAULT_REORDER_INTERVAL);
});
