// Per-project request activity for the Projects page.
//
// Counts live in bounded five-second buckets for a rolling 15-minute window.
// The public snapshot folds those into 15 one-minute graph points and merges
// durable session projects so an idle project still has a card.

import type {
  ProjectActivityBucket,
  ProjectAgent,
  ProjectAgentCounts,
  ProjectMethod,
  ProjectMethodCounts,
  ProjectsSnapshot,
  ProjectSummary,
  MemoryFlowCounts,
  MemoryEconomicsCounts,
  MemoryQualityCounts,
  DerivedWorkCounts,
  RequestRecord,
  SessionSummary,
} from "../shared/types.js";
import { emptyRequestIntents, requestIntent } from "../shared/requestIntent.js";
import { emptyMemoryLifecycleCounts, isRetrievalStage } from "../shared/memoryLifecycle.js";
import { addMemoryFlow, emptyMemoryFlowCounts, memoryFlowForRequest } from "../shared/memoryFlow.js";
import { addMemoryEconomics, emptyMemoryEconomicsCounts, memoryEconomicsForRequest } from "../shared/memoryEconomics.js";

export const PROJECT_WINDOW_MS = 15 * 60_000;
const BUCKET_MS = 5_000;
const GRAPH_BUCKET_MS = 60_000;
const GRAPH_BUCKETS = PROJECT_WINDOW_MS / GRAPH_BUCKET_MS;
const RPM_BUCKETS = 60_000 / BUCKET_MS;

interface ActivityBucket {
  t: number;
  count: number;
  errors: number;
  methods: ProjectMethodCounts;
  intents: ReturnType<typeof emptyRequestIntents>;
  lifecycle: ReturnType<typeof emptyMemoryLifecycleCounts>;
  retrievals: number;
  retrievalHits: number;
  retrievalMisses: number;
  contextTokens: number;
  contextBlocks: number;
  unscopedResults: number;
  crossProjectResults: number;
  agents: ProjectAgentCounts;
  memory: MemoryFlowCounts;
  economics: MemoryEconomicsCounts;
}

interface ProjectActivity {
  buckets: Map<number, ActivityBucket>;
  lastRequestAt: number | null;
}

function methodCounts(): ProjectMethodCounts {
  return { get: 0, post: 0, put: 0, delete: 0, other: 0 };
}

function agentCounts(): ProjectAgentCounts {
  return { claude: 0, codex: 0, cursor: 0, unknown: 0 };
}

function methodKey(method: string): ProjectMethod {
  const normalized = method.trim().toLowerCase();
  if (normalized === "get" || normalized === "post" || normalized === "put" || normalized === "delete") {
    return normalized;
  }
  return "other";
}

export function projectAgent(agent: string | null): ProjectAgent {
  const normalized = agent?.trim().toLowerCase();
  if (normalized === "claude" || normalized === "codex" || normalized === "cursor") {
    return normalized;
  }
  return "unknown";
}

function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(q * sorted.length) - 1));
  return sorted[index];
}

function addMethods(target: ProjectMethodCounts, source: ProjectMethodCounts): void {
  target.get += source.get;
  target.post += source.post;
  target.put += source.put;
  target.delete += source.delete;
  target.other += source.other;
}

function addAgents(target: ProjectAgentCounts, source: ProjectAgentCounts): void {
  target.claude += source.claude;
  target.codex += source.codex;
  target.cursor += source.cursor;
  target.unknown += source.unknown;
}

export class ProjectActivityTracker {
  private readonly activity = new Map<string, ProjectActivity>();

  constructor(private readonly maxProjects = 5_000) {}

  record(request: RequestRecord): void {
    const project = request.project?.trim();
    if (!project) return;

    let entry = this.activity.get(project);
    if (!entry) {
      entry = { buckets: new Map(), lastRequestAt: null };
      this.activity.set(project, entry);
    } else {
      this.activity.delete(project);
      this.activity.set(project, entry); // Map order is the project LRU.
    }

