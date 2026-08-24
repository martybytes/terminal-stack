// Request capture: metadata-only ring buffer plus time-bucketed rollups.
//
// Two rollup resolutions feed the dashboard charts: 5s buckets over the last
// 15 minutes and 1-minute buckets over the last 24 hours. Per-bucket duration
// arrays exist only while a bucket is still open; when its window passes the
// p50/p95 are frozen and the array is dropped, so memory stays bounded no
// matter the traffic rate.

import type {
  ProjectFlowEvent,
  ProjectsSnapshot,
  RequestRecord,
  RollupBucket,
  SessionSummary,
  MemoryQualityCounts,
  DerivedWorkCounts,
} from "../shared/types.js";
import { isRetrievalStage, isStorageStage } from "../shared/memoryLifecycle.js";
import { config } from "./config.js";
import { ProjectActivityTracker } from "./projectActivity.js";

const MINUTE_MS = 60_000;
const FIFTEEN_MIN_MS = 15 * MINUTE_MS;

function percentile(sorted: number[], q: number): number {
  const n = sorted.length;
  if (n === 0) return 0;
  const idx = Math.min(n - 1, Math.max(0, Math.ceil(q * n) - 1));
  return sorted[idx];
}

interface MutBucket {
  t: number;
  count: number;
  ok: number;
  err4: number;
  err5: number;
  p50: number;
  p95: number;
  durs: number[] | null; // present while the bucket is open, dropped on freeze
}

class Rollup {
  private buckets = new Map<number, MutBucket>();

  constructor(
    private readonly widthMs: number,
    private readonly slots: number,
  ) {}

  add(ts: number, status: number, durMs: number): void {
    this.freezeAndPrune(Date.now());
    const t = Math.floor(ts / this.widthMs) * this.widthMs;
    let b = this.buckets.get(t);
    if (!b) {
      b = { t, count: 0, ok: 0, err4: 0, err5: 0, p50: 0, p95: 0, durs: [] };
      this.buckets.set(t, b);
    }
    b.count++;
    if (status === 0 || status >= 500) b.err5++;
    else if (status >= 400) b.err4++;
    else b.ok++;
    if (b.durs) b.durs.push(durMs);
  }

  // Oldest first, zero-filled, exactly `slots` entries ending at "now".
  series(now: number): RollupBucket[] {
    this.freezeAndPrune(now);
    const end = Math.floor(now / this.widthMs) * this.widthMs;
    const out: RollupBucket[] = [];
    for (let i = this.slots - 1; i >= 0; i--) {
      const t = end - i * this.widthMs;
      const b = this.buckets.get(t);
      if (!b) {
        out.push({ t, count: 0, ok: 0, err4: 0, err5: 0, p50: 0, p95: 0 });
      } else if (b.durs) {
        // Still open: compute percentiles on the fly without freezing.
        const sorted = [...b.durs].sort((a, z) => a - z);
        out.push({
          t: b.t,
          count: b.count,
          ok: b.ok,
          err4: b.err4,
          err5: b.err5,
          p50: percentile(sorted, 0.5),
          p95: percentile(sorted, 0.95),
        });
      } else {
        out.push({ t: b.t, count: b.count, ok: b.ok, err4: b.err4, err5: b.err5, p50: b.p50, p95: b.p95 });
      }
    }
    return out;
  }

  private freezeAndPrune(now: number): void {
    const current = Math.floor(now / this.widthMs) * this.widthMs;
    const oldest = current - (this.slots - 1) * this.widthMs;
    for (const [t, b] of this.buckets) {
      if (t < oldest) {
        this.buckets.delete(t);
        continue;
      }
      if (t < current && b.durs) {
        const sorted = b.durs.sort((a, z) => a - z);
        b.p50 = percentile(sorted, 0.5);
        b.p95 = percentile(sorted, 0.95);
        b.durs = null; // frozen
      }
    }
  }
}

// Strip the query string and collapse id-ish path segments so the requests
// table can group by route: uuids, mem_*/obs_*-style ids, long hex, and long
// pure-numeric segments all become ":id".
export function normalizeRoute(path: string): string {
  const q = path.indexOf("?");
  const bare = q === -1 ? path : path.slice(0, q);
  const collapsed = bare
    .split("/")
    .map((seg) => {
      if (seg === "") return seg;
      if (/^[A-Za-z]{2,12}_[A-Za-z0-9_-]{4,}$/.test(seg)) return ":id"; // mem_..., obs_..., sess_...
      if (/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(seg)) return ":id"; // uuid
      if (/^[0-9a-fA-F]{16,}$/.test(seg)) return ":id"; // long hex
      if (/^\d{6,}$/.test(seg)) return ":id"; // long numeric
      return seg;
    })
    .join("/");
  return collapsed === "" ? "/" : collapsed;
}

const records: RequestRecord[] = [];
let nextId = 1;
const subscribers: Array<(r: RequestRecord) => void> = [];
const r5s = new Rollup(5_000, FIFTEEN_MIN_MS / 5_000); // 180 buckets
const r1m = new Rollup(MINUTE_MS, 1440); // 24 h, capped 1440
const projectActivity = new ProjectActivityTracker(config.ringSize);
const projectFlowSubscribers: Array<(event: ProjectFlowEvent) => void> = [];
let nextProjectFlowId = 1;

function publishProjectFlow(
  project: string,
  direction: ProjectFlowEvent["direction"],
  tone: ProjectFlowEvent["tone"],
): ProjectFlowEvent | null {
  const scopedProject = project.trim();
  if (!scopedProject) return null;
  const event: ProjectFlowEvent = {
    id: nextProjectFlowId++,
    ts: Date.now(),
    project: scopedProject,
    direction,
    tone,
  };
  for (const fn of projectFlowSubscribers) {
    try {
      fn(event);
    } catch {
      // Project glow telemetry must never affect the proxy path.
    }
  }
  return event;
}

