import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { BarChart3, Download, RefreshCw, ShieldAlert } from "lucide-react";
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  ReportLlmResponse,
  ReportMemoryResponse,
  ReportMeta,
  ReportProjectRow,
  ReportProjectsResponse,
  ReportSection,
  ReportSummaryResponse,
  ReportSystemResponse,
} from "../../shared/types";
import { AgentPill, Card, EmptyState, PageHeader, Pill, SelectBox, StatTile } from "../components/ui";
import { apiGet } from "../lib/api";
import { fmtCompactNum, fmtCompactRange, fmtMs, fmtNum, fmtTokensPerSecond, fmtUptime, fmtUsdNanos, timeAgo } from "../lib/format";
import { usePagePreferences } from "../lib/preferences";

const DAY_MS = 86_400_000;
const REFRESH_MS = 15_000;
const RANGE_KEY = "agent007memory.report-range.v1";
const COMPARE_KEY = "agent007memory.report-compare.v1";
type RangePreset = "1h" | "24h" | "7d" | "30d" | "90d" | "1y" | "custom";
type ReportViewSection = "overview" | ReportSection;
interface ReportOverviewData {
  summary: ReportSummaryResponse;
  projects: ReportProjectsResponse;
  memory: ReportMemoryResponse;
  llm: ReportLlmResponse;
  system: ReportSystemResponse;
}
type ReportData = ReportOverviewData | ReportSummaryResponse | ReportProjectsResponse | ReportMemoryResponse | ReportLlmResponse | ReportSystemResponse;

const PRESET_MS: Record<Exclude<RangePreset, "custom">, number> = {
  "1h": 3_600_000,
  "24h": DAY_MS,
  "7d": 7 * DAY_MS,
  "30d": 30 * DAY_MS,
  "90d": 90 * DAY_MS,
  "1y": 365 * DAY_MS,
};

const TOOLTIP_PROPS = {
  contentStyle: {
    background: "var(--color-tooltip)",
    border: "1px solid rgb(var(--rgb-fg) / 0.16)",
    borderRadius: 8,
    color: "var(--color-fg2)",
    fontSize: 11,
  },
  labelStyle: { color: "var(--color-fg1)" },
};

function initialRange(): RangePreset {
  try {
    const stored = window.localStorage.getItem(RANGE_KEY) as RangePreset | null;
    if (stored && (stored === "custom" || stored in PRESET_MS)) return stored;
  } catch { /* storage is optional */ }
  return "24h";
}

function initialCompare(): boolean {
  try { return window.localStorage.getItem(COMPARE_KEY) !== "false"; }
  catch { return true; }
}

function localInput(ts: number): string {
  const date = new Date(ts - new Date(ts).getTimezoneOffset() * 60_000);
  return date.toISOString().slice(0, 16);
}

