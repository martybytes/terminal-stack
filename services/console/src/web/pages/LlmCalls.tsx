import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { CSSProperties, ReactNode } from "react";
import {
  Activity,
  BrainCircuit,
  Clock3,
  Cpu,
  ListChecks,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Workflow,
  DollarSign,
} from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip } from "recharts";
import type {
  BillingStatusSnapshot,
  LlmCompletionEvent,
  LlmCallTelemetry,
  LlmFeatureFlag,
  LlmFunctionSummary,
  LlmSnapshot,
} from "../../shared/types";
import { callTokensPerSecond, llmFamilyForFunction, llmOutputThroughput } from "../../shared/llmThroughput";
import { MetricsTiles } from "../components/MetricsTiles";
import { Card, EmptyState, Eyebrow, PageHeader, Paginator, Pill, StatTile } from "../components/ui";
import { HelpTopic } from "../components/ContextHelp";
import { apiGet, apiPost } from "../lib/api";
import { fmtMs, fmtNum, fmtTokensPerSecond, fmtUsdNanos, timeAgo } from "../lib/format";
import { deriveLlmQueueMetrics } from "../lib/llmQueue";
import { usePagePreferences } from "../lib/preferences";
import { useLive } from "../lib/ws";

const SNAPSHOT_REFRESH_MS = 3_000;
const PULSE_VISIBLE_MS = 9_000;
const PULSE_DECAY_MS = 2_600;

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);
  return now;
}

function percent(successes: number, total: number): string {
  if (total <= 0) return "—";
  return `${((successes / total) * 100).toFixed(total >= 100 ? 1 : 0)}%`;
}

function seconds(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1_000 ? `${Math.round(ms / 1_000)} s` : `${Math.round(ms)} ms`;
}

