// Dead-lettered LLM jobs: the automatic redrive, and the manual Process / Clear
// actions behind the Dead letters page.
//
// Automatic only on a FREE (local) model, and only for dead letters under 24
// hours old. On a paid or unknown provider nothing is redriven without the
// operator: the page offers Process or Clear and shows what it would cost.
//
// Redriving one message is safe because every agentmemory handler re-checks
// current state before it calls the model (compression skips
// already_compressed / observation_missing, summary only runs when due, graph
// follows its incremental marker), so a stale redrive costs a queue hop, not a
// call. Bulk iii::queue::redrive is never used.

import type { DlqMessage, DlqProcessorState, DlqRow, DlqSnapshot, LlmSnapshot } from "../shared/types.js";
import type { LlmCostApplicability } from "../shared/llmEndpoint.js";
import { history } from "./history.js";
import { llmTelemetry } from "./llmTelemetry.js";
import { upstreamJson } from "./upstream.js";

export const AUTO_WINDOW_MS = 24 * 60 * 60_000;
export const AUTO_BATCH = 10;
export const PAUSE_MS = 30 * 60_000;
const POLL_MS = 60_000;
const STATE_KEY = "dlq_processor";
const PAGE = 200;

const EMPTY_STATE: DlqProcessorState = { lastRunAt: null, lastRedriven: 0, lastReason: null, pausedUntil: null };

export function ageOf(message: DlqMessage, now: number): number | null {
  const at = message.failedAt ?? message.queuedAt;
  return at === null ? null : Math.max(0, now - at);
}

// "Healthy" is proof the provider answered, not an absence of errors. The
// outage this was built for logged outcome "success" at 0 ms with no provider
// behind it, so a success only counts when it actually took time.
export function llmHealthy(llm: Pick<LlmSnapshot, "upstreamOk" | "circuitBreaker" | "queue" | "calls">): { ok: boolean; reason: string } {
  if (!llm.upstreamOk) return { ok: false, reason: "agentmemory is not answering" };
  if (llm.circuitBreaker.state === "open") return { ok: false, reason: "the LLM circuit breaker is open" };
  if (!llm.queue || llm.queue.consumers < 1) return { ok: false, reason: "the LLM queue has no consumers" };
  const latest = llm.calls
    .filter((call) => call.status === "completed")
    .reduce<(typeof llm.calls)[number] | null>((best, call) => (!best || (call.completedAt ?? 0) > (best.completedAt ?? 0) ? call : best), null);
  if (!latest) return { ok: false, reason: "no completed LLM call yet to prove the provider answers" };
  if (latest.outcome !== "success") return { ok: false, reason: `the latest LLM call ended in ${latest.outcome ?? "an unknown outcome"}` };
  if (!(Number(latest.providerLatencyMs) > 0)) return { ok: false, reason: "the latest LLM call never reached a provider" };
  return { ok: true, reason: "the latest LLM call reached the provider and succeeded" };
}

export interface AutoPlan {
  redrive: string[];
  reason: string;
  pause: boolean;
}

export function planAutoRedrive(
  messages: DlqMessage[],
  now: number,
  applicability: LlmCostApplicability,
  health: { ok: boolean; reason: string },
  state: DlqProcessorState,
): AutoPlan {
  if (applicability !== "local") return { redrive: [], reason: "paid or unknown model: waiting for a decision on the Dead letters page", pause: false };
  if (state.pausedUntil !== null && state.pausedUntil > now) return { redrive: [], reason: "paused after redriven jobs failed again", pause: false };
  if (!health.ok) {
    // A redrive whose jobs came straight back would otherwise repeat every tick.
    const bounced = state.lastRedriven > 0 && state.lastRunAt !== null && now - state.lastRunAt < PAUSE_MS;
    return { redrive: [], reason: health.reason, pause: bounced };
  }
  const due = messages
    .filter((message) => {
      const age = ageOf(message, now);
      return age !== null && age < AUTO_WINDOW_MS;
    })
    .sort((a, b) => (ageOf(a, now) ?? 0) - (ageOf(b, now) ?? 0))
    .slice(0, AUTO_BATCH)
    .map((message) => message.id);
  if (due.length === 0) return { redrive: [], reason: "nothing under 24 hours old", pause: false };
  return { redrive: due, reason: health.reason, pause: false };
}

async function listAll(): Promise<DlqMessage[] | null> {
  const result = await upstreamJson<{ messages?: DlqMessage[] }>("/agentmemory/llm/dlq?limit=1000", { timeoutMs: 30_000 });
  return Array.isArray(result?.messages) ? result.messages : null;
}

async function act(path: "redrive" | "discard", ids: string[]): Promise<{ done: number; failed: number }> {
  let done = 0;
  let failed = 0;
  for (let start = 0; start < ids.length; start += PAGE) {
    const chunk = ids.slice(start, start + PAGE);
    const result = await upstreamJson<{ redriven?: number; discarded?: number; failed?: number }>(`/agentmemory/llm/dlq/${path}`, {
      method: "POST",
      body: { messageIds: chunk },
      timeoutMs: 120_000,
    });
    if (!result) throw new Error("AgentMemory did not accept the operation");
    done += Number(result.redriven ?? result.discarded ?? 0);
    failed += Number(result.failed ?? 0);
  }
  return { done, failed };
}

