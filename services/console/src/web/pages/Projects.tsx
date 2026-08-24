import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Activity, FolderKanban, RefreshCw } from "lucide-react";
import { Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import type {
  ProjectAgent,
  ProjectFlowEvent,
  ProjectMethod,
  ProjectMethodCounts,
  ProjectsSnapshot,
  ProjectSummary,
  RequestRecord,
} from "../../shared/types";
import { MetricsTiles } from "../components/MetricsTiles";
import { MemoryEffectiveness, useMemoryEffectiveness } from "../components/MemoryEffectiveness";
import { HelpTerm } from "../components/ContextHelp";
import { AgentPill, Card, EmptyState, Eyebrow, PageHeader, SelectBox } from "../components/ui";
import { apiGet } from "../lib/api";
import { fmtCompactRange, fmtMs, fmtNum, timeAgo } from "../lib/format";
import {
  DEFAULT_REORDER_INTERVAL,
  parseReorderInterval,
  type ReorderInterval,
  sortProjectNames,
} from "../lib/projectOrder";
import { useLive } from "../lib/ws";
import { emptyRequestIntents, requestIntent } from "../../shared/requestIntent";
import { emptyMemoryLifecycleCounts, isRetrievalStage } from "../../shared/memoryLifecycle";
import { addMemoryFlow, emptyMemoryFlowCounts, memoryFlowForRequest, storageAttempts, storedCount } from "../../shared/memoryFlow";
import { addMemoryEconomics, emptyMemoryEconomicsCounts, memoryEconomicsForRequest } from "../../shared/memoryEconomics";
import { estimateLabel } from "../../shared/memoryEconomics";
import { orderProjectNames, usePagePreferences, useRegisterProjects } from "../lib/preferences";

const SNAPSHOT_REFRESH_MS = 5_000;
const WINDOW_MS = 15 * 60_000;
const GRAPH_BUCKET_MS = 60_000;
export const PROJECT_ORDER_STORAGE_KEY = "agent007memory.projects.reorderIntervalMs";
const AGENTS: ProjectAgent[] = ["claude", "codex", "cursor", "unknown"];
const FLOW_VISIBLE_MS = 9_000;
const FLOW_DECAY_MS = 2_600;

export interface FlowStrength {
  in: number;
  out: number;
}

const METHOD_COLORS: Record<ProjectMethod, string> = {
  get: "var(--color-s1)",
  post: "var(--color-peri)",
  put: "var(--color-ok)",
  delete: "var(--color-bad)",
  other: "var(--color-fg3)",
};

function emptyMethods(): ProjectMethodCounts {
  return { get: 0, post: 0, put: 0, delete: 0, other: 0 };
}

export function emptyProjectSummary(project: string, now: number): ProjectSummary {
  const end = Math.floor(now / GRAPH_BUCKET_MS) * GRAPH_BUCKET_MS;
  return {
    project,
    lastActivityAt: null,
    lastRequestAt: null,
    lastAgent: null,
    requestCount: 0,
    requestsPerMinute: 0,
    errorCount: 0,
    p95Ms: 0,
    methods: emptyMethods(),
    intents: emptyRequestIntents(),
    lifecycle: emptyMemoryLifecycleCounts(),
    retrievals: 0,
    retrievalHits: 0,
    retrievalMisses: 0,
    contextTokens: 0,
    contextBlocks: 0,
    unscopedResults: 0,
    crossProjectResults: 0,
    agents: { claude: 0, codex: 0, cursor: 0, unknown: 0 },
    memory: emptyMemoryFlowCounts(),
    economics: emptyMemoryEconomicsCounts(),
    quality: { total: 0, scoped: 0, conceptTagged: 0, sourceLinked: 0, active: 0, superseded: 0 },
    derivedWork: { queued: 0, running: 0, failed: 0, oldestWaitMs: null },
    longTermMemories: 0,
    buckets: Array.from({ length: 15 }, (_, index) => ({
      t: end - (14 - index) * GRAPH_BUCKET_MS,
      methods: emptyMethods(),
      memory: emptyMemoryFlowCounts(),
      economics: emptyMemoryEconomicsCounts(),
    })),
  };
}

export function cloneProjectSummary(summary: ProjectSummary): ProjectSummary {
  return {
    ...summary,
    methods: { ...summary.methods },
    intents: { ...summary.intents },
    lifecycle: { ...summary.lifecycle },
    agents: { ...summary.agents },
    memory: { ...summary.memory },
    economics: { ...summary.economics },
    quality: { ...summary.quality },
    derivedWork: { ...summary.derivedWork },
    buckets: summary.buckets.map((bucket) => ({
      ...bucket,
      methods: { ...bucket.methods },
      memory: { ...bucket.memory },
      economics: { ...bucket.economics },
    })),
  };
}

function methodKey(method: string): ProjectMethod {
  const normalized = method.trim().toLowerCase();
  if (normalized === "get" || normalized === "post" || normalized === "put" || normalized === "delete") {
    return normalized;
  }
  return "other";
}

function agentKey(agent: string | null): ProjectAgent {
  const normalized = agent?.trim().toLowerCase();
  if (normalized === "claude" || normalized === "codex" || normalized === "cursor") {
    return normalized;
  }
  return "unknown";
}

export function applyProjectRequest(summary: ProjectSummary, request: RequestRecord, now: number): void {
  const completedAt = request.ts + Math.max(0, request.durMs);
  summary.lastRequestAt = Math.max(summary.lastRequestAt ?? 0, completedAt);
  summary.lastActivityAt = Math.max(summary.lastActivityAt ?? 0, completedAt);
  if (request.ts < now - WINDOW_MS) return;

  const method = methodKey(request.method);
  summary.requestCount++;
  summary.methods[method]++;
  summary.intents[requestIntent(request)]++;
  summary.lifecycle[request.lifecycle]++;
  if (isRetrievalStage(request.lifecycle)) {
    summary.retrievals++;
    if (request.outcome?.kind === "returned") summary.retrievalHits++;
    else if (request.outcome?.kind === "empty") summary.retrievalMisses++;
  }
  summary.contextTokens += request.outcome?.contextTokens ?? 0;
  summary.contextBlocks += request.outcome?.contextBlocks ?? 0;
  summary.unscopedResults += request.outcome?.unscopedResultCount ?? 0;
  summary.crossProjectResults += request.outcome?.crossProjectResultCount ?? 0;
  summary.agents[agentKey(request.agent)]++;
  addMemoryFlow(summary.memory, memoryFlowForRequest(request));
  addMemoryEconomics(summary.economics, memoryEconomicsForRequest(request));
  if (request.status === 0 || request.status >= 400) summary.errorCount++;
  if (request.ts >= now - 60_000) summary.requestsPerMinute++;

  const minute = Math.floor(request.ts / GRAPH_BUCKET_MS) * GRAPH_BUCKET_MS;
  const bucket = summary.buckets.find((candidate) => candidate.t === minute);
  if (bucket) {
    bucket.methods[method]++;
    addMemoryFlow(bucket.memory, memoryFlowForRequest(request));
    addMemoryEconomics(bucket.economics, memoryEconomicsForRequest(request));
  }
}

export function loadProjectReorderInterval(): ReorderInterval {
  try {
    return parseReorderInterval(window.localStorage.getItem(PROJECT_ORDER_STORAGE_KEY));
  } catch {
    return DEFAULT_REORDER_INTERVAL;
  }
}

export function saveProjectReorderInterval(value: ReorderInterval): void {
  try {
    window.localStorage.setItem(PROJECT_ORDER_STORAGE_KEY, String(value));
  } catch {
    // Storage can be disabled; the in-memory selection still works.
  }
}

export function projectFlowStrengths(events: ProjectFlowEvent[], now: number): Map<string, FlowStrength> {
  const raw = new Map<string, FlowStrength>();
  for (const event of events) {
    const age = now - event.ts;
    if (age < 0 || age > FLOW_VISIBLE_MS) continue;
    const strength = Math.exp(-age / FLOW_DECAY_MS);
    const project = raw.get(event.project) ?? { in: 0, out: 0 };
    project[event.direction] += strength;
    raw.set(event.project, project);
  }
  for (const strength of raw.values()) {
    strength.in = 1 - Math.exp(-strength.in / 1.6);
    strength.out = 1 - Math.exp(-strength.out / 1.6);
  }
  return raw;
}

function glowStyle(flow: FlowStrength): CSSProperties | undefined {
  if (flow.in < 0.015 && flow.out < 0.015) return undefined;
  const total = flow.in + flow.out;
  const red = Math.round((83 * flow.in + 138 * flow.out) / total);
  const green = Math.round((226 * flow.in + 128 * flow.out) / total);
  const blue = Math.round((221 * flow.in + 240 * flow.out) / total);
  const borderAlpha = 0.3 + Math.min(0.65, Math.max(flow.in, flow.out) * 0.65);
  const incoming = `rgba(83,226,221,${(0.35 + 0.65 * flow.in).toFixed(3)})`;
  const outgoing = `rgba(138,128,240,${(0.35 + 0.65 * flow.out).toFixed(3)})`;
  const borderGradient =
    flow.in >= 0.015 && flow.out >= 0.015
      ? `linear-gradient(135deg,${incoming} 0%,${incoming} 44%,${outgoing} 56%,${outgoing} 100%)`
      : `linear-gradient(135deg,${flow.in >= 0.015 ? incoming : outgoing},${flow.in >= 0.015 ? incoming : outgoing})`;
  const shadows: string[] = [];
  if (flow.in >= 0.015) {
    shadows.push(
      `${Math.round(-2 - 4 * flow.in)}px ${Math.round(-1 - 2 * flow.in)}px ${Math.round(10 + 24 * flow.in)}px ${Math.round(1 + 3 * flow.in)}px rgba(83,226,221,${(0.76 * flow.in).toFixed(3)})`,
      `inset 2px 2px ${Math.round(6 + 11 * flow.in)}px rgba(83,226,221,${(0.18 * flow.in).toFixed(3)})`,
    );
  }
  if (flow.out >= 0.015) {
    shadows.push(
      `${Math.round(2 + 4 * flow.out)}px ${Math.round(1 + 2 * flow.out)}px ${Math.round(10 + 24 * flow.out)}px ${Math.round(1 + 3 * flow.out)}px rgba(138,128,240,${(0.8 * flow.out).toFixed(3)})`,
      `inset -2px -2px ${Math.round(6 + 11 * flow.out)}px rgba(138,128,240,${(0.2 * flow.out).toFixed(3)})`,
    );
  }
  return {
    background: `linear-gradient(var(--color-surface),var(--color-surface)) padding-box,${borderGradient} border-box`,
    borderColor: "transparent",
    boxShadow: shadows.join(","),
    outline: `1px solid rgba(${red},${green},${blue},${(borderAlpha * 0.6).toFixed(3)})`,
    outlineOffset: "1px",
  };
}

export function ProjectCard({
  summary,
  now,
  flow,
  compact = false,
}: {
  summary: ProjectSummary;
  now: number;
  flow: FlowStrength;
  compact?: boolean;
}) {
  const requestAge = summary.lastRequestAt === null ? Number.POSITIVE_INFINITY : now - summary.lastRequestAt;
  const activity = flow.in > 0.04 || flow.out > 0.04 || requestAge <= 10_000 ? "live" : requestAge <= 60_000 ? "recent" : "idle";
  const graphData = summary.buckets.map((bucket) => ({
    label: new Date(bucket.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    saved: storedCount(bucket.memory),
    automatic: -bucket.economics.automaticHits,
    manual: -bucket.economics.manualHits,
    empty: -bucket.economics.automaticMisses,
  }));
  const recentAgents = AGENTS.filter((agent) => summary.agents[agent] > 0);
  const avoided = summary.economics.modeledRetrievals > 0
    ? fmtCompactRange(summary.economics.estimatedAvoidedTokensLow, summary.economics.estimatedAvoidedTokensHigh)
    : "—";
  const avoidedExact = summary.economics.modeledRetrievals > 0
    ? `${fmtNum(summary.economics.estimatedAvoidedTokensLow)}–${fmtNum(summary.economics.estimatedAvoidedTokensHigh)} tokens`
    : undefined;
  const automaticRate = summary.economics.automaticAttempts > 0
    ? `${Math.round(summary.economics.automaticHits / summary.economics.automaticAttempts * 100)}%`
    : "—";

  if (compact) {
    return (
      <Link
        to={`/requests?project=${encodeURIComponent(summary.project)}`}
        aria-label={`Open live requests for ${summary.project}`}
        className="block min-w-0 no-underline"
      >
        <Card
          className="flex h-full min-h-[168px] flex-col gap-2 p-3 transition-[border-color,box-shadow,background-color] duration-300 hover:border-turq/40 hover:bg-surface2/45"
          style={glowStyle(flow)}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate font-display text-[13px] font-semibold text-fg1" title={summary.project}>
                {summary.project}
              </div>
              <div className="mt-0.5 text-[10px] text-fg3">
                {summary.lastActivityAt === null ? "no recorded activity" : `last active ${timeAgo(summary.lastActivityAt)}`}
              </div>
            </div>
            <span className="inline-flex flex-none items-center gap-1.5 text-[10px] text-fg3">
              <span
                className={`h-1.5 w-1.5 rounded-full ${activity === "live" ? "animate-pulse" : ""}`}
                style={{ background: activity === "idle" ? "var(--color-na)" : activity === "live" ? "var(--color-turq)" : "var(--color-s1)" }}
              />
              {activity}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-1.5">
            <div className="min-w-0 rounded-md border border-line bg-side/55 px-1.5 py-1.5">
              <div className="font-display text-[10px] font-medium leading-tight text-fg3 [overflow-wrap:anywhere]" data-readable-text><HelpTerm id="save-reliability">Saved</HelpTerm></div>
              <div className="whitespace-nowrap font-display text-sm font-bold text-turq" data-readable-text>{fmtNum(storedCount(summary.memory))}<span className="text-[10px] font-normal text-fg3">/{fmtNum(storageAttempts(summary.memory))}</span></div>
            </div>
            <div className="min-w-0 rounded-md border border-line bg-side/55 px-1.5 py-1.5">
              <div className="font-display text-[10px] font-medium leading-tight text-fg3 [overflow-wrap:anywhere]" data-readable-text><HelpTerm id="automatic-recall">Recall rate</HelpTerm></div>
              <div className="whitespace-nowrap font-display text-sm font-bold text-peri" data-readable-text>{automaticRate}</div>
            </div>
            <div className="min-w-0 rounded-md border border-line bg-side/55 px-1.5 py-1.5">
              <div className="font-display text-[10px] font-medium leading-tight text-fg3 [overflow-wrap:anywhere]" data-readable-text><HelpTerm id="estimated-context-avoided">Context avoided</HelpTerm></div>
              <div className="whitespace-nowrap font-display text-sm font-bold text-fg1" title={avoidedExact} aria-label={avoidedExact ?? "No modeled context avoided"} data-readable-text>{avoided}</div>
            </div>
          </div>

          <div className="grid min-h-[60px] grid-cols-[minmax(0,1fr)_88px] gap-2">
            <div className="flex min-w-0 flex-col justify-between">
              <div className="flex min-h-5 flex-wrap items-center gap-1.5 overflow-hidden">
                {recentAgents.length > 0 ? (
                  recentAgents.map((agent) => (
                    <span key={agent} className="inline-flex items-center gap-1">
                      <AgentPill agent={agent === "unknown" ? null : agent} />
                      <span className="font-mono text-[10px] text-fg2">{fmtNum(summary.agents[agent])}</span>
                    </span>
                  ))
                ) : summary.lastAgent ? (
                  <AgentPill agent={summary.lastAgent === "unknown" ? null : summary.lastAgent} />
                ) : (
                  <span className="text-[10px] text-fg3">No attributed activity</span>
                )}
              </div>
              <div className="grid gap-x-2 gap-y-0.5 font-mono text-[10px] leading-[1.25] text-fg3 [grid-template-columns:repeat(auto-fit,minmax(84px,1fr))]">
                <span className="whitespace-nowrap"><span className="text-fg1">{fmtNum(summary.requestsPerMinute)}</span> rpm</span>
                <span className="whitespace-nowrap"><span className="text-turq">{fmtNum(summary.economics.automaticHits)}/{fmtNum(summary.economics.automaticAttempts)}</span> auto</span>
                <span className="whitespace-nowrap"><span className="text-peri">{fmtNum(summary.lifecycle.observation_capture + summary.lifecycle.memory_save)}</span> captured</span>
                <span className="whitespace-nowrap"><span className="text-fg1">{fmtNum(summary.errorCount)}</span> errors</span>
                <span className="whitespace-nowrap"><span className="text-fg1">{summary.p95Ms > 0 ? fmtMs(summary.p95Ms) : "—"}</span> p95</span>
              </div>
            </div>

            <div className="h-[60px] min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={graphData} barCategoryGap="18%">
                  <ReferenceLine y={0} stroke="var(--color-linestrong)" />
                  <Bar dataKey="saved" fill="var(--color-turq)" radius={[2,2,0,0]} isAnimationActive={false} />
                  <Bar dataKey="automatic" stackId="out" fill="var(--color-peri)" radius={[0,0,2,2]} isAnimationActive={false} />
                  <Bar dataKey="manual" stackId="out" fill="var(--color-s1)" isAnimationActive={false} />
                  <Bar dataKey="empty" stackId="out" fill="var(--color-warn)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Card>
      </Link>
    );
  }

  return (
    <Link
      to={`/requests?project=${encodeURIComponent(summary.project)}`}
      aria-label={`Open live requests for ${summary.project}`}
      className="block min-w-0 no-underline"
    >
      <Card
        className="flex h-full min-h-[390px] flex-col gap-3.5 p-4 transition-[border-color,box-shadow,background-color] duration-300 hover:border-turq/40 hover:bg-surface2/45"
        style={glowStyle(flow)}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate font-display text-[15px] font-semibold text-fg1" title={summary.project}>
              {summary.project}
            </div>
            <div className="mt-1 text-[11px] text-fg3">
              {summary.lastActivityAt === null ? "no recorded activity" : `last active ${timeAgo(summary.lastActivityAt)}`}
            </div>
          </div>
          <span className="inline-flex flex-none items-center gap-1.5 text-[11px] text-fg3">
            <span
              className={`h-2 w-2 rounded-full ${activity === "live" ? "animate-pulse" : ""}`}
              style={{ background: activity === "idle" ? "var(--color-na)" : activity === "live" ? "var(--color-turq)" : "var(--color-s1)" }}
            />
            {activity}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-lg border border-line bg-side/55 px-3 py-2"><Eyebrow>Stored · 15m</Eyebrow><div className="mt-1 font-display text-xl font-bold text-turq">{fmtNum(storedCount(summary.memory))}<span className="ml-1 text-[10px] font-normal text-fg3">of {fmtNum(storageAttempts(summary.memory))} attempts</span></div><div className="text-[9px] text-fg3">{fmtNum(summary.memory.observationStored)} observations · {fmtNum(summary.memory.explicitMemoriesStored)} explicit</div></div>
          <div className="rounded-lg border border-line bg-side/55 px-3 py-2"><Eyebrow>Automatic recall</Eyebrow><div className="mt-1 font-display text-xl font-bold text-peri">{automaticRate}<span className="ml-1 text-[10px] font-normal text-fg3">{fmtNum(summary.economics.automaticHits)} of {fmtNum(summary.economics.automaticAttempts)}</span></div><div className="text-[9px] text-fg3">{fmtNum(summary.economics.automaticContextTokens)} context tokens delivered</div></div>
          <div className="rounded-lg border border-line bg-side/55 px-3 py-2"><Eyebrow>Estimated context avoided</Eyebrow><div className="mt-1 whitespace-nowrap font-display text-xl font-bold text-fg1" title={avoidedExact} aria-label={avoidedExact ?? "No modeled context avoided"}>{avoided}</div><div className="text-[9px] text-fg3">{fmtNum(summary.economics.modeledRetrievals)} injections · {estimateLabel(summary.economics) === "legacy_low" ? "modeled, low confidence" : "live byte model"}</div></div>
        </div>

        <div className="rounded-lg border border-line bg-side/45 px-3 py-2 font-mono text-[10px]">
          <div className="mb-1 flex items-center justify-between gap-2 text-fg3"><span>Memory lifecycle</span><span>context is returned, not proof the agent used it</span></div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <span className="text-turq">{fmtNum(summary.economics.automaticHits)}/{fmtNum(summary.economics.automaticAttempts)} automatic hits</span>
            <span className="text-s1">{fmtNum(summary.economics.manualContextTokens)} manual tokens</span>
            <span className="text-peri">{fmtNum(summary.lifecycle.observation_capture)} observations</span>
            <span className="text-fg2">{fmtNum(summary.lifecycle.memory_save)} explicit saves</span>
            <span className="text-fg2">{fmtNum(summary.quality.conceptTagged)}/{fmtNum(summary.quality.total)} semantic</span>
            <span className={summary.derivedWork.failed > 0 ? "text-bad" : summary.derivedWork.queued > 0 ? "text-warn" : "text-fg2"}>{fmtNum(summary.derivedWork.queued + summary.derivedWork.running)} derived backlog</span>
            {summary.unscopedResults + summary.crossProjectResults > 0 ? <span className="text-bad">{fmtNum(summary.unscopedResults + summary.crossProjectResults)} scope warnings</span> : null}
          </div>
        </div>

        <div>
          <div className="mb-1.5"><Eyebrow>Agents · last 15 minutes</Eyebrow></div>
          <div className="flex min-h-6 flex-wrap items-center gap-2">
            {recentAgents.length > 0 ? (
              recentAgents.map((agent) => (
                <span key={agent} className="inline-flex items-center gap-1">
                  <AgentPill agent={agent === "unknown" ? null : agent} />
                  <span className="font-mono text-[11px] text-fg2">{fmtNum(summary.agents[agent])}</span>
                </span>
              ))
            ) : summary.lastAgent ? (
              <span className="inline-flex items-center gap-2 text-[11px] text-fg3">
                last known <AgentPill agent={summary.lastAgent === "unknown" ? null : summary.lastAgent} />
              </span>
            ) : (
              <span className="text-[11px] text-fg3">No attributed activity</span>
            )}
          </div>
        </div>

        <div>
          <div className="mb-1 flex justify-between text-[9px] text-fg3"><span>saved into memory ↑</span><span>automatic / manual context ↓</span></div>
        <div className="h-[92px] min-h-[92px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={graphData} barCategoryGap="18%">
              <Tooltip
                cursor={{ fill: "rgb(var(--rgb-fg) / 0.05)" }}
                contentStyle={{
                  background: "var(--color-tooltip)",
                  border: "1px solid var(--color-linestrong)",
                  borderRadius: 8,
                  color: "var(--color-fg2)",
                  fontSize: 11,
                }}
              />
              <ReferenceLine y={0} stroke="var(--color-linestrong)" />
              <Bar dataKey="saved" fill="var(--color-turq)" radius={[3,3,0,0]} isAnimationActive={false} />
              <Bar dataKey="automatic" stackId="out" fill="var(--color-peri)" radius={[0,0,3,3]} isAnimationActive={false} />
              <Bar dataKey="manual" stackId="out" fill="var(--color-s1)" isAnimationActive={false} />
              <Bar dataKey="empty" stackId="out" fill="var(--color-warn)" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        </div>

        <div className="mt-auto grid grid-cols-4 gap-2 border-t border-line pt-3">
          <div><Eyebrow>Req/min</Eyebrow><div className="mt-1 font-mono text-xs text-fg1">{fmtNum(summary.requestsPerMinute)}</div></div>
          <div><Eyebrow>Actions</Eyebrow><div className="mt-1 font-mono text-xs text-fg1">{fmtNum(summary.requestCount)}</div></div>
          <div><Eyebrow>Errors</Eyebrow><div className="mt-1 font-mono text-xs text-fg1">{fmtNum(summary.errorCount)}</div></div>
          <div><Eyebrow>p95</Eyebrow><div className="mt-1 font-mono text-xs text-fg1">{summary.p95Ms > 0 ? fmtMs(summary.p95Ms) : "—"}</div></div>
        </div>
        <div className="-mt-2 flex flex-wrap gap-x-3 font-mono text-[9px] text-fg3" aria-label="HTTP verb diagnostics">
          <span>HTTP</span>{(["get", "post", "put", "delete", "other"] as ProjectMethod[]).map((method) => <span key={method} style={{ color: METHOD_COLORS[method] }}>{method.toUpperCase()} {fmtNum(summary.methods[method])}</span>)}
        </div>
      </Card>
    </Link>
  );
}

export default function Projects() {
  const { tick, requests, projectFlows } = useLive();
  const [snapshot, setSnapshot] = useState<ProjectsSnapshot | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [reorderInterval, setReorderInterval] = useState<ReorderInterval>(loadProjectReorderInterval);
  const [order, setOrder] = useState<string[]>([]);
  const memory = useMemoryEffectiveness();
  const { preference, sectionVisible, count } = usePagePreferences("projects");

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<ProjectsSnapshot>("/api/projects");
      if (disposed) return;
      if (next) setSnapshot(next);
      setLoaded(true);
    };
    void refresh();
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, SNAPSHOT_REFRESH_MS);
    const visible = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);

  const projects = useMemo(() => {
    if (!snapshot) return [];
    const byName = new Map(snapshot.projects.map((project) => [project.project, cloneProjectSummary(project)]));
    const deltas = requests
      .filter((request) => request.id > snapshot.latestRequestId && request.project?.trim())
      .sort((a, b) => a.id - b.id);
    for (const request of deltas) {
      const project = request.project!.trim();
      const summary = byName.get(project) ?? emptyProjectSummary(project, now);
      applyProjectRequest(summary, request, now);
      byName.set(project, summary);
    }
    return [...byName.values()];
  }, [snapshot, requests, now]);

  const latestProjects = useRef<ProjectSummary[]>([]);
  latestProjects.current = projects;
  const namesKey = useMemo(
    () => projects.map((project) => project.project).sort().join("\u0000"),
    [projects],
  );

  const reorderNow = useCallback(() => {
    setOrder(sortProjectNames(latestProjects.current));
  }, []);

  useEffect(() => {
    setOrder((previous) => {
      const sorted = sortProjectNames(latestProjects.current);
      if (previous.length === 0) return sorted;
      const known = new Set(sorted);
      const stable = previous.filter((project) => known.has(project));
      const seen = new Set(stable);
      return [...stable, ...sorted.filter((project) => !seen.has(project))];
    });
  }, [namesKey]);

  useEffect(() => {
    saveProjectReorderInterval(reorderInterval);
    if (reorderInterval === "manual") return;
    const interval = window.setInterval(reorderNow, reorderInterval);
    return () => window.clearInterval(interval);
  }, [reorderInterval, reorderNow]);

  const orderedProjects = useMemo(() => {
    const byName = new Map(projects.map((project) => [project.project, project]));
    const seen = new Set<string>();
    const result: ProjectSummary[] = [];
    for (const name of order) {
      const project = byName.get(name);
      if (project) {
        result.push(project);
        seen.add(name);
      }
    }
    for (const project of projects) {
      if (!seen.has(project.project)) result.push(project);
    }
    return result;
  }, [projects, order]);
  const activeFlows = useMemo(() => projectFlowStrengths(projectFlows, now), [projectFlows, now]);
  const projectNames = useMemo(() => orderedProjects.map((project) => project.project), [orderedProjects]);
  useRegisterProjects("projects", projectNames);
  const visibleNames = useMemo(() => orderProjectNames(projectNames, preference, count("projectCount", 100)), [projectNames, preference, count]);
  const visibleSet = useMemo(() => new Set(visibleNames), [visibleNames]);
  const visibleProjects = orderedProjects.filter((project) => visibleSet.has(project.project)).sort((a, b) => visibleNames.indexOf(a.project) - visibleNames.indexOf(b.project));

  return (
    <div className="flex min-h-full flex-col gap-5">
      <PageHeader
        title="Projects"
        helpId="project-integrity"
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{fmtNum(projects.length)} known projects · rolling 15-minute request activity</span>
            <span className="text-[11px] text-fg3">GET/POST are HTTP verbs; lookups include POST search/context calls</span>
            <span className="inline-flex items-center gap-1 text-[11px]"><span className="h-1.5 w-1.5 rounded-full bg-turq" /> turquoise in</span>
            <span className="inline-flex items-center gap-1 text-[11px]"><span className="h-1.5 w-1.5 rounded-full bg-peri" /> violet out</span>
          </span>
        }
        right={
          <div className="flex items-center gap-2">
            <SelectBox
              label="Reorder"
              value={String(reorderInterval)}
              onChange={(value) => setReorderInterval(parseReorderInterval(value))}
              options={[
                { value: "15000", label: "Every 15 seconds" },
                { value: "30000", label: "Every 30 seconds" },
                { value: "60000", label: "Every 60 seconds" },
                { value: "300000", label: "Every 5 minutes" },
                { value: "manual", label: "Manual" },
              ]}
            />
            {reorderInterval === "manual" ? (
              <button
                type="button"
                onClick={reorderNow}
                className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3 py-2 font-display text-xs font-semibold text-fg1 hover:border-turq/50"
              >
                <RefreshCw size={13} />
                Reorder now
              </button>
            ) : null}
          </div>
        }
      />

      {sectionVisible("metrics") ? <div style={{ order: preference.sectionOrder.indexOf("metrics") }}><MetricsTiles tick={tick} empty={!tick} /></div> : null}
      {sectionVisible("memoryFlow") ? <div style={{ order: preference.sectionOrder.indexOf("memoryFlow") }}><MemoryEffectiveness snapshot={memory} /></div> : null}

      {!sectionVisible("projects") ? null : <div style={{ order: preference.sectionOrder.indexOf("projects") }}>{!loaded ? (
        <Card className="flex min-h-[280px] items-center justify-center">
          <div className="inline-flex items-center gap-2 text-sm text-fg3">
            <RefreshCw size={16} className="animate-spin" /> Loading projects…
          </div>
        </Card>
      ) : snapshot === null ? (
        <Card className="flex min-h-[280px] items-center justify-center">
          <EmptyState
            icon={<Activity size={24} />}
            title="Projects unavailable"
            body="The console API did not answer. Existing dashboard metrics will resume when it reconnects."
          />
        </Card>
      ) : visibleProjects.length === 0 ? (
        <Card className="flex min-h-[280px] items-center justify-center">
          <EmptyState
            icon={<FolderKanban size={24} />}
            title="No projects yet"
            body="A project card appears after AgentMemory records a project session or the proxy captures scoped traffic."
          />
        </Card>
      ) : (
        <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(380px,1fr))]">
          {visibleProjects.map((project) => (
            <ProjectCard
              key={project.project}
              summary={project}
              now={now}
              flow={activeFlows.get(project.project) ?? { in: 0, out: 0 }}
            />
          ))}
        </div>
      )}</div>}
    </div>
  );
}