    const t = Math.floor(request.ts / BUCKET_MS) * BUCKET_MS;
    let bucket = entry.buckets.get(t);
    if (!bucket) {
      bucket = {
        t, count: 0, errors: 0, methods: methodCounts(), intents: emptyRequestIntents(),
        lifecycle: emptyMemoryLifecycleCounts(), retrievals: 0, retrievalHits: 0,
        retrievalMisses: 0, contextTokens: 0, contextBlocks: 0,
        unscopedResults: 0, crossProjectResults: 0, agents: agentCounts(), memory: emptyMemoryFlowCounts(),
        economics: emptyMemoryEconomicsCounts(),
      };
      entry.buckets.set(t, bucket);
    }
    bucket.count++;
    bucket.methods[methodKey(request.method)]++;
    bucket.intents[requestIntent(request)]++;
    bucket.lifecycle[request.lifecycle]++;
    if (isRetrievalStage(request.lifecycle)) {
      bucket.retrievals++;
      if (request.outcome?.kind === "returned") bucket.retrievalHits++;
      else if (request.outcome?.kind === "empty") bucket.retrievalMisses++;
    }
    bucket.contextTokens += request.outcome?.contextTokens ?? 0;
    bucket.contextBlocks += request.outcome?.contextBlocks ?? 0;
    bucket.unscopedResults += request.outcome?.unscopedResultCount ?? 0;
    bucket.crossProjectResults += request.outcome?.crossProjectResultCount ?? 0;
    bucket.agents[projectAgent(request.agent)]++;
    addMemoryFlow(bucket.memory, memoryFlowForRequest(request));
    addMemoryEconomics(bucket.economics, memoryEconomicsForRequest(request));
    if (request.status === 0 || request.status >= 400) bucket.errors++;

    const completedAt = request.ts + Math.max(0, request.durMs);
    entry.lastRequestAt = Math.max(entry.lastRequestAt ?? 0, completedAt);
    this.pruneBuckets(entry, Date.now());
    this.pruneProjects();
  }

