import assert from "node:assert/strict";
import test from "node:test";
import { fmtCompactRange } from "../src/web/lib/format";

test("formats dashboard ranges with one shared suffix", () => {
  assert.equal(fmtCompactRange(3_810_000, 5_090_000), "3.8–5.1M");
  assert.equal(fmtCompactRange(8_040_000, 10_700_000), "8–10.7M");
  assert.equal(fmtCompactRange(512_000, 890_000), "512–890K");
  assert.equal(fmtCompactRange(1_200_000_000, 2_300_000_000), "1.2–2.3G");
});

test("keeps small ranges exact and rejects incomplete values", () => {
  assert.equal(fmtCompactRange(1_234, 9_876), "1,234–9,876");
  assert.equal(fmtCompactRange(null, 9_876), "—");
  assert.equal(fmtCompactRange(1_234, Number.NaN), "—");
});
