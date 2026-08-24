import type { LlmCallTelemetry } from "../shared/types.js";

// Versioned deployment catalog. Rates are USD nanos per token (1 USD = 1e9
// nanos), derived from OpenAI's published per-million-token prices. Keeping the
// catalog in code makes historical estimates reproducible; it is never scraped
// at request time.
export const PRICING_CATALOG_EFFECTIVE = "2026-08-21";

interface TokenRates {
  input: number;
  cachedInput: number;
  cacheWrite: number;
  output: number;
}

const OPENAI_RATES: Array<{ matches: (model: string) => boolean; rates: TokenRates }> = [
  {
    matches: (model) => model === "gpt-5.6-luna" || model.startsWith("gpt-5.6-luna-"),
    rates: { input: 200, cachedInput: 20, cacheWrite: 250, output: 1_200 },
  },
  {
    matches: (model) => model === "gpt-5.6-terra" || model.startsWith("gpt-5.6-terra-"),
    rates: { input: 2_000, cachedInput: 200, cacheWrite: 2_500, output: 12_000 },
  },
];

export interface CostEstimate {
  nanos: number | null;
  coverage: "priced" | "local" | "unpriced";
}

function tokenCount(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

export function estimateLlmCall(call: Pick<LlmCallTelemetry,
  "provider" | "model" | "promptTokens" | "cachedPromptTokens" | "cacheWriteTokens" | "completionTokens"
>): CostEstimate {
  const provider = call.provider.trim().toLowerCase();
  if (provider.includes("local") || provider === "noop" || provider === "none") {
    return { nanos: 0, coverage: "local" };
  }
  if (provider !== "openai" || !call.model) return { nanos: null, coverage: "unpriced" };
  const entry = OPENAI_RATES.find(({ matches }) => matches(call.model!));
  if (!entry) return { nanos: null, coverage: "unpriced" };

  const cached = tokenCount(call.cachedPromptTokens);
  const cacheWrite = tokenCount(call.cacheWriteTokens);
  const prompt = tokenCount(call.promptTokens);
  const uncached = Math.max(0, prompt - cached - cacheWrite);
  const output = tokenCount(call.completionTokens);
  const longPromptMultiplier = prompt > 272_000 ? 2 : 1;
  const longOutputMultiplier = prompt > 272_000 ? 1.5 : 1;
  const nanos =
    (uncached * entry.rates.input +
      cached * entry.rates.cachedInput +
      cacheWrite * entry.rates.cacheWrite) * longPromptMultiplier +
    output * entry.rates.output * longOutputMultiplier;
  return { nanos, coverage: "priced" };
}

export function formatUsdNanos(nanos: number | null, minimumDigits = 2): string {
  if (nanos === null) return "—";
  const dollars = nanos / 1_000_000_000;
  const maximumFractionDigits = dollars > 0 && dollars < 0.01 ? 4 : minimumDigits;
  return dollars.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: minimumDigits,
    maximumFractionDigits,
  });
}