function finiteOr(v: number, fallback: number): number {
  return Number.isFinite(v) ? v : fallback;
}

export const capture: {
  record(rec: Omit<RequestRecord, "id">): RequestRecord;
  subscribe(fn: (r: RequestRecord) => void): void;
  recent(limit?: number): RequestRecord[];
  buckets5s(): RollupBucket[];
  buckets1m(): RollupBucket[];
  reqPerMin(): number;
  errLast15m(): number;
  latency(): { p50: number; p95: number };
  projects(
    sessions: SessionSummary[],
    memoryCounts?: Record<string, number>,
    qualityByProject?: Record<string, MemoryQualityCounts>,
    derivedByProject?: Record<string, DerivedWorkCounts>,
  ): ProjectsSnapshot;
  projectFlow(project: string, direction: ProjectFlowEvent["direction"], tone?: ProjectFlowEvent["tone"]): ProjectFlowEvent | null;
  subscribeProjectFlow(fn: (event: ProjectFlowEvent) => void): void;
} = {
  record(rec) {
    const clean: RequestRecord = {
      id: nextId++,
      ts: finiteOr(rec.ts, Date.now()),
      method: rec.method,
      path: rec.path,
      route: rec.route,
      operation:
        typeof rec.operation === "string" && rec.operation.trim().length > 0
          ? rec.operation.trim().slice(0, 512)
          : null,
      project: typeof rec.project === "string" && rec.project.length > 0 ? rec.project : null,
      sessionId:
        typeof rec.sessionId === "string" && rec.sessionId.trim().length > 0
          ? rec.sessionId.trim().slice(0, 512)
          : null,
      agent:
        typeof rec.agent === "string" && rec.agent.trim().length > 0
          ? rec.agent.trim().slice(0, 128)
          : null,
      lifecycle: rec.lifecycle,
      requestedTokenBudget:
        typeof rec.requestedTokenBudget === "number" && Number.isFinite(rec.requestedTokenBudget) && rec.requestedTokenBudget > 0
          ? Math.floor(rec.requestedTokenBudget)
          : null,
      outcome: rec.outcome,
      status: finiteOr(rec.status, 0),
      durMs: Math.max(0, Math.round(finiteOr(rec.durMs, 0) * 10) / 10),
      reqBytes: finiteOr(rec.reqBytes, -1),
      resBytes: finiteOr(rec.resBytes, -1),
    };
    records.push(clean);
    if (records.length > config.ringSize) records.splice(0, records.length - config.ringSize);
    r5s.add(clean.ts, clean.status, clean.durMs);
    r1m.add(clean.ts, clean.status, clean.durMs);
    projectActivity.record(clean);
    for (const fn of subscribers) {
      try {
        fn(clean);
      } catch {
        // A broken subscriber must never break capture.
      }
    }
    if (clean.project && (isStorageStage(clean.lifecycle) || isRetrievalStage(clean.lifecycle))) {
      const direction = isStorageStage(clean.lifecycle) ? "in" : "out";
      const tone = clean.outcome?.kind === "failed" ? "bad" : clean.outcome?.kind === "unknown" || clean.outcome?.kind === "empty" ? "warn" : "ok";
      publishProjectFlow(clean.project, direction, tone);
    }
    return clean;
  },

  subscribe(fn) {
    subscribers.push(fn);
  },

  recent(limit = 60) {
    const n = Math.max(1, Math.min(config.ringSize, Math.floor(limit)));
    const out: RequestRecord[] = [];
    for (let i = records.length - 1; i >= 0 && out.length < n; i--) out.push(records[i]);
    return out;
  },

  buckets5s() {
    return r5s.series(Date.now());
  },

  buckets1m() {
    return r1m.series(Date.now());
  },

  // NOTE: records[] is appended in COMPLETION order while ts is the request
  // START time, so it is not sorted by ts — a long-running request (upstream
  // functions legitimately take 20-180 s) lands late with an old ts. The
  // window scans below therefore walk the whole ring (capped at
  // config.ringSize) instead of stopping at the first out-of-window record.

  reqPerMin() {
    const cutoff = Date.now() - MINUTE_MS;
    let count = 0;
    for (let i = records.length - 1; i >= 0; i--) {
      if (records[i].ts >= cutoff) count++;
    }
    return count;
  },

  errLast15m() {
    const cutoff = Date.now() - FIFTEEN_MIN_MS;
    let count = 0;
    for (let i = records.length - 1; i >= 0; i--) {
      const r = records[i];
      if (r.ts >= cutoff && (r.status === 0 || r.status >= 400)) count++;
    }
    return count;
  },

  latency() {
    const cutoff = Date.now() - FIFTEEN_MIN_MS;
    const durs: number[] = [];
    for (let i = records.length - 1; i >= 0; i--) {
      if (records[i].ts >= cutoff) durs.push(records[i].durMs);
    }
    durs.sort((a, z) => a - z);
    return { p50: percentile(durs, 0.5), p95: percentile(durs, 0.95) };
  },

  projects(sessions, memoryCounts = {}, qualityByProject = {}, derivedByProject = {}) {
    return projectActivity.snapshot(sessions, records, nextId - 1, memoryCounts, qualityByProject, derivedByProject);
  },

  projectFlow(project, direction, tone = "ok") {
    return publishProjectFlow(project, direction, tone);
  },

  subscribeProjectFlow(fn) {
    projectFlowSubscribers.push(fn);
  },
};
