export type LlmCostApplicability = "paid" | "local" | "unknown";

export interface LlmEndpointAssessment {
  costApplicability: LlmCostApplicability;
  costReason: string;
  inferenceActive: boolean;
}

export function isActiveLocalLlmCall(
  assessment: LlmEndpointAssessment,
  configuredModel: string | null,
  callModel: string | null,
): boolean {
  const activeModel = configuredModel?.trim().toLowerCase();
  const observedModel = callModel?.trim().toLowerCase();
  return assessment.costApplicability === "local" && Boolean(activeModel) && activeModel === observedModel;
}

const PAID_PROVIDER = /(?:openai|anthropic|azure|bedrock|vertex|google|gemini|groq|together|openrouter|cohere|fireworks)/i;
const LOCAL_RUNTIME = /(?:vllm|ollama|lm\s*studio|local|self[- ]?hosted|no llm|noop)/i;

function privateHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host === "::1" || host.endsWith(".local")) return true;
  const octets = host.split(".").map(Number);
  if (octets.length === 4 && octets.every((value) => Number.isInteger(value) && value >= 0 && value <= 255)) {
    return octets[0] === 10 || octets[0] === 127 || (octets[0] === 169 && octets[1] === 254) ||
      (octets[0] === 192 && octets[1] === 168) || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31);
  }
  return host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe8") || host.startsWith("fe9") || host.startsWith("fea") || host.startsWith("feb");
}

export function assessLlmEndpoint(provider: string | null, endpoint: string | null, model: string | null): LlmEndpointAssessment {
  const providerName = provider?.trim() ?? "";
  const inferenceActive = Boolean(model?.trim()) && !/(?:no llm|noop|disabled)/i.test(providerName);
  if (!inferenceActive) return { costApplicability: "local", costReason: "No active external inference model", inferenceActive: false };
  if (PAID_PROVIDER.test(providerName)) return { costApplicability: "paid", costReason: `${providerName} is a hosted API provider`, inferenceActive: true };
  let isPrivate = false;
  if (endpoint) {
    try { isPrivate = privateHost(new URL(endpoint).hostname); } catch { /* invalid endpoints remain unknown */ }
  }
  if (isPrivate) return { costApplicability: "local", costReason: "Inference endpoint is on the local or private network", inferenceActive: true };
  if (LOCAL_RUNTIME.test(providerName)) {
    return endpoint
      ? { costApplicability: "unknown", costReason: `${providerName} is self-hostable, but its endpoint is not private`, inferenceActive: true }
      : { costApplicability: "local", costReason: `${providerName} is a local inference runtime`, inferenceActive: true };
  }
  return { costApplicability: "unknown", costReason: "Provider fee status cannot be proven from the configured provider and endpoint", inferenceActive: true };
}
