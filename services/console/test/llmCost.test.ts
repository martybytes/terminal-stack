import assert from "node:assert/strict";
import test from "node:test";
import { estimateLlmCall } from "../src/server/llmCost.js";

test("prices Luna token categories without double charging cached input", () => {
  const result = estimateLlmCall({ provider: "openai", model: "gpt-5.6-luna", promptTokens: 200_000, cachedPromptTokens: 20_000, cacheWriteTokens: 10_000, completionTokens: 10_000 });
  // 170k normal input + 20k cached + 10k cache-write + 10k output.
  assert.equal(result.nanos, 34_000_000 + 400_000 + 2_500_000 + 12_000_000);
  assert.equal(result.coverage, "priced");
});

test("prices Terra and labels unknown remote models as unpriced", () => {
  assert.deepEqual(estimateLlmCall({ provider: "openai", model: "gpt-5.6-terra", promptTokens: 1_000, cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 100 }), { nanos: 3_200_000, coverage: "priced" });
  assert.deepEqual(estimateLlmCall({ provider: "openai", model: "future-model", promptTokens: 1_000, cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 100 }), { nanos: null, coverage: "unpriced" });
  assert.deepEqual(estimateLlmCall({ provider: "local", model: "llama", promptTokens: 1_000, cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 100 }), { nanos: 0, coverage: "local" });
});

test("applies the published long-context multipliers above 272K input tokens", () => {
  const result = estimateLlmCall({ provider: "openai", model: "gpt-5.6-luna", promptTokens: 300_000, cachedPromptTokens: 0, cacheWriteTokens: 0, completionTokens: 10_000 });
  assert.equal(result.nanos, 300_000 * 200 * 2 + 10_000 * 1_200 * 1.5);
});
