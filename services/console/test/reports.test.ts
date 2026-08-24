import assert from "node:assert/strict";
import test from "node:test";
import type { ReportProjectsResponse } from "../src/shared/types.js";
import { parseReportQuery, reportCsv } from "../src/server/reports.js";

test("report ranges select bounded chart resolutions", () => {
  const to = Date.now();
  assert.equal(parseReportQuery("summary", { from: String(to - 3_600_000), to: String(to) }).bucketMs, 60_000);
  assert.equal(parseReportQuery("summary", { from: String(to - 86_400_000), to: String(to) }).bucketMs, 300_000);
  assert.equal(parseReportQuery("summary", { from: String(to - 365 * 86_400_000), to: String(to) }).bucketMs, 86_400_000);
  assert.throws(() => parseReportQuery("summary", { from: String(to), to: String(to - 1) }), /valid/);
  assert.throws(() => parseReportQuery("summary", { from: String(to - 366 * 86_400_000), to: String(to) }), /365 days/);
});

test("CSV export neutralizes spreadsheet formulas in aggregate dimensions", () => {
  const response: ReportProjectsResponse = {
    range: { from: 0, to: 60_000, bucketMs: 60_000 },
    rows: [{ project: "=cmd|' /C calc'!A0", requests: 1, previousRequests: null, errors: 0, errorRate: 0, p95Ms: 10, observations: 0, methods: { get: 1, post: 0, put: 0, delete: 0, other: 0 }, agents: [{ agent: "+codex", count: 1 }] }],
    series: [{ t: 0, requests: 1, errors: 0 }],
  };
  const output = reportCsv("projects", response, null);
  assert.match(output, /'=cmd/);
  assert.match(output, /'\+codex/);
  assert.doesNotMatch(output, /,=cmd/);
});