function chartLabel(ts: number, span: number): string {
  const date = new Date(ts);
  return span <= DAY_MS
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function percent(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(value >= 0.995 ? 1 : 2)}%`;
}

function delta(current: number, previous: number | null, suffix = ""): ReactNode {
  if (previous === null) return "comparison unavailable";
  if (previous === 0) return current === 0 ? "no change" : `new vs prior period`;
  const change = ((current - previous) / Math.abs(previous)) * 100;
  return <span style={{ color: change > 0 ? "#8FEDEA" : change < 0 ? "var(--color-bad-bright)" : undefined }}>{change > 0 ? "+" : ""}{change.toFixed(1)}%{suffix}</span>;
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Card className="flex h-[270px] min-w-0 flex-col p-4">
      <div className="font-display text-[13px] font-semibold text-fg1">{title}</div>
      {subtitle ? <div className="mt-0.5 text-[10px] text-fg3">{subtitle}</div> : null}
      <div className="mt-3 min-h-0 flex-1">{children}</div>
    </Card>
  );
}

function Axes({ dataKey = "label" }: { dataKey?: string }) {
  return (
    <>
      <XAxis dataKey={dataKey} tickLine={false} axisLine={false} tick={{ fill: "var(--color-fg3)", fontSize: 10 }} interval="preserveStartEnd" minTickGap={48} height={18} />
      <YAxis hide domain={[0, "auto"]} />
    </>
  );
}

function OverviewProjectCard({ row }: { row: ReportProjectRow }) {
  return (
    <Card className="flex min-h-[150px] min-w-0 flex-col gap-2.5 p-3">
      <div className="truncate font-display text-[13px] font-semibold text-fg1" title={row.project}>
        {row.project}
      </div>
      <div className="grid grid-cols-4 gap-1.5 font-mono text-[10px]">
        <div className="rounded-md border border-line bg-side/45 px-1.5 py-2 text-turq">GET <span className="float-right text-fg1">{fmtNum(row.methods.get)}</span></div>
        <div className="rounded-md border border-line bg-side/45 px-1.5 py-2 text-peri">POST <span className="float-right text-fg1">{fmtNum(row.methods.post)}</span></div>
        <div className="rounded-md border border-line bg-side/45 px-1.5 py-2 text-ok">PUT <span className="float-right text-fg1">{fmtNum(row.methods.put)}</span></div>
        <div className="rounded-md border border-line bg-side/45 px-1.5 py-2 text-bad">DEL <span className="float-right text-fg1">{fmtNum(row.methods.delete)}</span></div>
      </div>
      <div className="flex min-h-5 flex-wrap gap-1 overflow-hidden">
        {row.agents.slice(0, 3).map((entry) => (
          <span key={entry.agent} className="inline-flex items-center gap-1">
            <AgentPill agent={entry.agent === "unknown" ? null : entry.agent} />
            <span className="font-mono text-[10px] text-fg2">{fmtNum(entry.count)}</span>
          </span>
        ))}
      </div>
      <div className="mt-auto flex flex-wrap gap-x-3 gap-y-1 font-mono text-[9px] text-fg3">
        <span><span className="text-fg1">{fmtNum(row.requests)}</span> actions</span>
        <span><span className="text-fg1">{fmtNum(row.observations)}</span> observations</span>
        <span><span className="text-fg1">{fmtNum(row.errors)}</span> errors</span>
        <span><span className="text-fg1">{row.p95Ms > 0 ? fmtMs(row.p95Ms) : "—"}</span> p95</span>
      </div>
    </Card>
  );
}

function OverviewReport({ data }: { data: ReportOverviewData }) {
  const { count } = usePagePreferences("reports");
  const { summary, projects, memory, llm, system } = data;
  const span = summary.range.to - summary.range.from;
  const series = summary.series.map((point) => ({
    ...point,
    label: chartLabel(point.t, span),
    observations: point.rawObservations + point.compressedObservations,
  }));
  const llmByTime = new Map<number, { t: number; label: string; calls: number; failures: number }>();
  for (const point of llm.series) {
    const current = llmByTime.get(point.t) ?? {
      t: point.t,
      label: chartLabel(point.t, span),
      calls: 0,
      failures: 0,
    };
    current.calls += point.calls;
    current.failures += point.failures;
    llmByTime.set(point.t, current);
  }
  const llmCalls = llm.rows.reduce((total, row) => total + row.calls, 0);
  const llmSuccesses = llm.rows.reduce((total, row) => total + row.successes, 0);
  const llmFailures = llm.rows.reduce((total, row) => total + row.failures, 0);
  const llmLatencyTotal = llm.rows.reduce(
    (total, row) => total + row.avgLatencyMs * row.calls,
    0,
  );
  const uptime = system.series.at(-1)?.uptimeSec ?? null;
  const topProjects = projects.rows.slice(0, count("projectCount", 6));
  const billingScope = llm.providerCosts[0]?.scopeLabel || "active OpenAI project";
  const localCalls = llm.usageRows.reduce((total, row) => total + row.localCalls, 0);
  const showCost = llm.providerCosts.length > 0 || llm.usageRows.some((row) =>
    row.estimatedCostNanos > 0 || row.pricedCalls > 0 || row.unpricedCalls > 0
  );

  return (
    <div className="flex flex-col gap-4" data-testid="report-overview">
      <div>
        <div className="mb-2 font-display text-[14px] font-semibold text-fg1">Overview totals</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
          <StatTile label="Memories" value={fmtNum(summary.current.memoriesEnd)} sub={summary.current.memoriesChange === null ? "ending total" : `${summary.current.memoriesChange >= 0 ? "+" : ""}${fmtNum(summary.current.memoriesChange)} in period`} />
          <StatTile label="Sessions" value={fmtNum(summary.current.sessionsEnd)} sub={summary.current.sessionsChange === null ? "ending total" : `${summary.current.sessionsChange >= 0 ? "+" : ""}${fmtNum(summary.current.sessionsChange)} in period`} />
          <StatTile label="Observations" value={fmtNum(summary.current.observations)} sub={delta(summary.current.observations, summary.previous?.observations ?? null)} />
          <StatTile label="Requests / min" value={summary.current.requestsPerMinute.toFixed(1)} sub={`${fmtNum(summary.current.requests)} selected-period actions`} />
          <StatTile label="Estimated p95" value={summary.current.p95Ms > 0 ? fmtMs(summary.current.p95Ms) : "—"} sub="privacy-safe histogram" />
          <StatTile label="Last uptime" value={fmtUptime(uptime)} sub={`availability ${percent(summary.current.sampledAvailability)}`} />
        </div>
      </div>

      <section>
        <div className="mb-2">
          <div className="font-display text-[14px] font-semibold text-fg1">Memory effectiveness</div>
          <div className="mt-0.5 text-[11px] text-fg3">Historical lifecycle outcomes; returned context is measurable, actual agent use is not.</div>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
          <StatTile label="Save reliability" value={percent(memory.current.saveReliability)} sub={`${fmtNum(memory.current.stored)} stored of ${fmtNum(memory.current.storageAttempts)}`} />
          <StatTile label="Recall delivered" value={percent(memory.current.recallDeliveryRate)} sub={`${fmtNum(memory.current.hits)} returned · ${fmtNum(memory.current.misses)} empty · ${fmtNum(memory.current.retrievalFailures)} failed`} />
          <StatTile label="Context returned" value={fmtNum(memory.current.contextTokens)} sub={`${fmtNum(memory.current.contextBlocks)} blocks`} />
          <StatTile label="Stored by kind" value={fmtNum(memory.current.stored)} sub={`${fmtNum(memory.current.observationsCaptured)} observation attempts · ${fmtNum(memory.current.memoriesSaved)} explicit attempts`} />
          <StatTile label="Project matches" value={fmtNum(memory.current.projectMatches)} sub={`${fmtNum(memory.current.resultCount)} returned results`} />
          <StatTile label="Scope warnings" value={fmtNum(memory.current.unscopedResults + memory.current.crossProjectResults)} sub="unscoped + cross-project results" />
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-end justify-between gap-3">
          <div>
            <div className="font-display text-[14px] font-semibold text-fg1">Projects</div>
            <div className="mt-0.5 text-[11px] text-fg3">Six busiest projects in the selected period</div>
          </div>
          <div className="text-[10px] text-fg3">{fmtNum(projects.rows.length)} projects recorded</div>
        </div>
        {topProjects.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-6">
            {topProjects.map((row) => <OverviewProjectCard key={row.project} row={row} />)}
          </div>
        ) : (
          <Card className="px-4 py-6 text-center text-xs text-fg3">No project aggregates in this period.</Card>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-end justify-between gap-3">
          <div>
            <div className="font-display text-[14px] font-semibold text-fg1">LLM calls</div>
            <div className="mt-0.5 text-[11px] text-fg3">Historical completion counters; queue depth and waits remain live-only telemetry</div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
          <StatTile label="Completed" value={fmtNum(llmCalls)} sub="selected period" />
          <StatTile label="Success rate" value={percent(llmCalls > 0 ? llmSuccesses / llmCalls : null)} sub={`${fmtNum(llmFailures)} failures`} />
          <StatTile label="Average latency" value={llmCalls > 0 ? fmtMs(llmLatencyTotal / llmCalls) : "—"} sub="tracked families" />
          {showCost ? <StatTile label="Estimated API cost" value={fmtUsdNanos(llm.estimatedCostNanos)} sub="exact token telemetry" /> : <StatTile label="Local inference" value={fmtNum(localCalls)} sub="calls with no API fee" />}
          {showCost ? <StatTile label="Billed provider cost" value={fmtUsdNanos(llm.billedCostNanos)} sub={`${billingScope} · complete UTC days`} /> : <StatTile label="Models" value={fmtNum(new Set(llm.usageRows.map((row) => row.model)).size)} sub="local models in range" />}
          <StatTile label="Availability" value={percent(summary.current.sampledAvailability)} sub="sampled upstream" />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Overview activity" subtitle="requests, errors, and observations">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="requests" name="requests" fill="var(--color-s1)" isAnimationActive={false} /><Bar dataKey="observations" name="observations" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="errors" name="errors" fill="var(--color-bad)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="LLM completion activity" subtitle="all tracked call families">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={[...llmByTime.values()].sort((a, b) => a.t - b.t)}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="calls" name="calls" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="failures" name="failures" fill="var(--color-bad)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function MemoryReport({ data, meta, project, agent, setProject, setAgent }: { data: ReportMemoryResponse; meta: ReportMeta | null; project: string; agent: string; setProject: (value: string) => void; setAgent: (value: string) => void }) {
  const span = data.range.to - data.range.from;
  const series = data.series.map((point) => ({ ...point, label: chartLabel(point.t, span) }));
  const current = data.current;
  return (
    <div className="flex flex-col gap-4" data-testid="report-memory">
      <div className="flex flex-wrap items-center gap-3">
        <SelectBox label="Project" value={project} onChange={setProject} options={[{ value: "", label: "All projects" }, ...(meta?.projects ?? []).map((value) => ({ value, label: value }))]} />
        <SelectBox label="Agent" value={agent} onChange={setAgent} options={[{ value: "", label: "All agents" }, ...(meta?.agents ?? []).map((value) => ({ value, label: value }))]} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-8">
        <StatTile label="Automatic recall" value={current.automaticRetrievals > 0 ? percent(current.automaticHits / current.automaticRetrievals) : "—"} sub={`${fmtNum(current.automaticHits)} of ${fmtNum(current.automaticRetrievals)} delivered`} />
        <StatTile label="Context returned" value={fmtNum(current.automaticContextTokens)} sub="automatic tokens · not proof of use" />
        <StatTile label="Estimated context avoided" value={current.modeledRetrievals > 0 ? fmtCompactRange(current.estimatedAvoidedTokensLow, current.estimatedAvoidedTokensHigh) : "—"} sub={`${fmtNum(current.modeledRetrievals)} modeled · ${fmtNum(current.legacyEstimateCount)} low confidence`} />
        <StatTile label="Manual context" value={fmtNum(current.manualContextTokens)} sub={`${fmtNum(current.manualHits)} of ${fmtNum(current.manualRetrievals)} searches`} />
        <StatTile label="Save reliability" value={percent(current.saveReliability)} sub={`${fmtNum(current.stored)} stored of ${fmtNum(current.storageAttempts)}`} />
        <StatTile label="Start coverage" value={current.uniqueSessionsStarted > 0 ? percent(current.sessionsAssisted / current.uniqueSessionsStarted) : "—"} sub={`${fmtNum(current.sessionsAssisted)} assisted · ${fmtNum(current.sessionsClosed)} closed`} />
        <StatTile label="Token budget" value={fmtNum(current.budgetTokens)} sub={`${fmtNum(current.truncatedRetrievals)} truncated · ${fmtNum(current.oversizedRetrievals)} oversized`} />
        <StatTile label="Scope warnings" value={fmtNum(current.unscopedResults + current.crossProjectResults)} sub="result metadata" />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Automatic and manual context" subtitle="delivery is separated from explicit search"><ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="automaticContextTokens" name="automatic tokens" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="manualContextTokens" name="manual tokens" fill="var(--color-s1)" isAnimationActive={false} /></BarChart></ResponsiveContainer></ChartCard>
        <ChartCard title="Capture and lifecycle" subtitle="observations, explicit saves, starts, and ends"><ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="observationsCaptured" name="observations" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="memoriesSaved" name="saves" fill="var(--color-turq)" isAnimationActive={false} /><Bar dataKey="sessionStarts" name="starts" fill="var(--color-ok)" isAnimationActive={false} /><Bar dataKey="sessionEnds" name="ends" fill="var(--color-warn)" isAnimationActive={false} /></BarChart></ResponsiveContainer></ChartCard>
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[1180px] border-collapse text-left text-xs">
          <thead><tr className="border-b border-line text-[10px] uppercase tracking-[0.05em] text-fg3"><th className="px-4 py-3">Project</th><th>Automatic recall</th><th>Automatic context</th><th>Estimated avoided</th><th>Manual context</th><th>Save reliability</th><th>Starts assisted</th><th>Scope warnings</th></tr></thead>
          <tbody>{data.projects.map((row) => <tr key={row.project} className="border-b border-line/70 last:border-0"><td className="max-w-[280px] truncate px-4 py-3 font-display font-semibold text-fg1">{row.project || "Unscoped"}</td><td className="font-mono text-fg2">{fmtNum(row.automaticHits)} / {fmtNum(row.automaticRetrievals)}</td><td className="font-mono text-fg2">{fmtCompactNum(row.automaticContextTokens)} tokens</td><td className="font-mono text-fg2" title={row.modeledRetrievals ? `${fmtNum(row.estimatedAvoidedTokensLow)}–${fmtNum(row.estimatedAvoidedTokensHigh)} tokens` : undefined}>{row.modeledRetrievals ? fmtCompactRange(row.estimatedAvoidedTokensLow, row.estimatedAvoidedTokensHigh) : "—"}</td><td className="font-mono text-fg2">{fmtCompactNum(row.manualContextTokens)} tokens</td><td className="font-mono text-fg2">{percent(row.saveReliability)}</td><td className="font-mono text-fg2">{fmtNum(row.sessionsAssisted)} / {fmtNum(row.uniqueSessionsStarted)}</td><td className="font-mono text-fg2">{fmtNum(row.unscopedResults + row.crossProjectResults)}</td></tr>)}</tbody>
        </table>
      </Card>
    </div>
  );
}

function SummaryReport({ data }: { data: ReportSummaryResponse }) {
  const span = data.range.to - data.range.from;
  const series = data.series.map((point) => ({ ...point, label: chartLabel(point.t, span), observations: point.rawObservations + point.compressedObservations }));
  const previous = data.previous;
  const showCost = data.current.estimatedLlmCostNanos > 0 || data.current.billedProviderCostNanos !== null ||
    data.current.pricedLlmCalls > 0 || data.current.unpricedLlmCalls > 0;
  return (
    <div className="flex flex-col gap-4" data-testid="report-summary">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5 2xl:grid-cols-10">
        <StatTile label="Requests" value={fmtNum(data.current.requests)} sub={delta(data.current.requests, previous?.requests ?? null)} />
        <StatTile label="Requests / min" value={data.current.requestsPerMinute.toFixed(1)} sub="selected period" />
        <StatTile label="Error rate" value={percent(data.current.errorRate)} sub={previous ? `${((data.current.errorRate - previous.errorRate) * 100).toFixed(2)} points vs prior` : "comparison unavailable"} />
        <StatTile label="Estimated p95" value={data.current.p95Ms > 0 ? fmtMs(data.current.p95Ms) : "—"} sub={previous ? delta(data.current.p95Ms, previous.p95Ms) : "histogram estimate"} />
        <StatTile label="Observations" value={fmtNum(data.current.observations)} sub={delta(data.current.observations, previous?.observations ?? null)} />
        <StatTile label="LLM calls" value={fmtNum(data.current.llmCalls)} sub={`${fmtNum(data.current.llmFailures)} failures`} />
        {showCost ? <StatTile label="Estimated cost" value={fmtUsdNanos(data.current.estimatedLlmCostNanos)} sub="catalog estimate" /> : <StatTile label="Local LLM calls" value={fmtNum(data.current.localLlmCalls)} sub="no API fee" />}
        {showCost ? <StatTile label="Billed cost" value={fmtUsdNanos(data.current.billedProviderCostNanos)} sub="provider actual" /> : null}
        <StatTile label="Memories" value={fmtNum(data.current.memoriesEnd)} sub={data.current.memoriesChange === null ? "ending total" : `${data.current.memoriesChange >= 0 ? "+" : ""}${fmtNum(data.current.memoriesChange)} in period`} />
        <StatTile label="Availability" value={percent(data.current.sampledAvailability)} sub="sampled upstream" />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Request activity" subtitle="completed proxy actions and errors">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="requests" name="requests" fill="var(--color-s1)" isAnimationActive={false} /><Bar dataKey="errors" name="errors" fill="var(--color-bad)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Observations" subtitle="raw and compressed AgentMemory events">
          <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="rawObservations" name="raw" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} /><Line type="monotone" dataKey="compressedObservations" name="compressed" stroke="var(--color-peri)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Proxy latency" subtitle="estimated p95 from privacy-safe histogram counts">
          <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="p95Ms" name="estimated p95 ms" stroke="var(--color-turq)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="LLM completions" subtitle="tracked cumulative-counter deltas">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="llmCalls" name="calls" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="llmFailures" name="failures" fill="var(--color-bad)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function ProjectsReport({ data, meta, project, agent, setProject, setAgent }: { data: ReportProjectsResponse; meta: ReportMeta | null; project: string; agent: string; setProject: (value: string) => void; setAgent: (value: string) => void }) {
  const span = data.range.to - data.range.from;
  const series = data.series.map((point) => ({ ...point, label: chartLabel(point.t, span) }));
  return (
    <div className="flex flex-col gap-4" data-testid="report-projects">
      <div className="flex flex-wrap items-center gap-3">
        <SelectBox label="Project" value={project} onChange={setProject} options={[{ value: "", label: "All projects" }, ...(meta?.projects ?? []).map((value) => ({ value, label: value }))]} />
        <SelectBox label="Agent" value={agent} onChange={setAgent} options={[{ value: "", label: "All agents" }, ...(meta?.agents ?? []).map((value) => ({ value, label: value }))]} />
        <span className="text-[11px] text-fg3">{fmtNum(data.rows.length)} projects in range</span>
      </div>
      <ChartCard title="Project request activity" subtitle="filters apply to the trend and ranked breakdown">
        <ResponsiveContainer width="100%" height="100%"><BarChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Bar dataKey="requests" name="requests" fill="var(--color-s1)" isAnimationActive={false} /><Bar dataKey="errors" name="errors" fill="var(--color-bad)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
      </ChartCard>
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[980px] border-collapse text-left text-xs">
          <thead><tr className="border-b border-line text-[10px] uppercase tracking-[0.05em] text-fg3"><th className="px-4 py-3">Project</th><th>Actions</th><th>vs prior</th><th>Methods</th><th>Agents</th><th>Observations</th><th>Errors</th><th>Estimated p95</th></tr></thead>
          <tbody>{data.rows.map((row) => <tr key={row.project} className="border-b border-line/70 last:border-0"><td className="max-w-[280px] truncate px-4 py-3 font-display font-semibold text-fg1" title={row.project}>{row.project}</td><td className="font-mono text-fg2">{fmtNum(row.requests)}</td><td className="text-[11px] text-fg3">{delta(row.requests, row.previousRequests)}</td><td><div className="flex gap-2 font-mono text-[10px]"><span className="text-turq">G {row.methods.get}</span><span className="text-peri">P {row.methods.post}</span><span className="text-ok">U {row.methods.put}</span><span className="text-bad">D {row.methods.delete}</span></div></td><td><div className="flex flex-wrap gap-1">{row.agents.slice(0, 3).map((entry) => <AgentPill key={entry.agent} agent={entry.agent} />)}</div></td><td className="font-mono text-fg2">{fmtNum(row.observations)}</td><td className="font-mono text-fg2">{fmtNum(row.errors)} <span className="text-fg3">· {percent(row.errorRate)}</span></td><td className="font-mono text-fg2">{row.p95Ms > 0 ? fmtMs(row.p95Ms) : "—"}</td></tr>)}</tbody>
        </table>
      </Card>
    </div>
  );
}

function LlmReport({ data, meta, functionId, setFunctionId }: { data: ReportLlmResponse; meta: ReportMeta | null; functionId: string; setFunctionId: (value: string) => void }) {
  const span = data.range.to - data.range.from;
  const byTime = new Map<number, Record<string, number | string>>();
  for (const point of data.series) {
    const row = byTime.get(point.t) ?? { t: point.t, label: chartLabel(point.t, span) };
    row[point.functionId] = point.calls; row[`${point.functionId}:failures`] = point.failures; byTime.set(point.t, row);
  }
  const families = functionId ? [functionId] : (meta?.llmFunctions ?? data.rows.map((row) => row.functionId));
  const billingScope = data.providerCosts[0]?.scopeLabel || "active OpenAI project";
  const localCalls = data.usageRows.reduce((total, row) => total + row.localCalls, 0);
  const throughputTokens = data.usageRows.reduce((total, row) => total + row.throughputCompletionTokens, 0);
  const throughputLatency = data.usageRows.reduce((total, row) => total + row.throughputProviderLatencyMs, 0);
  const throughputCalls = data.usageRows.reduce((total, row) => total + row.throughputMeasuredCalls, 0);
  const outputRate = throughputLatency > 0 ? throughputTokens / (throughputLatency / 1_000) : null;
  const showCost = data.providerCosts.length > 0 || data.usageRows.some((row) =>
    row.estimatedCostNanos > 0 || row.pricedCalls > 0 || row.unpricedCalls > 0
  );
  return (
    <div className="flex flex-col gap-4" data-testid="report-llm">
      <SelectBox label="Call family" value={functionId} onChange={setFunctionId} options={[{ value: "", label: "All tracked families" }, ...(meta?.llmFunctions ?? []).map((value) => ({ value, label: value }))]} />
      <div className={`grid grid-cols-2 gap-3 ${showCost ? "xl:grid-cols-5" : "md:grid-cols-3"}`}>
        {showCost ? <StatTile label="Estimated cost" value={fmtUsdNanos(data.estimatedCostNanos)} sub="family/model telemetry" /> : <StatTile label="Local inference" value={fmtNum(localCalls)} sub="calls with no API fee" />}
        {showCost ? <StatTile label="Billed cost" value={fmtUsdNanos(data.billedCostNanos)} sub={`${billingScope} · complete UTC days`} /> : null}
        <StatTile label="Models" value={fmtNum(new Set(data.usageRows.map((row) => row.model)).size)} sub="in selected range" />
        <StatTile label="Effective output rate" value={fmtTokensPerSecond(outputRate)} sub={throughputCalls ? `${fmtNum(throughputCalls)} exact successful calls` : "not measured in this range"} dim={outputRate === null} />
        {showCost ? <StatTile label="Unpriced calls" value={fmtNum(data.usageRows.reduce((sum, row) => sum + row.unpricedCalls, 0))} sub="not treated as free" /> : null}
      </div>
      <ChartCard title="LLM completion history" subtitle="global counters cannot be attributed to individual projects">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={[...byTime.values()].sort((a, b) => Number(a.t) - Number(b.t))}><Axes /><Tooltip {...TOOLTIP_PROPS} />{families.map((family, index) => <Line key={family} type="monotone" dataKey={family} name={family} stroke={index % 2 === 0 ? "var(--color-turq)" : "var(--color-peri)"} strokeWidth={2} dot={false} isAnimationActive={false} />)}</LineChart></ResponsiveContainer>
      </ChartCard>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{data.rows.map((row) => <Card key={row.functionId} className="p-4"><div className="font-display text-sm font-semibold text-fg1">{row.functionId}</div><div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4"><StatTile label="Calls" value={fmtNum(row.calls)} sub={delta(row.calls, row.previousCalls)} /><StatTile label="Success" value={percent(row.successRate)} /><StatTile label="Failures" value={fmtNum(row.failures)} /><StatTile label="Avg latency" value={row.calls > 0 ? fmtMs(row.avgLatencyMs) : "—"} /></div></Card>)}</div>
      <Card className="overflow-x-auto">
        <div className="border-b border-line px-4 py-3"><div className="font-display text-[13px] font-semibold text-fg1">Provider usage by model and family</div><div className="mt-0.5 text-[10px] text-fg3">Exact categories are aggregated; local, priced, and unknown-fee calls remain distinct in history.</div></div>
        <table className="w-full min-w-[1130px] text-left text-[11px]"><thead><tr className="border-b border-line text-[9px] uppercase tracking-[0.08em] text-fg3"><th className="px-4 py-3">Provider</th><th>Model</th><th>Family</th><th>Calls</th><th>Fee class</th><th>Input</th><th>Cached</th><th>Cache write</th><th>Output</th><th>Output rate</th><th>Reasoning</th><th>Total</th>{showCost ? <th>Estimated cost</th> : null}</tr></thead><tbody>{data.usageRows.map((row) => <tr key={`${row.provider}:${row.model}:${row.family}`} className="border-b border-line/60 font-mono text-fg2 last:border-0"><td className="px-4 py-3">{row.provider}</td><td>{row.model}</td><td>{row.family}</td><td>{fmtNum(row.calls)}</td><td>{row.localCalls === row.calls ? "Local" : row.pricedCalls === row.calls ? "Priced" : row.unpricedCalls === row.calls ? "Unpriced" : "Mixed"}</td><td>{fmtNum(row.promptTokens)}</td><td>{fmtNum(row.cachedPromptTokens)}</td><td>{fmtNum(row.cacheWriteTokens)}</td><td>{fmtNum(row.completionTokens)}</td><td title={`${fmtNum(row.throughputMeasuredCalls)} measured calls`}>{fmtTokensPerSecond(row.outputTokensPerSecond)}</td><td>{fmtNum(row.reasoningTokens)}</td><td>{fmtNum(row.totalTokens)}</td>{showCost ? <td>{fmtUsdNanos(row.estimatedCostNanos)}{row.unpricedCalls ? <span className="ml-1 text-warn">+ {fmtNum(row.unpricedCalls)} unpriced</span> : null}</td> : null}</tr>)}</tbody></table>
      </Card>
    </div>
  );
}

function SystemReport({ data }: { data: ReportSystemResponse }) {
  const span = data.range.to - data.range.from;
  const series = data.series.map((point) => ({ ...point, label: chartLabel(point.t, span), availabilityPct: point.sampledAvailability === null ? null : point.sampledAvailability * 100 }));
  const latest = data.series.at(-1);
  return (
    <div className="flex flex-col gap-4" data-testid="report-system">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><StatTile label="Console starts" value={fmtNum(data.restartCount)} sub={data.previousRestartCount === null ? "comparison unavailable" : `${fmtNum(data.previousRestartCount)} prior period`} /><StatTile label="Heap average" value={latest?.heapAvgMb == null ? "—" : `${Math.round(latest.heapAvgMb)} MB`} sub={latest?.heapMaxMb == null ? undefined : `max ${Math.round(latest.heapMaxMb)} MB`} /><StatTile label="RSS average" value={latest?.rssAvgMb == null ? "—" : `${Math.round(latest.rssAvgMb)} MB`} sub={latest?.rssMaxMb == null ? undefined : `max ${Math.round(latest.rssMaxMb)} MB`} /><StatTile label="Last uptime" value={fmtUptime(latest?.uptimeSec ?? null)} sub="AgentMemory process" /></div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Stored totals" subtitle="last sampled gauge in each chart interval"><ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="memoriesTotal" name="memories" stroke="var(--color-turq)" strokeWidth={2} dot={false} isAnimationActive={false} /><Line type="monotone" dataKey="sessionsTotal" name="sessions" stroke="var(--color-peri)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></ChartCard>
        <ChartCard title="Process memory" subtitle="average heap and RSS in MB"><ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="heapAvgMb" name="heap MB" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} /><Line type="monotone" dataKey="rssAvgMb" name="RSS MB" stroke="var(--color-peri)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></ChartCard>
        <ChartCard title="Event-loop lag" subtitle="average and maximum milliseconds"><ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="lagAvgMs" name="average ms" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} /><Line type="monotone" dataKey="lagMaxMs" name="max ms" stroke="var(--color-bad)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></ChartCard>
        <ChartCard title="Sampled upstream availability" subtitle="successful health polls; console downtime is not sampled"><ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Axes /><Tooltip {...TOOLTIP_PROPS} /><Line type="monotone" dataKey="availabilityPct" name="availability %" stroke="var(--color-ok)" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></ChartCard>
      </div>
    </div>
  );
}

export default function Reports() {
  const { sectionVisible } = usePagePreferences("reports");
  const [section, setSection] = useState<ReportViewSection>("overview");
  const [preset, setPreset] = useState<RangePreset>(initialRange);
  const [compare, setCompare] = useState(initialCompare);
  const [customFrom, setCustomFrom] = useState(() => localInput(Date.now() - DAY_MS));
  const [customTo, setCustomTo] = useState(() => localInput(Date.now()));
  const [project, setProject] = useState("");
  const [agent, setAgent] = useState("");
  const [functionId, setFunctionId] = useState("");
  const [meta, setMeta] = useState<ReportMeta | null>(null);
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);

  useEffect(() => { try { window.localStorage.setItem(RANGE_KEY, preset); } catch { /* optional */ } }, [preset]);
  useEffect(() => { try { window.localStorage.setItem(COMPARE_KEY, String(compare)); } catch { /* optional */ } }, [compare]);

  const selectedRange = useCallback(() => {
    if (preset !== "custom") { const to = Date.now(); return { from: to - PRESET_MS[preset], to }; }
    return { from: new Date(customFrom).getTime(), to: new Date(customTo).getTime() };
  }, [preset, customFrom, customTo]);

  const refresh = useCallback(async () => {
    const range = selectedRange();
    if (!Number.isFinite(range.from) || !Number.isFinite(range.to) || range.to <= range.from) { setError("Choose a valid custom time range."); setLoading(false); return; }
    setLoading(true);
    const params = new URLSearchParams({ from: String(range.from), to: String(range.to), compare: String(compare) });
    if (section === "projects" || section === "memory") { if (project) params.set("project", project); if (agent) params.set("agent", agent); }
    if (section === "llm" && functionId) params.set("functionId", functionId);
    const reportRequest = section === "overview"
      ? Promise.all([
          apiGet<ReportSummaryResponse>(`/api/reports/summary?${params}`),
          apiGet<ReportProjectsResponse>(`/api/reports/projects?${params}`),
          apiGet<ReportMemoryResponse>(`/api/reports/memory?${params}`),
          apiGet<ReportLlmResponse>(`/api/reports/llm?${params}`),
          apiGet<ReportSystemResponse>(`/api/reports/system?${params}`),
        ]).then(([summary, projects, memory, llm, system]): ReportOverviewData | null =>
          summary && projects && memory && llm && system ? { summary, projects, memory, llm, system } : null,
        )
      : apiGet<ReportData>(`/api/reports/${section}?${params}`);
    const [next, nextMeta] = await Promise.all([reportRequest, apiGet<ReportMeta>("/api/reports/meta")]);
    if (nextMeta) setMeta(nextMeta);
    if (next) { setData(next); setError(null); setRefreshedAt(Date.now()); } else setError("Historical reporting is unavailable. Live console activity is unaffected.");
    setLoading(false);
  }, [agent, compare, functionId, project, section, selectedRange]);

  useEffect(() => {
    setData(null); setLoading(true); void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, REFRESH_MS);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [section, preset, compare, customFrom, customTo, project, agent, functionId]);

  const exportUrl = useMemo(() => {
    const range = selectedRange();
    const params = new URLSearchParams({ from: String(range.from), to: String(range.to), compare: String(compare) });
    if (section === "projects" || section === "memory") { if (project) params.set("project", project); if (agent) params.set("agent", agent); }
    if (section === "llm" && functionId) params.set("functionId", functionId);
    const exportSection = section === "overview" ? "summary" : section;
    return `/api/reports/${exportSection}.csv?${params}`;
  }, [agent, compare, functionId, project, section, selectedRange]);

  const tabs: Array<{ id: ReportViewSection; label: string }> = [{ id: "overview", label: "Overview" }, { id: "summary", label: "Summary" }, { id: "projects", label: "Projects" }, { id: "memory", label: "Memory" }, { id: "llm", label: "LLM" }, { id: "system", label: "System" }];
  return (
    <div className="flex min-h-full flex-col gap-5" data-testid="reports-page">
      <PageHeader title="Reports" helpId="sampled-availability" subtitle={meta?.earliestTs ? `history retained since ${new Date(meta.earliestTs).toLocaleString()}` : "privacy-safe operational history begins after deployment"} right={<div className="flex items-center gap-2">{meta ? <Pill tone={meta.status.ok ? "ok" : "bad"}>{meta.status.ok ? "HISTORY LIVE" : "HISTORY DEGRADED"}</Pill> : null}<a href={exportUrl} className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3 py-2 font-display text-xs font-semibold text-fg1 no-underline hover:border-turq/50"><Download size={13} /> Export CSV</a></div>} />

      {sectionVisible("filters") ? <Card className="flex flex-wrap items-center gap-3 px-4 py-3">
        <SelectBox label="Range" value={preset} onChange={(value) => setPreset(value as RangePreset)} options={[{ value: "1h", label: "Last hour" }, { value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" }, { value: "30d", label: "Last 30 days" }, { value: "90d", label: "Last 90 days" }, { value: "1y", label: "Last year" }, { value: "custom", label: "Custom" }]} />
        {preset === "custom" ? <><label className="text-[11px] text-fg3">From <input type="datetime-local" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} className="ml-2 rounded-lg border border-linestrong bg-side px-2.5 py-2 font-mono text-xs text-fg1" /></label><label className="text-[11px] text-fg3">To <input type="datetime-local" value={customTo} onChange={(event) => setCustomTo(event.target.value)} className="ml-2 rounded-lg border border-linestrong bg-side px-2.5 py-2 font-mono text-xs text-fg1" /></label></> : null}
        <label className="inline-flex cursor-pointer items-center gap-2 font-display text-xs text-fg2"><input type="checkbox" checked={compare} onChange={(event) => setCompare(event.target.checked)} className="accent-[#53E2DD]" /> Compare previous period</label>
        <button type="button" onClick={() => void refresh()} className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-side px-3 py-2 font-display text-xs font-semibold text-fg1 hover:border-turq/50"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh</button>
        <span className="ml-auto text-[10px] text-fg3">{refreshedAt ? `updated ${timeAgo(refreshedAt)}` : "waiting for history"}</span>
      </Card> : null}

      <div className="flex gap-1 border-b border-line">{tabs.map((tab) => <button key={tab.id} type="button" onClick={() => { setData(null); setSection(tab.id); }} className="border-b-2 px-4 py-2.5 font-display text-xs font-semibold" style={section === tab.id ? { borderColor: "var(--color-turq)", color: "var(--color-fg1)" } : { borderColor: "transparent", color: "var(--color-fg3)" }}>{tab.label}</button>)}</div>

      {error ? <Card className="flex items-start gap-3 border-bad/40 p-4"><ShieldAlert size={18} className="mt-0.5 text-bad" /><div><div className="font-display text-sm font-semibold text-fg1">History unavailable</div><div className="mt-1 text-xs text-fg3">{error}</div></div></Card> : null}
      {loading && data === null ? <Card className="flex min-h-[320px] items-center justify-center"><div className="inline-flex items-center gap-2 text-sm text-fg3"><RefreshCw size={16} className="animate-spin" /> Building historical report…</div></Card> : data === null ? <Card><EmptyState icon={<BarChart3 size={24} />} title="No historical data yet" body="Aggregate minute buckets will appear here as Agent007Memory records activity." /></Card> : section === "overview" ? <OverviewReport data={data as ReportOverviewData} /> : section === "summary" ? <SummaryReport data={data as ReportSummaryResponse} /> : section === "projects" ? <ProjectsReport data={data as ReportProjectsResponse} meta={meta} project={project} agent={agent} setProject={setProject} setAgent={setAgent} /> : section === "memory" ? <MemoryReport data={data as ReportMemoryResponse} meta={meta} project={project} agent={agent} setProject={setProject} setAgent={setAgent} /> : section === "llm" ? <LlmReport data={data as ReportLlmResponse} meta={meta} functionId={functionId} setFunctionId={setFunctionId} /> : <SystemReport data={data as ReportSystemResponse} />}

      {sectionVisible("boundary") ? <Card className="px-4 py-3 text-[11px] leading-relaxed text-fg3">Only aggregate counts and gauges are retained. Historical latency is estimated from fixed histogram buckets; sampled availability excludes time when this console itself was not running. No paths, request bodies, prompts, responses, memory content, session IDs, or individual activity records enter the reporting database.</Card> : null}
    </div>
  );
}
