import { readFileSync } from "node:fs";
import type { LlmKeyHint } from "../shared/types.js";
import { config } from "./config.js";

export function maskOpenAiKey(value: string): string | null {
  const key = value.trim();
  if (!key.startsWith("sk-") || key.length < 10 || /[\r\n=]/.test(key)) return null;
  const family = key.match(/^sk-(?:proj|admin)-/)?.[0] ?? "sk-";
  const identifier = key.slice(family.length);
  if (identifier.length <= 10) return `${family}${identifier.slice(0, 2)}••••`;
  return `${family}${identifier.slice(0, 6)}…${identifier.slice(-4)}`;
}

function fileHint(path: string | null): string | null {
  if (!path) return null;
  try {
    return maskOpenAiKey(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function configuredHint(value: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  // A deployment may pass an already-masked hint. If it accidentally passes
  // a complete key, reduce it here before it can enter any API response.
  if (trimmed.includes("•") || trimmed.includes("…") || trimmed.includes("*")) {
    return trimmed.slice(0, 24);
  }
  return maskOpenAiKey(trimmed);
}

export function openAiKeyHints(): LlmKeyHint[] {
  const inferenceFile = fileHint(config.openAiInferenceKeyFile);
  const inferenceSafeHint = inferenceFile ?? configuredHint(config.llmApiKeyHint) ?? configuredHint(config.openAiInferenceKeyHint);
  const adminFile = fileHint(config.openAiAdminKeyFile);
  const admin = configuredHint(config.llmAdminKeyHint) ?? adminFile;
  return [
    {
      purpose: "inference",
      label: "Inference key",
      masked: inferenceSafeHint,
      configured: inferenceSafeHint !== null,
      source: inferenceFile !== null ? "file" : inferenceSafeHint !== null ? "safe_hint" : "unavailable",
    },
    {
      purpose: "billing_admin",
      label: "Billing admin key",
      masked: admin,
      configured: admin !== null,
      source: admin !== null ? config.llmAdminKeyHint ? "safe_hint" : "file" : "unavailable",
    },
  ];
}
