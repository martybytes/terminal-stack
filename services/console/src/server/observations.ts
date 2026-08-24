// Server-side store for sessions, per-session observation timelines, and the
// memories browser.
//
// Upstream has no paging or filtering on /observations (sessions can carry
// 30k+ rows), so each session is fetched once, cached (LRU of 8, 60 s TTL),
// and sorted/filtered/sliced here. Memories are fetched in one big page and
// scored locally for search.

import type {
  TimelinePage,
  SessionSummary,
  MemoriesPage,
  ObservationEvent,
  TimelineItem,
  MemoryItem,
} from "../shared/types.js";
import { upstreamJson } from "./upstream.js";
import { emptyMemoryLifecycleCounts } from "../shared/memoryLifecycle.js";
import type { MemoryInventory } from "./memoryEffectiveness.js";

const SESSIONS_TTL_MS = 30_000;
const OBS_TTL_MS = 60_000;
const OBS_LRU_MAX = 8;
const MEM_TTL_MS = 60_000;
const ACTIVE_WINDOW_MS = 10 * 60_000;
const CONTENT_MAX = 500;
const SESSION_PROJECT_MAX = 5_000;
const SESSION_AGENT_MAX = 5_000;

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

function asStrings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((value): value is string => typeof value === "string" && value.length > 0) : [];
}