function averageCostNanos(llm: LlmSnapshot, family: string): number | null {
  const priced = llm.calls.filter((call) => call.family === family && call.estimatedCostNanos !== null);
  if (priced.length === 0) return null;
  return priced.reduce((sum, call) => sum + (call.estimatedCostNanos ?? 0), 0) / priced.length;
}

export function estimateCostNanos(llm: LlmSnapshot, rows: DlqMessage[]): number | null {
  if (llm.config.costApplicability === "local") return 0;
  let total = 0;
  for (const row of rows) {
    const each = averageCostNanos(llm, row.family);
    if (each === null) return null;
    total += each;
  }
  return Math.round(total);
}

let state: DlqProcessorState = { ...EMPTY_STATE };
let running = false;
let started = false;
const listeners = new Set<(state: DlqProcessorState) => void>();

async function loadState(): Promise<void> {
  try {
    const raw = await history.metaValue(STATE_KEY);
    if (raw) state = { ...EMPTY_STATE, ...(JSON.parse(raw) as Partial<DlqProcessorState>) };
  } catch {
    // History unavailable: start from an empty state; the next save retries.
  }
}

async function saveState(next: DlqProcessorState): Promise<void> {
  state = next;
  for (const listener of listeners) listener(next);
  try {
    await history.setMetaValue(STATE_KEY, JSON.stringify(next));
  } catch {
    // Losing the pause across a restart only costs one extra health check.
  }
}

async function tick(): Promise<void> {
  if (running) return;
  running = true;
  try {
    const llm = llmTelemetry.snapshot();
    if (!llm.queue || llm.queue.dlqDepth === 0) return;
    const messages = await listAll();
    if (!messages) return;
    const now = Date.now();
    const plan = planAutoRedrive(messages, now, llm.config.costApplicability, llmHealthy(llm), state);
    if (plan.pause) {
      await saveState({ ...state, lastReason: `paused: ${plan.reason}`, pausedUntil: now + PAUSE_MS });
      console.warn(`agent007memory: dead-letter redrive paused for 30 minutes: ${plan.reason}`);
      return;
    }
    if (plan.redrive.length === 0) return;
    const { done, failed } = await act("redrive", plan.redrive);
    await saveState({ lastRunAt: now, lastRedriven: done, lastReason: plan.reason, pausedUntil: null });
    console.log(`agent007memory: redrove ${done} dead-lettered LLM job(s) automatically${failed ? `, ${failed} not found` : ""}`);
  } catch (error) {
    console.warn(`agent007memory: dead-letter redrive skipped: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    running = false;
  }
}

async function idsFor(body: { ids?: unknown; all?: unknown }): Promise<string[]> {
  if (body.all === true) {
    const messages = await listAll();
    if (!messages) throw new Error("AgentMemory did not return the dead letters");
    return messages.map((message) => message.id);
  }
  const ids = Array.isArray(body.ids) ? body.ids.filter((id): id is string => typeof id === "string") : [];
  if (ids.length === 0) throw new Error("Select at least one dead letter, or choose all");
  return [...new Set(ids)];
}

export const dlqProcessor = {
  async start(): Promise<void> {
    if (started) return;
    started = true;
    await loadState();
    setInterval(() => void tick(), POLL_MS).unref();
  },
  subscribe(listener: (state: DlqProcessorState) => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  async snapshot(): Promise<DlqSnapshot> {
    const llm = llmTelemetry.snapshot();
    const messages = await listAll();
    const now = Date.now();
    const local = llm.config.costApplicability === "local";
    const rows: DlqRow[] = (messages ?? []).map((message) => {
      const ageMs = ageOf(message, now);
      return { ...message, ageMs, autoEligible: local && ageMs !== null && ageMs < AUTO_WINDOW_MS };
    });
    return {
      ts: now,
      available: messages !== null,
      mode: local ? "automatic" : "manual",
      costApplicability: llm.config.costApplicability,
      costReason: llm.config.costReason,
      autoWindowMs: AUTO_WINDOW_MS,
      rows,
      estimatedCostNanos: estimateCostNanos(llm, rows),
      processor: state,
    };
  },
  async redrive(body: { ids?: unknown; all?: unknown }): Promise<{ done: number; failed: number }> {
    return act("redrive", await idsFor(body));
  },
  async discard(body: { ids?: unknown; all?: unknown }): Promise<{ done: number; failed: number }> {
    return act("discard", await idsFor(body));
  },
  async resume(): Promise<DlqProcessorState> {
    await saveState({ ...state, pausedUntil: null, lastReason: "resumed by operator" });
    void tick();
    return state;
  },
};
