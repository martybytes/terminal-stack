// Dependency status dots for the dashboard header.
//
// Every field access into the upstream /health payload is guarded: anything
// unreadable degrades to "unknown", and when upstream itself is unreachable
// every upstream-derived dot is "unknown" rather than guessing.

import { statfsSync } from "node:fs";
import { dirname } from "node:path";
import { config } from "./config.js";
import type { DepStatus, HistoryStatus } from "../shared/types.js";

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function asString(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

export function computeDeps(input: {
  upstreamOk: boolean;
  wsConnected: boolean;
  health: unknown | null;
  history?: HistoryStatus;
}): DepStatus[] {
  const { upstreamOk, wsConnected, health, history } = input;
  const root = asRecord(health);
  const h = upstreamOk ? asRecord(root?.health) : null;
  const cb = upstreamOk ? asRecord(root?.circuitBreaker) : null;

  const deps: DepStatus[] = [];

  // proxy: we are the proxy — if this code runs, it is up.
  deps.push({ id: "proxy", label: "Proxy", state: "ok" });

  // api: upstream REST reachability (livez).
  deps.push(
    upstreamOk
      ? { id: "api", label: "API", state: "ok" }
      : { id: "api", label: "API", state: "down", detail: "livez unreachable" },
  );

  // stream: mem-live websocket. Meaningless when upstream itself is down.
  deps.push({
    id: "stream",
    label: "Stream",
    state: !upstreamOk ? "unknown" : wsConnected ? "ok" : "down",
  });

  // kv: health.health.kvConnectivity.status
  let kv: DepStatus = { id: "kv", label: "KV", state: "unknown" };
  if (h) {
    const kvc = asRecord(h.kvConnectivity);
    const status = asString(kvc?.status);
    if (status === "ok") {
      const lat = asNumber(kvc?.latencyMs);
      kv = { id: "kv", label: "KV", state: "ok", detail: lat === null ? undefined : `${lat.toFixed(1)} ms` };
    } else if (status !== null) {
      kv = {
        id: "kv",
        label: "KV",
        state: status === "degraded" || status === "warn" || status === "warning" ? "warn" : "down",
        detail: status,
      };
    }
  }
  deps.push(kv);

  // process: health.health.status + notes
  let proc: DepStatus = { id: "process", label: "Process", state: "unknown" };
  if (h) {
    const status = asString(h.status);
    const notes = Array.isArray(h.notes)
      ? h.notes.filter((n): n is string => typeof n === "string")
      : [];
    if (status === "healthy") {
      proc =
        notes.length > 0
          ? { id: "process", label: "Process", state: "warn", detail: notes[0] }
          : { id: "process", label: "Process", state: "ok" };
    } else if (status !== null) {
      proc = {
        id: "process",
        label: "Process",
        state: status === "degraded" || status === "warning" ? "warn" : "down",
        detail: notes[0] ?? status,
      };
    }
  }
  deps.push(proc);

  // llm: circuitBreaker.state
  let llm: DepStatus = { id: "llm", label: "LLM", state: "unknown" };
  if (cb) {
    const state = asString(cb.state);
    const failures = asNumber(cb.failures);
    const failDetail =
      failures !== null && failures > 0 ? `${failures} recent failure${failures === 1 ? "" : "s"}` : undefined;
    if (state === "closed") llm = { id: "llm", label: "LLM", state: "ok", detail: failDetail };
    else if (state === "half_open" || state === "half-open")
      llm = { id: "llm", label: "LLM", state: "warn", detail: failDetail ?? "half-open" };
    else if (state === "open") llm = { id: "llm", label: "LLM", state: "down", detail: failDetail ?? "circuit open" };
  }
  deps.push(llm);

  // workers: health.health.workers
  let workers: DepStatus = { id: "workers", label: "Workers", state: "unknown" };
  if (h && Array.isArray(h.workers)) {
    workers =
      h.workers.length > 0
        ? { id: "workers", label: "Workers", state: "ok", detail: `${h.workers.length} worker${h.workers.length === 1 ? "" : "s"}` }
        : { id: "workers", label: "Workers", state: "down", detail: "none registered" };
  }
  deps.push(workers);

  // volume: free space on the filesystem holding the shared secret file
  // (the mounted agentmemory data volume in the container profile).
  let volume: DepStatus = { id: "volume", label: "Volume", state: "unknown" };
  if (config.secretFile) {
    try {
      const st = statfsSync(dirname(config.secretFile));
      if (st.blocks > 0) {
        const usedPct = Math.round((1 - st.bavail / st.blocks) * 100);
        volume = {
          id: "volume",
          label: "Volume",
          state: usedPct > 85 ? "warn" : "ok",
          detail: `${usedPct}% used`,
        };
      }
    } catch {
      // Unreadable filesystem: leave "unknown".
    }
  }
  deps.push(volume);

  deps.push(
    history === undefined
      ? { id: "history", label: "History", state: "unknown" }
      : history.ok
        ? {
            id: "history",
            label: "History",
            state: "ok",
            detail: history.pendingBatches > 0 ? `${history.pendingBatches} pending` : "SQLite",
          }
        : {
            id: "history",
            label: "History",
            state: history.writable ? "warn" : "down",
            detail: history.lastError ?? "unavailable",
          },
  );

  return deps;
}