  snapshot(
    sessions: SessionSummary[],
    recentRequests: RequestRecord[],
    latestRequestId: number,
    memoryCounts: Record<string, number> = {},
    qualityByProject: Record<string, MemoryQualityCounts> = {},
    derivedByProject: Record<string, DerivedWorkCounts> = {},
    now = Date.now(),
  ): ProjectsSnapshot {
    const sessionData = new Map<
      string,
      { lastActivityAt: number | null; lastAgent: ProjectAgent | null; lastAgentAt: number }
    >();
    const corpusObservations = new Map<string, number>();

    for (const session of sessions) {
      const project = session.project?.trim();
      if (!project) continue;
      const hit = sessionData.get(project) ?? {
        lastActivityAt: null,
        lastAgent: null,
        lastAgentAt: Number.NEGATIVE_INFINITY,
      };
      if (session.lastActiveAt !== null) {
        hit.lastActivityAt = Math.max(hit.lastActivityAt ?? 0, session.lastActiveAt);
      }
      if (session.agent?.trim()) {
        const agentAt = session.lastActiveAt ?? session.startedAt ?? 0;
        if (agentAt >= hit.lastAgentAt) {
          hit.lastAgent = projectAgent(session.agent);
          hit.lastAgentAt = agentAt;
        }
      }
      sessionData.set(project, hit);
      corpusObservations.set(project, (corpusObservations.get(project) ?? 0) + Math.max(0, session.observationCount ?? 0));
    }

    const names = new Set([...sessionData.keys(), ...this.activity.keys()]);
    const projects: ProjectSummary[] = [];
    const latencyByProject = new Map<string, number[]>();
    const cutoff = now - PROJECT_WINDOW_MS;
    for (const request of recentRequests) {
      const project = request.project?.trim();
      if (!project || request.ts < cutoff) continue;
      const durations = latencyByProject.get(project) ?? [];
      durations.push(request.durMs);
      latencyByProject.set(project, durations);
    }

    for (const project of names) {
      const entry = this.activity.get(project);
      if (entry) this.pruneBuckets(entry, now);
      const methods = methodCounts();
      const intents = emptyRequestIntents();
      const lifecycle = emptyMemoryLifecycleCounts();
      const agents = agentCounts();
      const memory = emptyMemoryFlowCounts();
      const economics = emptyMemoryEconomicsCounts();
      let requestCount = 0;
      let requestsPerMinute = 0;
      let errorCount = 0;
      let retrievals = 0;
      let retrievalHits = 0;
      let retrievalMisses = 0;
      let contextTokens = 0;
      let contextBlocks = 0;
      let unscopedResults = 0;
      let crossProjectResults = 0;
      const current5s = Math.floor(now / BUCKET_MS) * BUCKET_MS;
      const rpmOldest = current5s - (RPM_BUCKETS - 1) * BUCKET_MS;

      for (const bucket of entry?.buckets.values() ?? []) {
        requestCount += bucket.count;
        errorCount += bucket.errors;
        addMethods(methods, bucket.methods);
        for (const intent of Object.keys(intents) as Array<keyof typeof intents>) intents[intent] += bucket.intents[intent];
        for (const stage of Object.keys(lifecycle) as Array<keyof typeof lifecycle>) lifecycle[stage] += bucket.lifecycle[stage];
        retrievals += bucket.retrievals;
        retrievalHits += bucket.retrievalHits;
        retrievalMisses += bucket.retrievalMisses;
        contextTokens += bucket.contextTokens;
        contextBlocks += bucket.contextBlocks;
        unscopedResults += bucket.unscopedResults;
        crossProjectResults += bucket.crossProjectResults;
        addAgents(agents, bucket.agents);
        addMemoryFlow(memory, bucket.memory);
        addMemoryEconomics(economics, bucket.economics);
        if (bucket.t >= rpmOldest) requestsPerMinute += bucket.count;
      }

      const graph = new Map<number, { methods: ProjectMethodCounts; memory: MemoryFlowCounts; economics: MemoryEconomicsCounts }>();
      for (const bucket of entry?.buckets.values() ?? []) {
        const minute = Math.floor(bucket.t / GRAPH_BUCKET_MS) * GRAPH_BUCKET_MS;
        const counts = graph.get(minute) ?? { methods: methodCounts(), memory: emptyMemoryFlowCounts(), economics: emptyMemoryEconomicsCounts() };
        addMethods(counts.methods, bucket.methods);
        addMemoryFlow(counts.memory, bucket.memory);
        addMemoryEconomics(counts.economics, bucket.economics);
        graph.set(minute, counts);
      }
      const endMinute = Math.floor(now / GRAPH_BUCKET_MS) * GRAPH_BUCKET_MS;
      const buckets: ProjectActivityBucket[] = [];
      for (let i = GRAPH_BUCKETS - 1; i >= 0; i--) {
        const t = endMinute - i * GRAPH_BUCKET_MS;
        const point = graph.get(t);
        buckets.push({ t, methods: point?.methods ?? methodCounts(), memory: point?.memory ?? emptyMemoryFlowCounts(), economics: point?.economics ?? emptyMemoryEconomicsCounts() });
      }

      const session = sessionData.get(project);
      const lastRequestAt = entry?.lastRequestAt ?? null;
      const sessionAt = session?.lastActivityAt ?? null;
      const lastActivityAt =
        lastRequestAt === null ? sessionAt : sessionAt === null ? lastRequestAt : Math.max(lastRequestAt, sessionAt);
      const durations = latencyByProject.get(project) ?? [];
      durations.sort((a, b) => a - b);
      projects.push({
        project,
        lastActivityAt,
        lastRequestAt,
        lastAgent: session?.lastAgent ?? null,
        requestCount,
        requestsPerMinute,
        errorCount,
        p95Ms: percentile(durations, 0.95),
        methods,
        intents,
        lifecycle,
        retrievals,
        retrievalHits,
        retrievalMisses,
        contextTokens,
        contextBlocks,
        unscopedResults,
        crossProjectResults,
        agents,
        memory,
        economics: { ...economics, corpusObservations: corpusObservations.get(project) ?? 0 },
        quality: qualityByProject[project] ?? { total: 0, scoped: 0, conceptTagged: 0, sourceLinked: 0, active: 0, superseded: 0 },
        derivedWork: derivedByProject[project] ?? { queued: 0, running: 0, failed: 0, oldestWaitMs: null },
        longTermMemories: memoryCounts[project] ?? 0,
        buckets,
      });
    }

    projects.sort(
      (a, b) =>
        (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0) || a.project.localeCompare(b.project),
    );
    return { ts: now, windowMs: PROJECT_WINDOW_MS, latestRequestId, projects };
  }

  private pruneBuckets(entry: ProjectActivity, now: number): void {
    const oldest = Math.floor(now / BUCKET_MS) * BUCKET_MS - (PROJECT_WINDOW_MS / BUCKET_MS - 1) * BUCKET_MS;
    for (const t of entry.buckets.keys()) {
      if (t < oldest) entry.buckets.delete(t);
    }
  }

  private pruneProjects(): void {
    while (this.activity.size > this.maxProjects) {
      const oldest = this.activity.keys().next().value;
      if (oldest === undefined) return;
      this.activity.delete(oldest);
    }
  }
}
