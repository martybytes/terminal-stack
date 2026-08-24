import assert from "node:assert/strict";
import test from "node:test";
import {
  buildProjectCostsUrl,
  conservativeBillingNextAllowedAt,
  parseRateLimitDurationMs,
} from "../src/server/billing.js";

test("project cost requests cannot fall back to API-key or organization-wide scope", () => {
  const url = buildProjectCostsUrl(1_000, 86_401_000, "proj_agentmemory", "next-page");
  assert.equal(url.pathname, "/v1/organization/costs");
  assert.deepEqual(url.searchParams.getAll("project_ids"), ["proj_agentmemory"]);
  assert.deepEqual(url.searchParams.getAll("group_by"), ["project_id"]);
  assert.equal(url.searchParams.has("api_key_ids"), false);
  assert.equal(url.searchParams.get("bucket_width"), "1d");
  assert.equal(url.searchParams.get("page"), "next-page");
});

test("rate-limit cooldown doubles provider windows and never drops below two hours", () => {
  assert.equal(parseRateLimitDurationMs("1h30m"), 5_400_000);
  const now = 1_000_000;
  const short = new Response(null, { headers: { "retry-after": "60", "x-ratelimit-reset-requests": "5m" } });
  assert.equal(conservativeBillingNextAllowedAt(short, now), now + 2 * 60 * 60_000);
  const long = new Response(null, { headers: { "retry-after": "3h" } });
  assert.equal(conservativeBillingNextAllowedAt(long, now), now + 6 * 60 * 60_000);
});
