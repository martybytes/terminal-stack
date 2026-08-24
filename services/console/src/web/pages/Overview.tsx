import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowUpRight, BrainCircuit, FolderKanban, RefreshCw } from "lucide-react";
import type { BillingStatusSnapshot, LlmSnapshot, ProjectsSnapshot, ProjectSummary } from "../../shared/types";
import { llmFamilyForFunction, llmOutputThroughput } from "../../shared/llmThroughput";
import { MetricsTiles } from "../components/MetricsTiles";
import { MemoryEffectiveness, useContextAvoidedHistory, useMemoryEffectiveness } from "../components/MemoryEffectiveness";
import { Card, EmptyState, PageHeader, Pill, SelectBox } from "../components/ui";
import { apiGet } from "../lib/api";
import { fmtNum, timeAgo } from "../lib/format";
import { parseReorderInterval, sortProjectNames, type ReorderInterval } from "../lib/projectOrder";
import { useLive } from "../lib/ws";
import {
  applyProjectRequest,
  cloneProjectSummary,
  emptyProjectSummary,
  loadProjectReorderInterval,
  ProjectCard,
  projectFlowStrengths,
  saveProjectReorderInterval,
} from "./Projects";
import { CallCard, familyEstimatedCost, LlmSummaryTiles } from "./LlmCalls";
import { orderProjectNames, usePagePreferences, useRegisterProjects } from "../lib/preferences";

const PROJECT_REFRESH_MS = 5_000;
const LLM_REFRESH_MS = 3_000;
const PROJECT_LIMIT = 6;

function ViewAll({ to, children }: { to: string; children: string }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3 py-2 font-display text-xs font-semibold text-fg1 no-underline hover:border-turq/50"
    >
      {children}
      <ArrowUpRight size={13} />
    </Link>
  );
}

