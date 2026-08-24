import type {
  MemoryEffectivenessSnapshot,
  MemoryEffectivenessWarning,
  RequestRecord,
  SessionSummary,
  MemoryQualityCounts,
} from "../shared/types.js";
import { emptyMemoryLifecycleCounts, isRetrievalStage } from "../shared/memoryLifecycle.js";
import { addMemoryFlow, emptyMemoryFlowCounts, memoryFlowForRequest } from "../shared/memoryFlow.js";
import { addMemoryEconomics, emptyMemoryEconomicsCounts, memoryEconomicsForRequest, retrievalMode } from "../shared/memoryEconomics.js";
import { upstreamJson } from "./upstream.js";

const WINDOW_MS = 15 * 60_000;
const UPSTREAM_TTL_MS = 30_000;

export interface MemoryInventory {
  total: number;
  scoped: number;
  unscoped: number;
  projects: string[];
  byProject: Record<string, number>;
  quality: MemoryQualityCounts;
  qualityByProject: Record<string, MemoryQualityCounts>;
}

interface UpstreamMemorySignals {
  at: number;
  semanticFacts: number | null;
  graphNodes: number | null;
  graphEdges: number | null;
  graphUpdatedAt: number | null;
  featureFlags: Array<{ key: string; label: string; enabled: boolean }>;
}