function waitLabel(until: number, now: number): string {
  const minutes = Math.max(1, Math.ceil((until - now) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function utcDate(ts: number): string {
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", year: "numeric", month: "short", day: "numeric" }).format(ts);
}

export function BillingRefreshButton({
  billing,
  compact = false,
  onUpdated,
}: {
  billing: BillingStatusSnapshot;
  compact?: boolean;
  onUpdated?: (billing: BillingStatusSnapshot) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const now = useNow();
  const coolingDown = (billing.nextBillingSyncAllowedAt ?? 0) > now;
  const configured = billing.billingScope !== null && billing.billingStatus !== "setup_required";
  const disabled = busy || billing.billingStatus === "syncing" || coolingDown || !configured;
  const title = !configured
    ? "Configure project-scoped OpenAI billing first"
    : coolingDown
      ? `Refresh available in ${waitLabel(billing.nextBillingSyncAllowedAt!, now)}`
      : "Refresh authoritative OpenAI project costs";
  const refresh = async () => {
    setBusy(true);
    setMessage(null);
    const result = await apiPost<{ success: boolean; billing: BillingStatusSnapshot }>("/api/operations/billing/sync");
    setBusy(false);
    if (result.data?.billing) onUpdated?.(result.data.billing);
    if (result.error) setMessage(result.error);
  };
  return (
    <span className="inline-flex min-w-0 flex-col items-end gap-1">
      <button
        type="button"
        disabled={disabled}
        title={title}
        aria-label={title}
        data-testid="billing-refresh"
        onClick={() => void refresh()}
        className={`${compact ? "h-6 w-6 justify-center p-0" : "px-2.5 py-1.5"} inline-flex items-center gap-1.5 rounded-md border border-line bg-side/70 font-display text-[10px] font-semibold text-fg2 transition hover:border-turq/45 hover:text-fg1 disabled:cursor-not-allowed disabled:opacity-35`}
      >
        <RefreshCw size={compact ? 11 : 12} className={busy || billing.billingStatus === "syncing" ? "animate-spin" : ""} />
        {compact ? null : busy || billing.billingStatus === "syncing" ? "Refreshing…" : coolingDown ? `Available in ${waitLabel(billing.nextBillingSyncAllowedAt!, now)}` : "Refresh billed cost"}
      </button>
      {message && !compact ? <span className="max-w-[280px] text-right text-[9px] text-bad">{message}</span> : null}
    </span>
  );
}

function Setting({ label, value, mono = false, compact = false }: { label: string; value: ReactNode; mono?: boolean; compact?: boolean }) {
  return (
    <div className={`min-w-0 rounded-lg border border-line bg-side/45 ${compact ? "px-2 py-1" : "px-3 py-2.5"}`}>
      <Eyebrow>{label}</Eyebrow>
      <div
        className={`${compact ? "mt-0.5 text-[10px]" : "mt-1 text-[12px]"} truncate text-fg1 ${mono ? "font-mono" : "font-display font-semibold"}`}
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </div>
    </div>
  );
}

function pulseFor(
  events: LlmCompletionEvent[],
  functionId: string,
  now: number,
): { success: number; failure: number } {
  let success = 0;
  let failure = 0;
  for (const event of events) {
    if (event.functionId !== functionId) continue;
    const age = now - event.ts;
    if (age < 0 || age > PULSE_VISIBLE_MS) continue;
    const decay = Math.exp(-age / PULSE_DECAY_MS);
    success += event.successes * decay;
    failure += event.failures * decay;
  }
  return {
    success: 1 - Math.exp(-success / 1.6),
    failure: 1 - Math.exp(-failure / 1.2),
  };
}

function pulseStyle(pulse: { success: number; failure: number }): CSSProperties | undefined {
  if (pulse.success < 0.015 && pulse.failure < 0.015) return undefined;
  const success = `rgba(83,226,221,${(0.4 + pulse.success * 0.6).toFixed(3)})`;
  const failure = `rgba(238,128,100,${(0.4 + pulse.failure * 0.6).toFixed(3)})`;
  const both = pulse.success >= 0.015 && pulse.failure >= 0.015;
  const border = both
    ? `linear-gradient(135deg,${success} 0%,${success} 45%,${failure} 55%,${failure} 100%)`
    : `linear-gradient(135deg,${pulse.failure >= 0.015 ? failure : success},${pulse.failure >= 0.015 ? failure : success})`;
  const shadows: string[] = [];
  if (pulse.success >= 0.015) {
    shadows.push(
      `-3px -2px ${Math.round(12 + pulse.success * 24)}px rgba(83,226,221,${(
        pulse.success * 0.72
      ).toFixed(3)})`,
    );
  }
  if (pulse.failure >= 0.015) {
    shadows.push(
      `3px 2px ${Math.round(12 + pulse.failure * 24)}px rgba(238,128,100,${(
        pulse.failure * 0.78
      ).toFixed(3)})`,
    );
  }
  return {
    background: `linear-gradient(var(--color-surface),var(--color-surface)) padding-box,${border} border-box`,
    borderColor: "transparent",
    boxShadow: shadows.join(","),
  };
}

export function CallCard({
  summary,
  events,
  now,
  compact = false,
  costNanos = 0,
  showCost = true,
  tokensPerSecond = null,
  throughputSamples = 0,
}: {
  summary: LlmFunctionSummary;
  events: LlmCompletionEvent[];
  now: number;
  compact?: boolean;
  costNanos?: number;
  showCost?: boolean;
  tokensPerSecond?: number | null;
  throughputSamples?: number;
}) {
  const pulse = pulseFor(events, summary.functionId, now);
  const active = pulse.success > 0.04 || pulse.failure > 0.04;
  const latestEvent = events.find((event) => event.functionId === summary.functionId);
  const chartData = summary.buckets.map((bucket) => ({
    label: new Date(bucket.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    completed: bucket.successes,
    failed: bucket.failures,
  }));

  if (compact) {
    return (
      <Card
        className="flex min-h-[145px] flex-col gap-1.5 p-2.5 transition-[border-color,box-shadow,background-color] duration-300"
        style={pulseStyle(pulse)}
        data-testid="llm-call-card"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-display text-[13px] font-semibold text-fg1">{summary.label}</div>
            <div className="mt-0.5 font-mono text-[9px] text-peri">{summary.functionId}</div>
          </div>
          <span className="inline-flex flex-none items-center gap-1.5 text-[10px] text-fg3">
            <span
              className={`h-1.5 w-1.5 rounded-full ${active ? "animate-pulse" : ""}`}
              style={{
                background:
                  pulse.failure > pulse.success
                    ? "var(--color-bad-bright)"
                    : active
                      ? "var(--color-turq)"
                      : summary.recentCalls > 0
                        ? "var(--color-s1)"
                        : "var(--color-na)",
              }}
            />
            {active ? "completing" : summary.recentCalls > 0 ? "recent" : "idle"}
          </span>
        </div>

        <div className="grid grid-cols-4 gap-1.5">
          <Setting label="15 min" value={fmtNum(summary.recentCalls)} mono compact />
          <Setting
            label="Latency"
            value={summary.recentCalls > 0 ? fmtMs(summary.recentAvgLatencyMs) : "—"}
            mono
            compact
          />
          <Setting label="Failed" value={fmtNum(summary.recentFailures)} mono compact />
          <Setting
            label="Last seen"
            value={summary.lastCompletedAt === null ? "not since start" : timeAgo(summary.lastCompletedAt)}
            mono
            compact
          />
        </div>

        <div className="h-[24px] min-h-[24px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} barCategoryGap="18%">
              <Tooltip
                cursor={{ fill: "rgb(var(--rgb-fg) / 0.05)" }}
                contentStyle={{
                  background: "var(--color-tooltip)",
                  border: "1px solid rgb(var(--rgb-fg) / 0.16)",
                  borderRadius: 8,
                  color: "var(--color-fg2)",
                  fontSize: 11,
                }}
              />
              <Bar dataKey="completed" stackId="calls" fill="var(--color-s1)" isAnimationActive={false} />
              <Bar dataKey="failed" stackId="calls" fill="var(--color-bad)" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className={`mt-auto grid ${showCost ? "grid-cols-5" : "grid-cols-4"} gap-2 border-t border-line pt-1.5`}>
          <div><Eyebrow>All calls</Eyebrow><div className="mt-0.5 font-mono text-[10px] text-fg1">{fmtNum(summary.totalCalls)}</div></div>
          <div><Eyebrow>Success</Eyebrow><div className="mt-0.5 font-mono text-[10px] text-fg1">{percent(summary.successCount, summary.totalCalls)}</div></div>
          <div><Eyebrow>Avg latency</Eyebrow><div className="mt-0.5 font-mono text-[10px] text-fg1">{fmtMs(summary.avgLatencyMs)}</div></div>
          <div><Eyebrow>Output rate</Eyebrow><div className="mt-0.5 font-mono text-[10px] text-fg1" title={`${fmtNum(throughputSamples)} exact successful calls`}>{fmtTokensPerSecond(tokensPerSecond)}</div></div>
          {showCost ? <div><Eyebrow>Est. cost</Eyebrow><div className="mt-0.5 font-mono text-[10px] text-fg1">{fmtUsdNanos(costNanos)}</div></div> : null}
        </div>
      </Card>
    );
  }

  return (
    <Card
      className="flex min-h-[390px] flex-col gap-3.5 p-4 transition-[border-color,box-shadow,background-color] duration-300"
      style={pulseStyle(pulse)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-display text-[15px] font-semibold text-fg1">{summary.label}</div>
          <div className="mt-1 font-mono text-[10px] text-peri">{summary.functionId}</div>
        </div>
        <span className="inline-flex flex-none items-center gap-1.5 text-[11px] text-fg3">
          <span
            className={`h-2 w-2 rounded-full ${active ? "animate-pulse" : ""}`}
            style={{
              background:
                pulse.failure > pulse.success
                  ? "var(--color-bad-bright)"
                  : active
                    ? "var(--color-turq)"
                    : summary.recentCalls > 0
                      ? "var(--color-s1)"
                      : "var(--color-na)",
            }}
          />
          {active ? "completing" : summary.recentCalls > 0 ? "recent" : "idle"}
        </span>
      </div>

      <p className="min-h-[42px] text-[12px] leading-[1.5] text-fg2">{summary.description}</p>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Setting label="15 min" value={fmtNum(summary.recentCalls)} mono />
        <Setting
          label="Recent latency"
          value={summary.recentCalls > 0 ? fmtMs(summary.recentAvgLatencyMs) : "—"}
          mono
        />
        <Setting label="Failed" value={fmtNum(summary.recentFailures)} mono />
        <Setting
          label="Last seen"
          value={summary.lastCompletedAt === null ? "not since start" : timeAgo(summary.lastCompletedAt)}
          mono
        />
      </div>

      <div className="h-[104px] min-h-[104px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} barCategoryGap="18%">
            <Tooltip
              cursor={{ fill: "rgb(var(--rgb-fg) / 0.05)" }}
              contentStyle={{
                background: "var(--color-tooltip)",
                border: "1px solid rgb(var(--rgb-fg) / 0.16)",
                borderRadius: 8,
                color: "var(--color-fg2)",
                fontSize: 11,
              }}
            />
            <Bar dataKey="completed" stackId="calls" fill="var(--color-s1)" isAnimationActive={false} />
            <Bar dataKey="failed" stackId="calls" fill="var(--color-bad)" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className={`mt-auto grid ${showCost ? "grid-cols-5" : "grid-cols-4"} gap-2 border-t border-line pt-3`}>
        <div>
          <Eyebrow>All calls</Eyebrow>
          <div className="mt-1 font-mono text-xs text-fg1">{fmtNum(summary.totalCalls)}</div>
        </div>
        <div>
          <Eyebrow>Success</Eyebrow>
          <div className="mt-1 font-mono text-xs text-fg1">
            {percent(summary.successCount, summary.totalCalls)}
          </div>
        </div>
        <div>
          <Eyebrow>Avg latency</Eyebrow>
          <div className="mt-1 font-mono text-xs text-fg1">{fmtMs(summary.avgLatencyMs)}</div>
        </div>
        <div>
          <Eyebrow>Output rate</Eyebrow>
          <div className="mt-1 font-mono text-xs text-fg1" title={`${fmtNum(throughputSamples)} exact successful calls`}>{fmtTokensPerSecond(tokensPerSecond)}</div>
        </div>
        {showCost ? <div>
          <Eyebrow>Est. cost</Eyebrow>
          <div className="mt-1 font-mono text-xs text-fg1">{fmtUsdNanos(costNanos)}</div>
        </div> : null}
      </div>

      {latestEvent?.failures ? (
        <div className="text-[11px] text-bad">
          Latest detected batch included {fmtNum(latestEvent.failures)} failed completion
          {latestEvent.failures === 1 ? "" : "s"}.
        </div>
      ) : null}
    </Card>
  );
}

function FeatureCard({ flag }: { flag: LlmFeatureFlag }) {
  const icon: ReactNode =
    flag.key === "GRAPH_EXTRACTION_ENABLED" ? (
      <Network size={18} />
    ) : flag.key === "CONSOLIDATION_ENABLED" ? (
      <Workflow size={18} />
    ) : flag.key === "AGENTMEMORY_AUTO_COMPRESS" ? (
      <Sparkles size={18} />
    ) : (
      <Activity size={18} />
    );
  const boundary = flag.needsLlm
    ? "Safe per-call rows are tracked above without prompt or response content."
    : "This setting changes hook behavior; it does not create an LLM call by itself.";
  return (
    <Card className="flex min-h-[175px] flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div
          className="flex h-9 w-9 items-center justify-center rounded-lg"
          style={{ background: "rgba(138,128,240,0.14)", color: "var(--color-peri-bright)" }}
        >
          {icon}
        </div>
        <Pill tone={flag.enabled ? "ok" : "na"}>{flag.enabled ? "ENABLED" : "OFF"}</Pill>
      </div>
      <div>
        <div className="font-display text-[13px] font-semibold text-fg1">{flag.label}</div>
        <div className="mt-1 text-[11px] leading-[1.5] text-fg2">{flag.description}</div>
      </div>
      <div className="mt-auto border-t border-line pt-2 text-[10px] leading-[1.45] text-fg3">
        {boundary}
      </div>
    </Card>
  );
}

export function ProviderOverview({ snapshot }: { snapshot: LlmSnapshot }) {
  const exactRecent = snapshot.calls.filter(
    (call) =>
      call.status === "completed" &&
      call.completedAt !== null &&
      call.completedAt >= Date.now() - 15 * 60_000,
  );
  const recentCalls = snapshot.calls.length > 0
    ? exactRecent.length
    : snapshot.functions.reduce((total, item) => total + item.recentCalls, 0);
  const recentFailures = snapshot.calls.length > 0
    ? exactRecent.filter((call) => call.outcome !== "success").length
    : snapshot.functions.reduce((total, item) => total + item.recentFailures, 0);
  const circuit = snapshot.circuitBreaker;
  const circuitTone = circuit.state === "closed" ? "ok" : circuit.state === "open" ? "bad" : "warn";
  return (
    <Card className="relative overflow-hidden p-5">
      <div
        aria-hidden="true"
        className="absolute -right-16 -top-24 h-72 w-72 rounded-full"
        style={{
          background: "radial-gradient(circle,rgba(83,226,221,0.12) 0%,rgba(138,128,240,0.05) 45%,transparent 72%)",
        }}
      />
      <div className="relative flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-11 w-11 items-center justify-center rounded-xl border"
              style={{
                background: "rgba(83,226,221,0.10)",
                borderColor: "rgba(83,226,221,0.28)",
                color: "var(--color-turq)",
              }}
            >
              <BrainCircuit size={23} />
            </div>
            <div>
              <div className="font-display text-[16px] font-semibold text-fg1">
                {snapshot.config.endpointLabel ?? "LLM endpoint"}
              </div>
              <div className="mt-0.5 text-[11px] text-fg3">
                {snapshot.config.provider} · AgentMemory {snapshot.version ?? "unknown version"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2"><Pill tone={snapshot.config.costApplicability === "local" ? "ok" : snapshot.config.costApplicability === "paid" ? "warn" : "na"}>{snapshot.config.costApplicability === "local" ? "LOCAL · NO API FEES" : snapshot.config.costApplicability === "paid" ? "PAID API" : "FEE STATUS UNKNOWN"}</Pill><Pill tone={circuitTone}>
            <ShieldCheck size={11} /> CIRCUIT {circuit.state.toUpperCase()}
          </Pill></div>
        </div>

        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4 2xl:grid-cols-8">
          <Setting label="Model" value={snapshot.config.model ?? "not forwarded"} mono />
          <Setting label="Endpoint" value={snapshot.config.endpoint ?? "not forwarded"} mono />
          <Setting label="Timeout" value={seconds(snapshot.config.timeoutMs)} mono />
          <Setting label="Max output" value={fmtNum(snapshot.config.maxTokens)} mono />
          <Setting label="Summary workers" value={fmtNum(snapshot.config.summarizeConcurrency)} mono />
          <Setting label="Graph batch" value={fmtNum(snapshot.config.graphBatchSize)} mono />
          <Setting
            label="Embeddings"
            value={snapshot.config.embeddingProvider ?? "not reported"}
            mono
          />
          <Setting label="Completed 15m" value={`${fmtNum(recentCalls)} · ${fmtNum(recentFailures)} failed`} mono />
        </div>

        {snapshot.config.keyHints.length ? <div className="grid grid-cols-1 gap-2 md:grid-cols-2" data-testid="openai-key-hints">
          {snapshot.config.keyHints.map((hint) => (
            <Setting
              key={hint.purpose}
              label={hint.label}
              value={hint.configured && hint.masked ? hint.masked : "not visible to console"}
              mono
            />
          ))}
        </div> : null}

        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[11px] text-fg3">
          <Cpu size={13} className="text-turq" />
          <span>AgentMemory</span>
          <span>→</span>
          <span>compression · summarization · graph · consolidation</span>
          <span>→</span>
          <span className="text-fg2">{snapshot.config.endpointLabel ?? "configured provider"}</span>
          <span>→</span>
          <span className="font-mono text-fg2">{snapshot.config.model ?? "model not forwarded"}</span>
        </div>
      </div>
    </Card>
  );
}

export function LlmSummaryTiles({
  snapshot,
  compact = false,
  onBillingUpdated,
}: {
  snapshot: LlmSnapshot;
  compact?: boolean;
  onBillingUpdated?: (billing: BillingStatusSnapshot) => void;
}) {
  const metrics = deriveLlmQueueMetrics(snapshot);
  const queue = snapshot.queue;
  const showCost = snapshot.config.costApplicability !== "local";
  const throughput = llmOutputThroughput(snapshot.calls, { since: Date.now() - snapshot.windowMs });
  const { itemVisible } = usePagePreferences(compact ? "overview" : "llm");
  const sectionId = compact ? "llmSummary" : "summary";

  return (
    <div
      className={`grid grid-cols-2 ${compact ? `gap-2 ${showCost ? "2xl:grid-cols-10" : "2xl:grid-cols-8"}` : "gap-3.5 2xl:grid-cols-9"} md:grid-cols-4`}
      data-testid="llm-summary-tiles"
    >
      {itemVisible(sectionId, "completed") ? <StatTile
        label="Completed · 15m"
        value={fmtNum(metrics.completedCalls)}
        sub="provider calls"
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "success") ? <StatTile
        label="Success · 15m"
        value={percent(metrics.completedCalls - metrics.failedCalls, metrics.completedCalls)}
        sub={metrics.exactCalls ? "exact completions" : "cumulative fallback"}
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "providerLatency") ? <StatTile
        label="Provider · 15m"
        value={metrics.averageProviderLatencyMs === null ? "—" : fmtMs(metrics.averageProviderLatencyMs)}
        sub="average LLM time"
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "outputRate") ? <StatTile
        label="Output rate · 15m"
        value={fmtTokensPerSecond(throughput.tokensPerSecond)}
        sub={throughput.measuredCalls ? `${fmtNum(throughput.measuredCalls)} exact successful calls` : "awaiting exact token usage"}
        dim={throughput.tokensPerSecond === null}
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "queueDepth") ? <StatTile
        label="Queue depth"
        value={queue ? fmtNum(queue.depth) : "—"}
        sub={queue ? `${fmtNum(queue.activeJobs)} active · ${fmtNum(queue.consumers)} workers` : "not reported"}
        dim={!queue}
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "queueWait") ? <StatTile
        label="Queue wait · 15m"
        value={metrics.averageQueueWaitMs === null ? "—" : fmtMs(metrics.averageQueueWaitMs)}
        sub="enqueue → worker"
        compact={compact}
      /> : null}
      {compact && showCost ? (
        <>
          {itemVisible(sectionId, "apiCost") ? <StatTile label="API cost · today" value={fmtUsdNanos(snapshot.cost.estimatedTodayNanos)} sub={snapshot.cost.unpricedCallsToday > 0 ? `${fmtNum(snapshot.cost.unpricedCallsToday)} unpriced` : "estimated from tokens"} compact /> : null}
          {itemVisible(sectionId, "billedMtd") ? <StatTile
            label="Billed · MTD"
            value={fmtUsdNanos(snapshot.cost.billedMonthToDateNanos)}
            sub={`${snapshot.cost.billingScope?.name ?? "OpenAI project"} · ${snapshot.cost.lastBillingSuccessAt ? `updated ${timeAgo(snapshot.cost.lastBillingSuccessAt)}` : snapshot.cost.billingStatus.replace("_", " ")}`}
            action={<BillingRefreshButton billing={snapshot.cost} compact onUpdated={onBillingUpdated} />}
            dim={snapshot.cost.billedMonthToDateNanos === null}
            compact
          /> : null}
        </>
      ) : !compact ? (
        itemVisible(sectionId, "providerGate") ? <StatTile label="Provider gate · 15m" value={metrics.averageProviderGateWaitMs === null ? "—" : fmtMs(metrics.averageProviderGateWaitMs)} sub="worker → LLM slot" /> : null
      ) : null}
      {itemVisible(sectionId, "jobRuntime") ? <StatTile
        label="Job runtime · 15m"
        value={metrics.averageJobRuntimeMs === null ? "—" : fmtMs(metrics.averageJobRuntimeMs)}
        sub="worker → complete"
        compact={compact}
      /> : null}
      {itemVisible(sectionId, "deadLetter") ? <StatTile
        label="Dead letter"
        value={
          queue ? (
            <span className={queue.dlqDepth > 0 ? "text-bad" : "text-fg1"}>
              {fmtNum(queue.dlqDepth)}
            </span>
          ) : (
            "—"
          )
        }
        sub="retry-exhausted jobs"
        dim={!queue}
        compact={compact}
      /> : null}
    </div>
  );
}

function CostOverview({ snapshot, onBillingUpdated }: { snapshot: LlmSnapshot; onBillingUpdated?: (billing: BillingStatusSnapshot) => void }) {
  const billed = snapshot.cost.billedMonthToDateNanos;
  const coverage = snapshot.cost.pricedCallsToday + snapshot.cost.unpricedCallsToday;
  const coveragePercent = coverage > 0 ? Math.round((snapshot.cost.pricedCallsToday / coverage) * 100) : 100;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3"><div className="rounded-lg bg-turq/10 p-2 text-turq"><DollarSign size={18} /></div><div><div className="font-display text-[13px] font-semibold text-fg1">Paid provider cost</div><div className="mt-1 text-[11px] text-fg3">Estimates and provider billing remain separate so timing and coverage differences stay visible.</div></div></div>
        <div className="flex items-start gap-2">
          <BillingRefreshButton billing={snapshot.cost} onUpdated={onBillingUpdated} />
          <Pill tone={snapshot.cost.billingStatus === "ready" ? "ok" : snapshot.cost.billingStatus === "error" ? "bad" : "warn"}>{snapshot.cost.billingStatus.replace("_", " ").toUpperCase()}</Pill>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Setting label="Estimated today" value={fmtUsdNanos(snapshot.cost.estimatedTodayNanos)} mono />
        <Setting label="Estimated · 15 min" value={fmtUsdNanos(snapshot.cost.estimatedWindowNanos)} mono />
        <Setting label="Billed · month to date" value={fmtUsdNanos(billed)} mono />
        <Setting label="Pricing coverage" value={`${coveragePercent}% · ${fmtNum(snapshot.cost.unpricedCallsToday)} unpriced`} mono />
      </div>
      <div className="mt-3 border-t border-line pt-3 text-[10px] leading-[1.5] text-fg3">
        {snapshot.cost.billingDetail} Catalog effective {snapshot.cost.pricingCatalogEffective}.
        {snapshot.cost.billedThrough ? ` Billed through ${utcDate(snapshot.cost.billedThrough)} UTC.` : ""}
        {snapshot.cost.lastBillingSuccessAt ? ` Last updated ${timeAgo(snapshot.cost.lastBillingSuccessAt)}.` : " Never successfully updated."}
      </div>
    </Card>
  );
}

function familyLabel(family: LlmCallTelemetry["family"]): string {
  return family === "summary" ? "Summarization" : family[0].toUpperCase() + family.slice(1);
}

export function familyForFunction(functionId: string): LlmCallTelemetry["family"] {
  const value = functionId.toLowerCase();
  if (value.includes("compress")) return "compression";
  if (value.includes("summar")) return "summary";
  if (value.includes("graph")) return "graph";
  if (value.includes("consolidat") || value.includes("reflect")) return "consolidation";
  return "other";
}

export function familyEstimatedCost(snapshot: LlmSnapshot, functionId: string): number {
  const family = familyForFunction(functionId);
  return snapshot.calls.filter((call) => call.family === family).reduce((sum, call) => sum + (call.estimatedCostNanos ?? 0), 0);
}

function QueueStatus({ snapshot }: { snapshot: LlmSnapshot }) {
  const running = snapshot.jobs.filter((job) => job.status === "running").length;
  const queue = snapshot.queue;
  const providerSlots = snapshot.config.providerConcurrency;
  return (
    <Card className="grid gap-3 p-4 md:grid-cols-[1fr_auto] md:items-center">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-none items-center justify-center rounded-lg bg-peri/10 text-peri">
          <ListChecks size={18} />
        </div>
        <div>
          <div className="font-display text-[13px] font-semibold text-fg1">Durable LLM queue</div>
          <div className="mt-1 text-[11px] leading-[1.5] text-fg3">
            File-backed iii queue absorbs hook bursts; ID-only jobs become prompts after a worker starts, then the provider gate admits {providerSlots === 1 ? "one endpoint call" : providerSlots ? `${fmtNum(providerSlots)} endpoint calls` : "a bounded number of endpoint calls"} at a time.
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
        <Setting label="Depth" value={queue ? fmtNum(queue.depth) : "—"} mono />
        <Setting label="Running" value={fmtNum(queue?.activeJobs ?? running)} mono />
        <Setting label="Workers" value={queue ? fmtNum(queue.consumers) : "—"} mono />
        <Setting label="Provider slots" value={fmtNum(providerSlots)} mono />
        <Setting label="Recovery wave" value={fmtNum(snapshot.config.recoveryBatchSize)} mono />
        <Setting label="DLQ" value={queue ? fmtNum(queue.dlqDepth) : "—"} mono />
      </div>
    </Card>
  );
}

function RecentCalls({ calls, showCost, pageSize }: { calls: LlmCallTelemetry[]; showCost: boolean; pageSize: number }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(calls.length / pageSize));
  const safePage = Math.min(page, pages - 1);
  const rows = calls.slice(safePage * pageSize, (safePage + 1) * pageSize);
  useEffect(() => { if (page >= pages) setPage(Math.max(0, pages - 1)); }, [page, pages]);
  return (
    <Card className="overflow-hidden" data-testid="exact-provider-calls">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <div className="flex items-center gap-1.5"><div className="font-display text-[14px] font-semibold text-fg1">Exact provider calls</div><HelpTopic id="exact-provider-calls" /></div>
          <div className="mt-0.5 text-[10px] text-fg3">Newest first · {fmtNum(calls.length)} retained · prompt and response content are never collected</div>
        </div>
        <Pill tone={rows.some((row) => row.status === "running") ? "warn" : "ok"}>
          {rows.some((row) => row.status === "running") ? "IN FLIGHT" : "IDLE"}
        </Pill>
      </div>
      {rows.length === 0 ? (
        <div className="flex min-h-[150px] items-center justify-center px-4">
          <EmptyState
            icon={<Clock3 size={22} />}
            title="No provider calls recorded yet"
            body="Queued jobs and every compression, summary, graph, or consolidation provider call will appear here as work runs."
          />
        </div>
      ) : (
        <div className="max-h-[360px] overflow-auto" data-testid="exact-provider-calls-window">
          <table className="w-full min-w-[1240px] text-left text-[11px]">
            <thead className="sticky top-0 z-10 bg-side text-[9px] uppercase tracking-[0.12em] text-fg3">
              <tr>
                <th className="px-4 py-2.5 font-medium">Started</th>
                <th className="px-3 py-2.5 font-medium">Family</th>
                <th className="px-3 py-2.5 font-medium">Outcome</th>
                <th className="px-3 py-2.5 font-medium">Model</th>
                <th className="px-3 py-2.5 font-medium">Project</th>
                <th className="px-3 py-2.5 font-medium">Prompt</th>
                <th className="px-3 py-2.5 font-medium">Tokens</th>
                <th className="px-3 py-2.5 font-medium">Output rate</th>
                {showCost ? <th className="px-3 py-2.5 font-medium">Est. cost</th> : null}
                <th className="px-3 py-2.5 font-medium">Durable wait</th>
                <th className="px-3 py-2.5 font-medium">Provider gate</th>
                <th className="px-4 py-2.5 font-medium">Provider</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((call) => {
                const outcome = call.status === "running" ? "running" : call.outcome ?? "unknown";
                return (
                  <tr key={call.id} className="text-fg2">
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-fg3">{timeAgo(call.startedAt)}</td>
                    <td className="px-3 py-2.5 font-display font-semibold text-fg1">{familyLabel(call.family)}</td>
                    <td className="px-3 py-2.5"><Pill tone={outcome === "success" ? "ok" : outcome === "running" ? "warn" : "bad"}>{outcome.toUpperCase()}</Pill></td>
                    <td className="max-w-[190px] truncate px-3 py-2.5 font-mono" title={call.model ?? undefined}>{call.model ?? "—"}</td>
                    <td className="max-w-[150px] truncate px-3 py-2.5" title={call.project ?? undefined}>{call.project ?? "Unscoped"}</td>
                    <td className="px-3 py-2.5 font-mono">{fmtNum(call.promptChars)} chars</td>
                    <td className="px-3 py-2.5 font-mono" title={`input ${fmtNum(call.promptTokens)} · cached ${fmtNum(call.cachedPromptTokens)} · output ${fmtNum(call.completionTokens)} · reasoning ${fmtNum(call.reasoningTokens)}`}>{call.totalTokens === null ? `~${fmtNum(call.estimatedPromptTokens)}` : fmtNum(call.totalTokens)}</td>
                    <td className="px-3 py-2.5 font-mono" title="Completion tokens divided by provider latency; includes time-to-first-token">{fmtTokensPerSecond(callTokensPerSecond(call))}</td>
                    {showCost ? <td className="px-3 py-2.5 font-mono">{call.costCoverage === "unpriced" ? "Unpriced" : fmtUsdNanos(call.estimatedCostNanos)}</td> : null}
                    <td className="px-3 py-2.5 font-mono">{fmtMs(Math.max(0, call.queueWaitMs - call.providerGateWaitMs))}</td>
                    <td className="px-3 py-2.5 font-mono">{fmtMs(call.providerGateWaitMs)}</td>
                    <td className="px-4 py-2.5 font-mono">{call.providerLatencyMs === null ? "running" : fmtMs(call.providerLatencyMs)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {calls.length > 0 ? <div className="flex items-center justify-between border-t border-line px-4 py-2.5"><span className="font-mono text-[10px] text-fg3">{fmtNum(safePage * pageSize + 1)}–{fmtNum(Math.min(calls.length, (safePage + 1) * pageSize))} of {fmtNum(calls.length)}</span><Paginator page={safePage} pages={pages} onPage={setPage} /></div> : null}
    </Card>
  );
}

export default function LlmCalls() {
  const { sectionVisible, count } = usePagePreferences("llm");
  const { tick, llmCompletions } = useLive();
  const [snapshot, setSnapshot] = useState<LlmSnapshot | null>(null);
  const [loaded, setLoaded] = useState(false);
  const now = useNow();
  const updateBilling = (billing: BillingStatusSnapshot) => {
    setSnapshot((current) => current ? { ...current, cost: { ...current.cost, ...billing } } : current);
  };

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<LlmSnapshot>("/api/llm");
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

  return (
    <div className="flex min-h-full flex-col gap-5">
      <PageHeader
        title="LLM Calls"
        helpId="exact-provider-calls"
        subtitle="durable queue pressure, exact safe provider calls, and configured LLM features"
        right={
          <div className="flex items-center gap-2 text-[11px] text-fg3">
            {snapshot ? <>
              <Pill tone={snapshot.upstreamOk ? "ok" : "bad"}>
                {snapshot.upstreamOk ? "TELEMETRY LIVE" : "UPSTREAM OFFLINE"}
              </Pill>
              updated {timeAgo(snapshot.ts)}
            </> : null}
            <Link to="/operations" className="rounded-lg border border-line bg-side px-3 py-2 font-display text-[11px] font-semibold text-fg2 no-underline hover:border-turq/40 hover:text-fg1">Operations</Link>
          </div>
        }
      />

      {sectionVisible("metrics") ? <MetricsTiles tick={tick} empty={!tick} /> : null}

      {!loaded ? (
        <Card className="flex min-h-[280px] items-center justify-center">
          <div className="inline-flex items-center gap-2 text-sm text-fg3">
            <RefreshCw size={16} className="animate-spin" /> Loading LLM telemetry…
          </div>
        </Card>
      ) : snapshot === null ? (
        <Card className="flex min-h-[280px] items-center justify-center">
          <EmptyState
            icon={<BrainCircuit size={24} />}
            title="LLM telemetry unavailable"
            body="The console API did not answer. No provider secrets or prompt content are required for this page."
          />
        </Card>
      ) : (
        <>
          {sectionVisible("provider") ? <ProviderOverview snapshot={snapshot} /> : null}

          {sectionVisible("cost") && snapshot.config.costApplicability !== "local" ? <CostOverview snapshot={snapshot} onBillingUpdated={updateBilling} /> : null}

          {sectionVisible("summary") ? <LlmSummaryTiles snapshot={snapshot} /> : null}

          {sectionVisible("queue") ? <QueueStatus snapshot={snapshot} /> : null}

          {sectionVisible("families") ? <section>
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <div className="font-display text-[14px] font-semibold text-fg1">Tracked call families</div>
                <div className="mt-0.5 text-[11px] text-fg3">
                  Cards glow turquoise on successful completions and coral when failures are detected.
                </div>
              </div>
              <div className="text-[10px] text-fg3">rolling {Math.round(snapshot.windowMs / 60_000)} minutes</div>
            </div>
            <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-2">
              {snapshot.functions.map((summary) => (
                (() => {
                  const throughput = llmOutputThroughput(snapshot.calls, { since: now - snapshot.windowMs, family: llmFamilyForFunction(summary.functionId) });
                  return <CallCard
                    key={summary.functionId}
                    summary={summary}
                    events={llmCompletions}
                    now={now}
                    costNanos={familyEstimatedCost(snapshot, summary.functionId)}
                    showCost={snapshot.config.costApplicability !== "local"}
                    tokensPerSecond={throughput.tokensPerSecond}
                    throughputSamples={throughput.measuredCalls}
                  />;
                })()
              ))}
            </div>
          </section> : null}

          {sectionVisible("features") ? <section>
            <div className="mb-3">
              <div className="font-display text-[14px] font-semibold text-fg1">Configured feature settings</div>
              <div className="mt-0.5 text-[11px] text-fg3">
                Runtime flags reported by AgentMemory; these are status only and cannot be edited here.
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 2xl:grid-cols-4">
              {snapshot.features.map((flag) => (
                <FeatureCard key={flag.key} flag={flag} />
              ))}
            </div>
          </section> : null}

          {sectionVisible("boundary") ? <Card className="flex items-start gap-3 px-4 py-3.5">
            <ShieldCheck size={17} className="mt-0.5 flex-none text-turq" />
            <div className="text-[11px] leading-[1.55] text-fg3">
              <span className="font-display font-semibold text-fg2">Telemetry boundary:</span>{" "}
              The deployment compatibility layer publishes queue state and safe per-call metadata for
              compression, summarization, graph extraction, and consolidation. Prompt and response
              bodies, complete provider keys, and raw error messages never enter this console. Key hints show
              only the family prefix, six identifier characters, and final four so you can distinguish rotated credentials.
            </div>
          </Card> : null}

          {sectionVisible("recentCalls") ? <RecentCalls calls={snapshot.calls.slice(0, count("recentCallCount", 100))} pageSize={count("recentCallPageSize", 20)} showCost={snapshot.config.costApplicability !== "local"} /> : null}
        </>
      )}
    </div>
  );
}