export default function Overview() {
  const { tick, requests, projectFlows, llmCompletions } = useLive();
  const [projectsSnapshot, setProjectsSnapshot] = useState<ProjectsSnapshot | null>(null);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [llmSnapshot, setLlmSnapshot] = useState<LlmSnapshot | null>(null);
  const [llmLoaded, setLlmLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [reorderInterval, setReorderInterval] = useState<ReorderInterval>(loadProjectReorderInterval);
  const [projectOrder, setProjectOrder] = useState<string[]>([]);
  const memory = useMemoryEffectiveness();
  const avoidedHistory = useContextAvoidedHistory();
  const { preference, sectionVisible, count } = usePagePreferences("overview");
  const updateBilling = useCallback((billing: BillingStatusSnapshot) => {
    setLlmSnapshot((current) => current ? { ...current, cost: { ...current.cost, ...billing } } : current);
  }, []);

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<ProjectsSnapshot>("/api/projects");
      if (disposed) return;
      if (next) setProjectsSnapshot(next);
      setProjectsLoaded(true);
    };
    void refresh();
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, PROJECT_REFRESH_MS);
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
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<LlmSnapshot>("/api/llm");
      if (disposed) return;
      if (next) setLlmSnapshot(next);
      setLlmLoaded(true);
    };
    void refresh();
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, LLM_REFRESH_MS);
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
    if (!projectsSnapshot) return [];
    const byName = new Map(
      projectsSnapshot.projects.map((project) => [project.project, cloneProjectSummary(project)]),
    );
    const deltas = requests
      .filter((request) => request.id > projectsSnapshot.latestRequestId && request.project?.trim())
      .sort((a, b) => a.id - b.id);
    for (const request of deltas) {
      const project = request.project!.trim();
      const summary = byName.get(project) ?? emptyProjectSummary(project, now);
      applyProjectRequest(summary, request, now);
      byName.set(project, summary);
    }
    return [...byName.values()].sort(
      (a, b) =>
        (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0) ||
        a.project.localeCompare(b.project),
    );
  }, [projectsSnapshot, requests, now]);

  const latestProjectsRef = useRef<ProjectSummary[]>([]);
  latestProjectsRef.current = projects;
  const projectNamesKey = useMemo(
    () => projects.map((project) => project.project).sort().join("\u0000"),
    [projects],
  );
  const reorderProjects = useCallback(() => {
    setProjectOrder(sortProjectNames(latestProjectsRef.current));
  }, []);

  useEffect(() => {
    setProjectOrder((previous) => {
      const sorted = sortProjectNames(latestProjectsRef.current);
      if (previous.length === 0) return sorted;
      const known = new Set(sorted);
      const stable = previous.filter((project) => known.has(project));
      const seen = new Set(stable);
      return [...stable, ...sorted.filter((project) => !seen.has(project))];
    });
  }, [projectNamesKey]);

  useEffect(() => {
    saveProjectReorderInterval(reorderInterval);
    if (reorderInterval === "manual") return;
    const interval = window.setInterval(reorderProjects, reorderInterval);
    return () => window.clearInterval(interval);
  }, [reorderInterval, reorderProjects]);

  const orderedProjects = useMemo(() => {
    const byName = new Map(projects.map((project) => [project.project, project]));
    const seen = new Set<string>();
    const result: ProjectSummary[] = [];
    for (const name of projectOrder) {
      const project = byName.get(name);
      if (!project) continue;
      result.push(project);
      seen.add(name);
    }
    for (const project of projects) {
      if (!seen.has(project.project)) result.push(project);
    }
    return result;
  }, [projects, projectOrder]);
  const projectNames = useMemo(() => orderedProjects.map((project) => project.project), [orderedProjects]);
  useRegisterProjects("overview", projectNames);
  const latestNames = useMemo(() => orderProjectNames(projectNames, preference, count("projectCount", PROJECT_LIMIT)), [projectNames, preference, count]);
  const latestProjects = latestNames.flatMap((name) => orderedProjects.find((project) => project.project === name) ?? []);
  const activeFlows = useMemo(
    () => projectFlowStrengths(projectFlows, now),
    [projectFlows, now],
  );

  return (
    <div className="flex min-h-full flex-col gap-2" data-testid="overview-page">
      <PageHeader
        title="Projects"
        subtitle={`${fmtNum(projects.length)} known projects · six most recently active`}
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
                onClick={reorderProjects}
                className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3 py-2 font-display text-xs font-semibold text-fg1 hover:border-turq/50"
              >
                <RefreshCw size={13} />
                Reorder now
              </button>
            ) : null}
            <ViewAll to="/projects">View all projects</ViewAll>
          </div>
        }
      />

      {sectionVisible("metrics") ? <div style={{ order: preference.sectionOrder.indexOf("metrics") }}><MetricsTiles tick={tick} empty={!tick} /></div> : null}
      {sectionVisible("memoryFlow") ? <div style={{ order: preference.sectionOrder.indexOf("memoryFlow") }}><MemoryEffectiveness snapshot={memory} compact avoidedHistory={avoidedHistory} /></div> : null}

      {!sectionVisible("projects") ? null : <div style={{ order: preference.sectionOrder.indexOf("projects") }}>{!projectsLoaded ? (
        <Card className="flex min-h-[168px] items-center justify-center">
          <div className="inline-flex items-center gap-2 text-sm text-fg3">
            <RefreshCw size={16} className="animate-spin" /> Loading projects…
          </div>
        </Card>
      ) : projectsSnapshot === null ? (
        <Card className="flex min-h-[168px] items-center justify-center">
          <EmptyState
            icon={<Activity size={22} />}
            title="Projects unavailable"
            body="The console API did not answer."
          />
        </Card>
      ) : latestProjects.length === 0 ? (
        <Card className="flex min-h-[168px] items-center justify-center">
          <EmptyState
            icon={<FolderKanban size={22} />}
            title="No projects yet"
            body="Recent projects will appear here as AgentMemory records activity."
          />
        </Card>
      ) : (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]" data-testid="overview-projects">
          {latestProjects.map((project: ProjectSummary) => (
            <ProjectCard
              key={project.project}
              summary={project}
              now={now}
              flow={activeFlows.get(project.project) ?? { in: 0, out: 0 }}
              compact
            />
          ))}
        </div>
      )}</div>}

      {sectionVisible("llmSummary") || sectionVisible("llmFamilies") ? <div style={{ order: Math.min(preference.sectionOrder.indexOf("llmSummary"), preference.sectionOrder.indexOf("llmFamilies")) }}><PageHeader
        title="LLM Calls"
        subtitle="safe completion telemetry and configured AgentMemory LLM features"
        right={
          <div className="flex items-center gap-2">
            {llmSnapshot ? (
              <div className="hidden items-center gap-2 text-[11px] text-fg3 xl:flex">
                <Pill tone={llmSnapshot.upstreamOk ? "ok" : "bad"}>
                  {llmSnapshot.upstreamOk ? "TELEMETRY LIVE" : "UPSTREAM OFFLINE"}
                </Pill>
                updated {timeAgo(llmSnapshot.ts)}
              </div>
            ) : null}
            <ViewAll to="/llm">Open LLM Calls</ViewAll>
          </div>
        }
      />

      {!sectionVisible("llmSummary") && !sectionVisible("llmFamilies") ? null : !llmLoaded ? (
        <Card className="flex min-h-[180px] items-center justify-center">
          <div className="inline-flex items-center gap-2 text-sm text-fg3">
            <RefreshCw size={16} className="animate-spin" /> Loading LLM telemetry…
          </div>
        </Card>
      ) : llmSnapshot === null ? (
        <Card className="flex min-h-[180px] items-center justify-center">
          <EmptyState
            icon={<BrainCircuit size={22} />}
            title="LLM telemetry unavailable"
            body="The console API did not answer."
          />
        </Card>
      ) : (
        <>
          {sectionVisible("llmSummary") ? <LlmSummaryTiles snapshot={llmSnapshot} compact onBillingUpdated={updateBilling} /> : null}
          {sectionVisible("llmFamilies") ? <section data-testid="overview-llm-families">
            <div className="mb-2 flex items-end justify-between gap-3">
              <div>
                <div className="font-display text-[14px] font-semibold text-fg1">Tracked call families</div>
                <div className="mt-0.5 text-[11px] text-fg3">
                  Cards glow turquoise on successful completions and coral when failures are detected.
                </div>
              </div>
              <div className="text-[10px] text-fg3">rolling {Math.round(llmSnapshot.windowMs / 60_000)} minutes</div>
            </div>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
              {llmSnapshot.functions.map((summary) => (
                (() => {
                  const throughput = llmOutputThroughput(llmSnapshot.calls, { since: now - llmSnapshot.windowMs, family: llmFamilyForFunction(summary.functionId) });
                  return <CallCard
                    key={summary.functionId}
                    summary={summary}
                    events={llmCompletions}
                    now={now}
                    compact
                    costNanos={familyEstimatedCost(llmSnapshot, summary.functionId)}
                    showCost={llmSnapshot.config.costApplicability !== "local"}
                    tokensPerSecond={throughput.tokensPerSecond}
                    throughputSamples={throughput.measuredCalls}
                  />;
                })()
              ))}
            </div>
          </section> : null}
        </>
      )}</div> : null}
    </div>
  );
}
