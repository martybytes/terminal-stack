import assert from "node:assert/strict";
import test from "node:test";
import { assessLlmEndpoint, isActiveLocalLlmCall } from "../src/shared/llmEndpoint.js";

test("private vLLM endpoints are local and fee-free", () => {
  const result = assessLlmEndpoint("vLLM", "http://10.30.1.20:8000/v1", "qwen3-8b-awq");
  assert.equal(result.costApplicability, "local");
  assert.equal(result.inferenceActive, true);
});

test("hosted providers remain paid even behind a private gateway", () => {
  assert.equal(assessLlmEndpoint("OpenAI", "http://192.168.1.4/v1", "gpt-5").costApplicability, "paid");
});

test("public self-hostable endpoints stay unknown rather than silently free", () => {
  assert.equal(assessLlmEndpoint("vLLM", "https://inference.example.com/v1", "qwen3").costApplicability, "unknown");
});

test("only calls matching the configured local model are marked fee-free", () => {
  const assessment = assessLlmEndpoint("vLLM", "http://10.30.1.20:8000/v1", "qwen3-8b-awq");
  assert.equal(isActiveLocalLlmCall(assessment, "qwen3-8b-awq", "QWEN3-8B-AWQ"), true);
  assert.equal(isActiveLocalLlmCall(assessment, "qwen3-8b-awq", "gpt-5"), false);
});