function parseTime(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return v > 1e12 ? v : v * 1000;
  if (typeof v === "string") {
    const parsed = Date.parse(v);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function clampSize(size: number | undefined, fallback: number): number {
  if (size === undefined || !Number.isFinite(size)) return fallback;
  return Math.min(200, Math.max(10, Math.floor(size)));
}

function clampPage(page: number | undefined): number {
  if (page === undefined || !Number.isFinite(page)) return 0;
  return Math.max(0, Math.floor(page));
}

// ---------------------------------------------------------------- sessions

let sessionsCache: { at: number; list: SessionSummary[] } | null = null;
let sessionsInFlight: Promise<SessionSummary[]> | null = null;
// Also accepts exact project/session pairs observed by the proxy. This fills
// the short gap before the upstream sessions cache refreshes and lets
// session-only calls (notably session/end) retain their project attribution.
const sessionProjects = new Map<string, string>();
const sessionAgents = new Map<string, string>();

function cacheSessionProject(sessionId: string, project: string): void {
  sessionProjects.delete(sessionId);
  sessionProjects.set(sessionId, project);
  while (sessionProjects.size > SESSION_PROJECT_MAX) {
    const oldest = sessionProjects.keys().next().value;
    if (oldest === undefined) break;
    sessionProjects.delete(oldest);
  }
}

function cacheSessionAgent(sessionId: string, agent: string): void {
  sessionAgents.delete(sessionId);
  sessionAgents.set(sessionId, agent);
  while (sessionAgents.size > SESSION_AGENT_MAX) {
    const oldest = sessionAgents.keys().next().value;
    if (oldest === undefined) break;
    sessionAgents.delete(oldest);
  }
}

async function fetchSessions(): Promise<SessionSummary[]> {
  const payload = await upstreamJson<unknown>("/agentmemory/sessions");
  const rows = asRecord(payload)?.sessions;
  if (!Array.isArray(rows)) return sessionsCache?.list ?? [];
  const out: SessionSummary[] = [];
  const cutoff = Date.now() - ACTIVE_WINDOW_MS;
  for (const row of rows) {
    const r = asRecord(row);
    if (!r) continue;
    const id = asString(r.id);
    if (!id) continue; // legacy rows without an id are unusable — skip
    const startedAt = parseTime(r.startedAt);
    const lastActiveAt = parseTime(r.updatedAt) ?? parseTime(r.endedAt) ?? startedAt;
    const status = asString(r.status);
    const project = asString(r.project);
    const upstreamAgent = asString(r.agentId);
    if (project) cacheSessionProject(id, project);
    if (upstreamAgent) cacheSessionAgent(id, upstreamAgent);
    out.push({
      id,
      project,
      agent: upstreamAgent ?? sessionAgents.get(id) ?? null,
      startedAt,
      lastActiveAt,
      observationCount: asNumber(r.observationCount),
      active: status !== "completed" && lastActiveAt !== null && lastActiveAt >= cutoff,
      lifecycle: emptyMemoryLifecycleCounts(),
      retrievals: 0,
      retrievalHits: 0,
      contextTokens: 0,
      contextBlocks: 0,
      automaticRetrievals: 0,
      automaticHits: 0,
      automaticContextTokens: 0,
      manualRetrievals: 0,
      manualHits: 0,
      manualContextTokens: 0,
      startContextTokens: 0,
      startContextDelivered: false,
      closeoutObserved: false,
      lifecycleFirstAt: null,
      lifecycleLastAt: null,
    });
  }
  out.sort((a, b) => (b.lastActiveAt ?? 0) - (a.lastActiveAt ?? 0));
  return out;
}

async function getSessions(): Promise<SessionSummary[]> {
  const now = Date.now();
  if (sessionsCache && now - sessionsCache.at < SESSIONS_TTL_MS) return sessionsCache.list;
  if (!sessionsInFlight) {
    sessionsInFlight = fetchSessions()
      .then((list) => {
        sessionsCache = { at: Date.now(), list };
        return list;
      })
      .finally(() => {
        sessionsInFlight = null;
      });
  }
  return sessionsInFlight;
}

// ------------------------------------------------------------ observations

interface ObsCacheEntry {
  at: number;
  items: TimelineItem[]; // upstream order: oldest first; live events appended
  types: string[];
}

// Map iteration order doubles as LRU order: delete+set on every touch.
const obsCache = new Map<string, ObsCacheEntry>();
const obsInFlight = new Map<string, Promise<ObsCacheEntry | null>>();
// Negative cache: a failed fetch is remembered briefly so every page view of
// a struggling session doesn't re-issue the doomed multi-MB request.
const OBS_FAIL_TTL_MS = 15_000;
const obsFailedAt = new Map<string, number>();

async function fetchObservations(sessionId: string): Promise<ObsCacheEntry | null> {
  const payload = await upstreamJson<unknown>(
    `/agentmemory/observations?sessionId=${encodeURIComponent(sessionId)}`,
    // Unpaged endpoint: 30k+ observations serialize to tens of MB, and the
    // upstream averages 20 s function latencies under load — the default 8 s
    // budget aborts mid-download on exactly the largest sessions.
    { timeoutMs: 120_000 },
  );
  const rows = asRecord(payload)?.observations;
  if (!Array.isArray(rows)) return null;
  const items: TimelineItem[] = [];
  const types = new Set<string>();
  for (let i = 0; i < rows.length; i++) {
    const r = asRecord(rows[i]);
    if (!r) continue;
    const type = asString(r.type);
    if (type) types.add(type);
    const narrative = asString(r.narrative);
    items.push({
      id: asString(r.id) ?? `obs_${sessionId}_${i}`,
      ts: parseTime(r.timestamp),
      sessionId,
      agent: asString(r.agentId) ?? sessionAgents.get(sessionId) ?? null,
      type,
      title: asString(r.title),
      content: narrative === null ? null : narrative.slice(0, CONTENT_MAX),
      importance: asNumber(r.importance),
    });
  }
  return { at: Date.now(), items, types: [...types].sort() };
}

async function loadSession(sessionId: string): Promise<ObsCacheEntry | null> {
  const now = Date.now();
  const hit = obsCache.get(sessionId);
  if (hit && now - hit.at < OBS_TTL_MS) {
    obsCache.delete(sessionId);
    obsCache.set(sessionId, hit); // refresh LRU position
    return hit;
  }
  const failedAt = obsFailedAt.get(sessionId);
  if (failedAt !== undefined && now - failedAt < OBS_FAIL_TTL_MS) {
    return hit ?? null; // recent failure: back off instead of re-fetching
  }
  let pending = obsInFlight.get(sessionId);
  if (!pending) {
    pending = fetchObservations(sessionId)
      .then((entry) => {
        if (entry) {
          obsFailedAt.delete(sessionId);
          obsCache.delete(sessionId);
          obsCache.set(sessionId, entry);
          while (obsCache.size > OBS_LRU_MAX) {
            const oldest = obsCache.keys().next().value;
            if (oldest === undefined) break;
            obsCache.delete(oldest);
          }
          return entry;
        }
        if (obsFailedAt.size > 256) obsFailedAt.clear(); // keep the map bounded
        obsFailedAt.set(sessionId, Date.now());
        return hit ?? null; // fetch failed: serve the stale entry if we have one
      })
      .finally(() => {
        obsInFlight.delete(sessionId);
      });
    obsInFlight.set(sessionId, pending);
  }
  return pending;
}

// --------------------------------------------------------------- memories

let memCache: { at: number; items: MemoryItem[] } | null = null;
let memInFlight: Promise<MemoryItem[]> | null = null;

async function fetchMemories(): Promise<MemoryItem[] | null> {
  const payload = await upstreamJson<unknown>("/agentmemory/memories?limit=5000");
  const rows = asRecord(payload)?.memories;
  if (!Array.isArray(rows)) return null;
  const out: MemoryItem[] = [];
  for (const row of rows) {
    const r = asRecord(row);
    if (!r) continue;
    const id = asString(r.id);
    if (!id) continue;
    const tags = Array.isArray(r.concepts)
      ? r.concepts.filter((c): c is string => typeof c === "string")
      : [];
    out.push({
      id,
      recordKind: "memory",
      agent: asString(r.agentId),
      type: asString(r.type),
      title: asString(r.title),
      content: asString(r.content),
      score: null,
      tags,
      createdAt: parseTime(r.createdAt),
      updatedAt: parseTime(r.updatedAt),
      project: asString(r.project),
      files: asStrings(r.files),
      sessionIds: asStrings(r.sessionIds),
      sourceObservationIds: asStrings(r.sourceObservationIds),
      strength: asNumber(r.strength),
      version: asNumber(r.version),
      supersedes: asStrings(r.supersedes),
      isLatest: r.isLatest !== false,
    });
  }
  out.sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
  return out;
}

async function loadMemories(): Promise<MemoryItem[]> {
  const now = Date.now();
  if (memCache && now - memCache.at < MEM_TTL_MS) return memCache.items;
  if (!memInFlight) {
    memInFlight = fetchMemories()
      .then((items) => {
        if (items) {
          memCache = { at: Date.now(), items };
          return items;
        }
        return memCache?.items ?? []; // fetch failed: serve stale if available
      })
      .finally(() => {
        memInFlight = null;
      });
  }
  return memInFlight;
}

// ------------------------------------------------------------------ store

let liveSeq = 0;

export const store: {
  sessions(): Promise<SessionSummary[]>;
  noteSessionProject(sessionId: string, project: string): void;
  noteSessionAgent(sessionId: string, agent: string): void;
  projectForSession(sessionId: string): Promise<string | null>;
  agentForSession(sessionId: string): Promise<string | null>;
  timeline(q: {
    sessionId?: string;
    sort?: "newest" | "oldest";
    page?: number;
    size?: number;
    types?: string[];
    minImportance?: number;
  }): Promise<TimelinePage>;
  memories(q: { query?: string; page?: number; size?: number; type?: string; project?: string }): Promise<MemoriesPage>;
  memoryInventory(): Promise<MemoryInventory>;
  ingestLive(e: ObservationEvent): void;
} = {
  sessions() {
    return getSessions();
  },

  noteSessionProject(sessionId, project) {
    cacheSessionProject(sessionId, project);
  },

  noteSessionAgent(sessionId, agent) {
    cacheSessionAgent(sessionId, agent);
  },

  async projectForSession(sessionId) {
    const hit = sessionProjects.get(sessionId);
    if (hit !== undefined) {
      cacheSessionProject(sessionId, hit); // refresh LRU position
      return hit;
    }
    try {
      const sessions = await getSessions();
      return sessions.find((session) => session.id === sessionId)?.project ?? null;
    } catch {
      return null;
    }
  },

  async agentForSession(sessionId) {
    const hit = sessionAgents.get(sessionId);
    if (hit !== undefined) {
      cacheSessionAgent(sessionId, hit); // refresh LRU position
      return hit;
    }
    try {
      const sessions = await getSessions();
      return sessions.find((session) => session.id === sessionId)?.agent ?? null;
    } catch {
      return null;
    }
  },

  async timeline(q) {
    const sort: "newest" | "oldest" = q.sort === "oldest" ? "oldest" : "newest";
    const page = clampPage(q.page);
    const size = clampSize(q.size, 50);
    const empty: TimelinePage = { total: 0, page, size, sort, items: [], types: [] };

    let sessionId = q.sessionId;
    if (!sessionId) {
      const list = await getSessions();
      sessionId = list[0]?.id; // most recently active
    }
    if (!sessionId) return empty;

    const entry = await loadSession(sessionId);
    if (!entry) return empty;

    let items = entry.items;
    if (q.types && q.types.length > 0) {
      const wanted = new Set(q.types);
      items = items.filter((i) => i.type !== null && wanted.has(i.type));
    }
    if (typeof q.minImportance === "number" && Number.isFinite(q.minImportance)) {
      const min = q.minImportance;
      items = items.filter((i) => (i.importance ?? 0) >= min);
    }

    const sorted = [...items].sort((a, b) => {
      const ta = a.ts ?? 0;
      const tb = b.ts ?? 0;
      return sort === "newest" ? tb - ta : ta - tb;
    });

    const start = page * size;
    return {
      total: sorted.length,
      page,
      size,
      sort,
      items: sorted.slice(start, start + size),
      types: entry.types,
    };
  },

  async memories(q: { query?: string; page?: number; size?: number; type?: string; project?: string }) {
    const page = clampPage(q.page);
    const size = clampSize(q.size, 50);
    const allMemories = await loadMemories();
    const projects = [...new Set(allMemories.flatMap((memory) => memory.project ? [memory.project] : []))].sort();
    const scopedTotal = allMemories.filter((memory) => memory.project !== null).length;
    const unscopedTotal = allMemories.length - scopedTotal;
    let rejectedResults = 0;
    let items: MemoryItem[];

    if (q.query?.trim()) {
      const limit = Math.min(100, Math.max(size, (page + 1) * size));
      const payload = await upstreamJson<unknown>("/agentmemory/search", {
        method: "POST",
        timeoutMs: 30_000,
        body: {
          query: q.query.trim(),
          limit,
          format: "full",
          ...(q.project ? { project: q.project } : {}),
        },
      });
      const rows = asRecord(payload)?.results;
      const byId = new Map(allMemories.map((memory) => [memory.id, memory]));
      const sessions = await getSessions();
      const projectBySession = new Map(sessions.map((session) => [session.id, session.project]));
      items = [];
      for (const value of Array.isArray(rows) ? rows : []) {
        const result = asRecord(value);
        const observation = asRecord(result?.observation) ?? result;
        if (!observation) continue;
        const id = asString(observation.id) ?? asString(result?.obsId);
        if (!id) continue;
        const existing = byId.get(id);
        if (existing) {
          items.push({ ...existing, score: asNumber(result?.score) ?? asNumber(result?.combinedScore) });
          continue;
        }
        const sessionId = asString(result?.sessionId) ?? asString(observation.sessionId);
        const project = asString(result?.project) ?? asString(observation.project) ?? (sessionId ? projectBySession.get(sessionId) ?? null : null);
        items.push({
          id,
          recordKind: "observation",
          agent: asString(observation.agentId),
          type: asString(observation.type),
          title: asString(observation.title),
          content: asString(observation.narrative),
          score: asNumber(result?.score) ?? asNumber(result?.combinedScore),
          tags: asStrings(observation.concepts),
          createdAt: parseTime(observation.timestamp),
          updatedAt: parseTime(observation.timestamp),
          project,
          files: asStrings(observation.files),
          sessionIds: sessionId ? [sessionId] : [],
          sourceObservationIds: [],
          strength: asNumber(observation.importance),
          version: null,
          supersedes: [],
          isLatest: true,
        });
      }
      if (q.project) {
        const before = items.length;
        items = items.filter((item) => item.project === q.project);
        rejectedResults = before - items.length;
      }
    } else {
      items = q.project ? allMemories.filter((memory) => memory.project === q.project) : allMemories;
    }
    if (q.type) {
      const type = q.type;
      items = items.filter((m) => m.type === type);
    }

    const start = page * size;
    return {
      total: items.length,
      page,
      size,
      items: items.slice(start, start + size),
      searchMode: q.query?.trim() ? "hybrid" : "list",
      projects,
      scopedTotal,
      unscopedTotal,
      rejectedResults,
    };
  },

  async memoryInventory() {
    const memories = await loadMemories();
    const projects = [...new Set(memories.flatMap((memory) => memory.project ? [memory.project] : []))].sort();
    const scoped = memories.filter((memory) => memory.project !== null).length;
    const emptyQuality = () => ({ total: 0, scoped: 0, conceptTagged: 0, sourceLinked: 0, active: 0, superseded: 0 });
    const byProject: Record<string, number> = {};
    const quality = emptyQuality();
    const qualityByProject: Record<string, ReturnType<typeof emptyQuality>> = {};
    for (const memory of memories) {
      const project = memory.project;
      if (project) byProject[project] = (byProject[project] ?? 0) + 1;
      const targets = [quality, ...(project ? [qualityByProject[project] ??= emptyQuality()] : [])];
      for (const target of targets) {
        target.total++;
        if (project) target.scoped++;
        if (memory.tags.length > 0) target.conceptTagged++;
        if (memory.sourceObservationIds.length > 0 || memory.sessionIds.length > 0) target.sourceLinked++;
        if (memory.isLatest) target.active++;
        else target.superseded++;
      }
    }
    return { total: memories.length, scoped, unscoped: memories.length - scoped, projects, byProject, quality, qualityByProject };
  },

  ingestLive(e) {
    if (!e.sessionId) return;
    const entry = obsCache.get(e.sessionId);
    if (!entry) return; // only sessions someone is actually viewing are cached
    liveSeq++;
    entry.items.push({
      id: `live_${e.ts}_${liveSeq}`,
      ts: Number.isFinite(e.ts) ? e.ts : Date.now(),
      sessionId: e.sessionId,
      agent: e.agent,
      type: e.type,
      title: e.title,
      content: e.excerpt,
      importance: e.importance,
    });
    if (e.type && !entry.types.includes(e.type)) {
      entry.types.push(e.type);
      entry.types.sort();
    }
  },
};
