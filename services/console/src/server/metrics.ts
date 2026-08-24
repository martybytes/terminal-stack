// Periodic upstream polling and metric assembly.
//
// Every config.healthPollMs the poller probes livez, then (when up) fetches
// /health, the memories count, and the sessions list in parallel, folds in
// the live capture numbers, and publishes a MetricsTick to subscribers.
// Observation minute-buckets are fed by memlive events via noteObservation.

import type { MetricsTick, HealthSample, ObsBucket, ObservationEvent } from "../shared/types.js";
import { config } from "./config.js";
import { capture } from "./capture.js";
import { upstreamJson, upstreamOk } from "./upstream.js";
import { computeDeps } from "./deps.js";
import { history } from "./history.js";

const MINUTE_MS = 60_000;
const DAY_MS = 24 * 60 * MINUTE_MS;
const OBS_SLOTS = 1440; // 24 h of minute buckets
const ACTIVE_WINDOW_MS = 10 * MINUTE_MS;

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function toHealthSample(health: unknown, ts: number): HealthSample | null {
  const h = asRecord(asRecord(health)?.health);
  if (!h) return null;
  const mem = asRecord(h.memory);
  const heap = asNumber(mem?.heapUsed);
  const rss = asNumber(mem?.rss);
  return {
    ts,
    heapMb: heap === null ? null : Math.round((heap / 1_048_576) * 10) / 10,
    rssMb: rss === null ? null : Math.round((rss / 1_048_576) * 10) / 10,
    lagMs: asNumber(h.eventLoopLagMs),
    uptimeSec: asNumber(h.uptimeSeconds),
  };
}

let wsConnected = false;
let latest: MetricsTick | null = null;
let started = false;
let polling = false;
const series: HealthSample[] = [];
const subs: Array<(t: MetricsTick) => void> = [];
const obsBuckets = new Map<number, { raw: number; compressed: number }>();

function pruneObs(now: number): void {
  const cutoff = now - DAY_MS - MINUTE_MS;
  for (const t of obsBuckets.keys()) {
    if (t < cutoff) obsBuckets.delete(t);
  }
}

function pruneSeries(now: number): void {
  const cutoff = now - DAY_MS;
  let drop = 0;
  while (drop < series.length && series[drop].ts < cutoff) drop++;
  if (drop > 0) series.splice(0, drop);
}

function obsTodayCount(): number {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const start = startOfDay.getTime();
  let total = 0;
  for (const [t, b] of obsBuckets) {
    if (t >= start) total += b.raw;
  }
  return total;
}

async function poll(): Promise<void> {
  if (polling) return;
  polling = true;
  try {
    const ok = await upstreamOk();
    let health: unknown | null = null;
    let memoriesTotal: number | null = null;
    let sessionsTotal: number | null = null;
    let sessionsActive: number | null = null;

    if (ok) {
      const [h, counts, sessions] = await Promise.all([
        upstreamJson<unknown>("/agentmemory/health"),
        upstreamJson<unknown>("/agentmemory/memories?count=true"),
        upstreamJson<unknown>("/agentmemory/sessions"),
      ]);
      health = h;
      memoriesTotal = asNumber(asRecord(counts)?.total);

      const rows = asRecord(sessions)?.sessions;
      if (Array.isArray(rows)) {
        sessionsTotal = rows.length;
        let active = 0;
        const cutoff = Date.now() - ACTIVE_WINDOW_MS;
        for (const row of rows) {
          const r = asRecord(row);
          if (!r) continue;
          const status = typeof r.status === "string" ? r.status : null;
          const updated = typeof r.updatedAt === "string" ? Date.parse(r.updatedAt) : NaN;
          if ((status !== null && status !== "completed") || (Number.isFinite(updated) && updated >= cutoff)) {
            active++;
          }
        }
        sessionsActive = active;
      }
    }

    // Carry last-known totals through a failed poll (or a failed sub-fetch)
    // so the offline dashboard genuinely shows "last data" — the UI renders
    // a still-null value as an em-dash, never a fabricated zero.
    memoriesTotal = memoriesTotal ?? latest?.memoriesTotal ?? null;
    sessionsTotal = sessionsTotal ?? latest?.sessionsTotal ?? null;
    sessionsActive = sessionsActive ?? latest?.sessionsActive ?? null;

    const now = Date.now();
    const sample = ok ? toHealthSample(health, now) : null;
    if (sample) {
      series.push(sample);
      pruneSeries(now);
    }

    const lat = capture.latency();
    const tick: MetricsTick = {
      ts: now,
      reqPerMin: capture.reqPerMin(),
      errLast15m: capture.errLast15m(),
      p50: lat.p50,
      p95: lat.p95,
      memoriesTotal,
      sessionsTotal,
      sessionsActive,
      obsToday: obsTodayCount(),
      health: sample,
      deps: computeDeps({ upstreamOk: ok, wsConnected, health, history: history.status() }),
      upstreamOk: ok,
    };
    latest = tick;
    for (const fn of subs) {
      try {
        fn(tick);
      } catch {
        // subscriber errors never stop polling
      }
    }
  } finally {
    polling = false;
  }
}

export const metrics: {
  start(): void;
  setWsConnected(v: boolean): void;
  noteObservation(e: ObservationEvent): void;
  latestTick(): MetricsTick | null;
  healthSeries(): HealthSample[];
  obsBuckets1m(): ObsBucket[];
  subscribe(fn: (t: MetricsTick) => void): void;
} = {
  start() {
    if (started) return;
    started = true;
    void poll();
    setInterval(() => void poll(), config.healthPollMs);
  },

  setWsConnected(v) {
    wsConnected = v;
  },

  noteObservation(e) {
    const ts = Number.isFinite(e.ts) ? e.ts : Date.now();
    const t = Math.floor(ts / MINUTE_MS) * MINUTE_MS;
    let b = obsBuckets.get(t);
    if (!b) {
      b = { raw: 0, compressed: 0 };
      obsBuckets.set(t, b);
    }
    if (e.kind === "compressed") b.compressed++;
    else b.raw++;
    pruneObs(Date.now());
  },

  latestTick() {
    return latest;
  },

  healthSeries() {
    pruneSeries(Date.now());
    return [...series];
  },

  obsBuckets1m() {
    const now = Date.now();
    pruneObs(now);
    const end = Math.floor(now / MINUTE_MS) * MINUTE_MS;
    const out: ObsBucket[] = [];
    for (let i = OBS_SLOTS - 1; i >= 0; i--) {
      const t = end - i * MINUTE_MS;
      const b = obsBuckets.get(t);
      out.push({ t, raw: b?.raw ?? 0, compressed: b?.compressed ?? 0 });
    }
    return out;
  },

  subscribe(fn) {
    subs.push(fn);
  },
};