let cached: UpstreamMemorySignals | null = null;
let inFlight: Promise<UpstreamMemorySignals> | null = null;

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function time(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function fetchSignals(): Promise<UpstreamMemorySignals> {
  const [semanticRaw, graphRaw, flagsRaw] = await Promise.all([
    upstreamJson<unknown>("/agentmemory/semantic", { timeoutMs: 20_000 }),
    upstreamJson<unknown>("/agentmemory/graph/stats", { timeoutMs: 20_000 }),
    upstreamJson<unknown>("/agentmemory/config/flags", { timeoutMs: 20_000 }),
  ]);
  const semantic = record(semanticRaw);
  const graph = record(graphRaw);
  const flagsRoot = record(flagsRaw);
  const featureFlags = (Array.isArray(flagsRoot?.flags) ? flagsRoot.flags : []).flatMap((value) => {
    const row = record(value);
    const key = typeof row?.key === "string" ? row.key : null;
    const label = typeof row?.label === "string" ? row.label : key;
    return key && label ? [{ key, label, enabled: row?.enabled === true }] : [];
  });
  return {
    at: Date.now(),
    semanticFacts: Array.isArray(semantic?.semantic) ? semantic.semantic.length : null,
    graphNodes: number(graph?.totalNodes),
    graphEdges: number(graph?.totalEdges),
    graphUpdatedAt: time(graph?.updatedAt),
    featureFlags,
  };
}

async function signals(): Promise<UpstreamMemorySignals> {
  if (cached && Date.now() - cached.at < UPSTREAM_TTL_MS) return cached;
  if (!inFlight) {
    inFlight = fetchSignals().then((value) => {
      cached = value;
      return value;
    }).finally(() => { inFlight = null; });
  }
  return inFlight;
}

function warning(id: string, severity: MemoryEffectivenessWarning["severity"], title: string, detail: string): MemoryEffectivenessWarning {
  return { id, severity, title, detail };
}

export async function memoryEffectiveness(
  allRequests: RequestRecord[],
  inventory: MemoryInventory,
  now = Date.now(),
): Promise<MemoryEffectivenessSnapshot> {
  const recent = allRequests.filter((request) => request.ts >= now - WINDOW_MS);
  const lifecycle = emptyMemoryLifecycleCounts();
  let retrievals = 0;
  let retrievalHits = 0;
  let retrievalMisses = 0;
  let retrievalUnknown = 0;
  let contextTokens = 0;
  let contextBlocks = 0;
  let contextChars = 0;
  let unscopedResults = 0;
  let crossProjectResults = 0;
  let projectAttributedRequests = 0;
  let attributableRequests = 0;
  let unscopedAgentRetrievals = 0;
  let mismatchedSaves = 0;
  const memory = emptyMemoryFlowCounts();
  const economics = emptyMemoryEconomicsCounts();
  let sessionStartsAssisted = 0;
  let sessionStartsEmpty = 0;
  let sessionCloseouts = 0;
  const endMinute = Math.floor(now / 60_000) * 60_000;
  const buckets = Array.from({ length: 15 }, (_, index) => ({
    t: endMinute - (14 - index) * 60_000,
    memory: emptyMemoryFlowCounts(),
    economics: emptyMemoryEconomicsCounts(),
  }));

  for (const request of recent) {
    const delta = memoryFlowForRequest(request);
    addMemoryFlow(memory, delta);
    addMemoryEconomics(economics, memoryEconomicsForRequest(request));
    const point = buckets.find((bucket) => bucket.t === Math.floor(request.ts / 60_000) * 60_000);
    if (point) {
      addMemoryFlow(point.memory, delta);
      addMemoryEconomics(point.economics, memoryEconomicsForRequest(request));
    }
    lifecycle[request.lifecycle]++;
    if (request.lifecycle === "session_start") {
      if (request.outcome?.kind === "returned") sessionStartsAssisted++;
      else if (request.outcome?.kind === "empty") sessionStartsEmpty++;
    }
    if (request.lifecycle === "session_end") sessionCloseouts++;
    if (request.lifecycle !== "health" && request.lifecycle !== "admin") {
      attributableRequests++;
      if (request.project) projectAttributedRequests++;
    }
    if (isRetrievalStage(request.lifecycle)) {
      retrievals++;
      if (request.outcome?.kind === "returned") retrievalHits++;
      else if (request.outcome?.kind === "empty") retrievalMisses++;
      else retrievalUnknown++;
      if (!request.project && request.agent) unscopedAgentRetrievals++;
    }
    contextTokens += request.outcome?.contextTokens ?? 0;
    contextBlocks += request.outcome?.contextBlocks ?? 0;
    contextChars += request.outcome?.contextChars ?? 0;
    unscopedResults += request.outcome?.unscopedResultCount ?? 0;
    crossProjectResults += request.outcome?.crossProjectResultCount ?? 0;
    if (request.lifecycle === "memory_save" && request.project && request.outcome?.returnedProject !== null && request.outcome?.returnedProject !== request.project) mismatchedSaves++;
    if (request.lifecycle === "memory_save" && request.project && request.outcome?.returnedProject === null && request.route === "/agentmemory/mcp/call") mismatchedSaves++;
  }

  const upstream = await signals();
  const warnings: MemoryEffectivenessWarning[] = [];
  if (inventory.unscoped > 0) warnings.push(warning("unscoped-memories", "warn", `${inventory.unscoped} memories have no project`, "Unprojected memories can contaminate project-scoped recall until the upstream filter and legacy data are repaired."));
  if (unscopedResults > 0) warnings.push(warning("unscoped-results", "bad", `${unscopedResults} retrieval results lacked project proof`, "The upstream response did not prove these results belonged to the requested project."));
  if (crossProjectResults > 0) warnings.push(warning("cross-project-results", "bad", `${crossProjectResults} cross-project results detected`, "Returned project metadata explicitly differed from the requested project."));
  if (unscopedAgentRetrievals > 0) warnings.push(warning("unscoped-agent-recall", "warn", `${unscopedAgentRetrievals} agent recalls were unscoped`, "Current MCP recall/search schemas do not consistently carry the active project."));
  if (mismatchedSaves > 0) warnings.push(warning("save-project-mismatch", "bad", `${mismatchedSaves} saves lacked matching project confirmation`, "The save request was scoped, but the response did not confirm the same project."));
  if (lifecycle.session_end > lifecycle.session_start + 1) warnings.push(warning("session-boundary", "warn", "Session-end traffic exceeds session starts", "Host Stop events may still be posting session/end before the real SessionEnd event."));
  if (retrievals > 0 && retrievalHits === 0) warnings.push(warning("no-retrieval-hits", "warn", "No confirmed retrieval hits", "Requests occurred, but response outcome telemetry has not confirmed returned memory context."));
  if (economics.automaticAttempts > 0 && economics.automaticHits === 0) warnings.push(warning("no-automatic-context", "warn", "Automatic context returned no confirmed memory", "Session and file hooks requested context, but none was confirmed as delivered."));
  if (economics.manualContextTokens > 10_000) warnings.push(warning("large-manual-context", "warn", "Manual search returned substantial context", "Manual searches are excluded from estimated context avoided and may warrant a smaller token budget."));
  if (economics.truncatedRetrievals > 0) warnings.push(warning("truncated-retrievals", "info", `${economics.truncatedRetrievals} retrievals reached their budget`, "Truncation is expected when ranked results fill the caller's configured context budget."));

  return {
    ts: now,
    windowMs: WINDOW_MS,
    lifecycle,
    retrievals,
    retrievalHits,
    retrievalMisses,
    retrievalUnknown,
    hitRate: retrievalHits + retrievalMisses > 0 ? retrievalHits / (retrievalHits + retrievalMisses) : null,
    contextTokens,
    contextBlocks,
    contextChars,
    projectAttributedRequests,
    projectCoverageRate: attributableRequests > 0 ? projectAttributedRequests / attributableRequests : null,
    unscopedResults,
    crossProjectResults,
    storedMemories: inventory.total,
    scopedMemories: inventory.scoped,
    unscopedMemories: inventory.unscoped,
    memoryProjectCoverageRate: inventory.total > 0 ? inventory.scoped / inventory.total : null,
    semanticFacts: upstream.semanticFacts,
    graphNodes: upstream.graphNodes,
    graphEdges: upstream.graphEdges,
    graphUpdatedAt: upstream.graphUpdatedAt,
    featureFlags: upstream.featureFlags,
    economics,
    quality: inventory.quality,
    sessionStartsAssisted,
    sessionStartsEmpty,
    sessionCloseouts,
    warnings,
    memory,
    buckets,
  };
}

export function enrichSessions(sessions: SessionSummary[], requests: RequestRecord[]): SessionSummary[] {
  const byId = new Map(sessions.map((session) => [session.id, {
    ...session,
    lifecycle: emptyMemoryLifecycleCounts(), retrievals: 0, retrievalHits: 0,
    contextTokens: 0, contextBlocks: 0, lifecycleFirstAt: null as number | null,
    lifecycleLastAt: null as number | null,
    automaticRetrievals: 0, automaticHits: 0, automaticContextTokens: 0,
    manualRetrievals: 0, manualHits: 0, manualContextTokens: 0,
    startContextTokens: 0, startContextDelivered: false, closeoutObserved: false,
  }]));
  for (const request of requests) {
    if (!request.sessionId) continue;
    const session = byId.get(request.sessionId);
    if (!session) continue;
    session.lifecycle[request.lifecycle]++;
    if (isRetrievalStage(request.lifecycle)) {
      session.retrievals++;
      if (request.outcome?.kind === "returned") session.retrievalHits++;
    }
    const mode = retrievalMode(request.lifecycle);
    if (mode === "automatic") {
      session.automaticRetrievals++;
      if (request.outcome?.kind === "returned") session.automaticHits++;
      session.automaticContextTokens += request.outcome?.contextTokens ?? 0;
    } else if (mode === "manual") {
      session.manualRetrievals++;
      if (request.outcome?.kind === "returned") session.manualHits++;
      session.manualContextTokens += request.outcome?.contextTokens ?? 0;
    }
    if (request.lifecycle === "session_start") {
      session.startContextTokens += request.outcome?.contextTokens ?? 0;
      if (request.outcome?.kind === "returned") session.startContextDelivered = true;
    }
    if (request.lifecycle === "session_end") session.closeoutObserved = true;
    session.contextTokens += request.outcome?.contextTokens ?? 0;
    session.contextBlocks += request.outcome?.contextBlocks ?? 0;
    session.lifecycleFirstAt = Math.min(session.lifecycleFirstAt ?? request.ts, request.ts);
    session.lifecycleLastAt = Math.max(session.lifecycleLastAt ?? request.ts, request.ts);
  }
  return [...byId.values()];
}
