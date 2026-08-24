import assert from "node:assert/strict";
import test from "node:test";
import { outcomeFromJson } from "../src/server/responseMetadata.js";
import { maskOpenAiKey } from "../src/server/keyHints.js";

test("keeps retrieval counts and project integrity without retaining content", () => {
  const outcome = outcomeFromJson({
    results: [
      { id: "a", project: "agent007memory", score: 0.91, content: "must never be copied" },
      { id: "b", project: null, score: 0.4, content: "also private" },
      { id: "c", project: "another-project", score: 0.2 },
    ],
  }, "manual_search", "agent007memory");
  assert.deepEqual(outcome, {
    kind: "returned", resultCount: 3, contextBlocks: null, contextTokens: null,
    contextChars: null, topScore: 0.91, projectMatchCount: 1,
    unscopedResultCount: 1, crossProjectResultCount: 1,
    returnedProject: null, truncated: null,
    reportedTokenBudget: null, estimatedAvoidedTokensLow: null,
    estimatedAvoidedTokensHigh: null, estimateConfidence: null,
  });
  assert.equal(JSON.stringify(outcome).includes("private"), false);
});

test("extracts MCP response counts and save confirmation", () => {
  const recall = outcomeFromJson({ content: [{ type: "text", text: JSON.stringify({ results: [{ project: "p" }] }) }] }, "manual_search", "p");
  assert.equal(recall?.kind, "returned");
  assert.equal(recall?.projectMatchCount, 1);
  const saved = outcomeFromJson({ memory: { id: "m1", project: "p", content: "private" } }, "memory_save", "p");
  assert.equal(saved?.kind, "stored");
  assert.equal(saved?.returnedProject, "p");
});

test("understands full search rows and their token budget", () => {
  const outcome = outcomeFromJson({ results: [{ observation: { project: "p", narrative: "private" }, score: 0.8 }], tokens_used: 77, tokens_budget: 100, truncated: false }, "manual_search", "p");
  assert.equal(outcome?.kind, "returned");
  assert.equal(outcome?.contextTokens, 77);
  assert.equal(outcome?.projectMatchCount, 1);
  assert.equal(outcome?.reportedTokenBudget, 100);
});

test("OpenAI key masks reveal only a short prefix", () => {
  const raw = "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz";
  const masked = maskOpenAiKey(raw);
  assert.equal(masked, "sk-proj-123456…wxyz");
  assert.equal(masked?.includes("7890abc"), false);
  assert.equal(maskOpenAiKey("OPENAI_API_KEY=sk-proj-secret"), null);
});
