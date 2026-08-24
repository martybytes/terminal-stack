import { useEffect, useState } from "react";
import { Brain, CheckCircle2, FolderCheck, SearchCheck, Waypoints, Gauge, Sparkles } from "lucide-react";
import { Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import type { ContextAvoidedHistorySnapshot, ContextAvoidedHistoryWindow, MemoryEffectivenessSnapshot } from "../../shared/types";
import { lifecycleLabel } from "../../shared/memoryLifecycle";
import { apiGet } from "../lib/api";
import { fmtCompactNum, fmtCompactRange, fmtNum } from "../lib/format";
import { Card, Pill } from "./ui";
import { usePagePreferences } from "../lib/preferences";
import { storageAttempts, storedCount } from "../../shared/memoryFlow";
import { estimateLabel } from "../../shared/memoryEconomics";
import { HelpTerm, HelpTopic } from "./ContextHelp";
import { helpIdForLabel } from "../lib/helpCatalog";

const REFRESH_MS = 5_000;
const HISTORY_REFRESH_MS = 60_000;

export function useMemoryEffectiveness(): MemoryEffectivenessSnapshot | null {
  const [snapshot, setSnapshot] = useState<MemoryEffectivenessSnapshot | null>(null);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<MemoryEffectivenessSnapshot>("/api/memory-effectiveness");
      if (!disposed && next) setSnapshot(next);
    };
    void refresh();
    const interval = window.setInterval(() => { if (!document.hidden) void refresh(); }, REFRESH_MS);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { disposed = true; window.clearInterval(interval); document.removeEventListener("visibilitychange", visible); };
  }, []);
  return snapshot;
}

export function useContextAvoidedHistory(): ContextAvoidedHistorySnapshot | null {
  const [snapshot, setSnapshot] = useState<ContextAvoidedHistorySnapshot | null>(null);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      const next = await apiGet<ContextAvoidedHistorySnapshot>("/api/memory-effectiveness/history");
      if (!disposed && next) setSnapshot(next);
    };
    void refresh();
    const interval = window.setInterval(() => { if (!document.hidden) void refresh(); }, HISTORY_REFRESH_MS);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { disposed = true; window.clearInterval(interval); document.removeEventListener("visibilitychange", visible); };
  }, []);
  return snapshot;
}

function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function Mini({
  label,
  displayLabel,
  value,
  valueTitle,
  sub,
  subTitle,
  icon,
}: {
  label: string;
  displayLabel?: string;
  value: string;
  valueTitle?: string;
  sub: string;
  subTitle?: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="min-w-0 border-l border-line pl-2.5 first:border-l-0 first:pl-0">
      <div className="flex min-h-[22px] min-w-0 items-start gap-1.5 font-display text-[10px] font-medium leading-[1.15] tracking-[0.01em] text-fg3" data-readable-text>
        <span className="mt-px flex-none text-turq">{icon}</span>
        <HelpTerm id={helpIdForLabel(label)}>{displayLabel ?? label}</HelpTerm>
      </div>
      <div className="whitespace-nowrap font-display text-[16px] font-bold leading-tight text-fg1" title={valueTitle} aria-label={valueTitle ?? `${label}: ${value}`} data-readable-text>{value}</div>
      <div className="text-[10px] leading-tight text-fg3 [overflow-wrap:anywhere]" title={subTitle} data-readable-text>{sub}</div>
    </div>
  );
}

function historicValue(window: ContextAvoidedHistoryWindow | null): string {
  return window && window.modeledRetrievals > 0
    ? fmtCompactRange(window.estimatedAvoidedTokensLow, window.estimatedAvoidedTokensHigh)
    : "—";
}

function historicTitle(label: string, window: ContextAvoidedHistoryWindow | null, trackingSince?: number | null): string {
  if (!window || window.modeledRetrievals === 0) return `${label}: no modeled recalls recorded`;
  const since = trackingSince ? ` since ${new Date(trackingSince).toLocaleString()}` : "";
  return `${label}${since}: ${fmtNum(window.estimatedAvoidedTokensLow)}–${fmtNum(window.estimatedAvoidedTokensHigh)} estimated tokens across ${fmtNum(window.modeledRetrievals)} modeled recalls`;
}

function ContextAvoidedMini({
  liveValue,
  liveTitle,
  liveModeled,
  history,
}: {
  liveValue: string;
  liveTitle?: string;
  liveModeled: number;
  history: ContextAvoidedHistorySnapshot | null;
}) {
  const windows = [
    { label: "15m", value: liveValue, title: liveTitle ?? "Rolling 15 minutes: no modeled recalls recorded" },
    { label: "24h", value: historicValue(history?.past24Hours ?? null), title: historicTitle("Past 24 hours", history?.past24Hours ?? null) },
    { label: "7d", value: historicValue(history?.past7Days ?? null), title: historicTitle("Past 7 days", history?.past7Days ?? null) },
    { label: "All", value: historicValue(history?.allTracked ?? null), title: historicTitle("All tracked history", history?.allTracked ?? null, history?.trackingSince) },
  ];
  return (
    <div className="col-span-2 min-w-0 border-l border-line pl-2.5">
      <div className="flex min-h-[22px] min-w-0 items-start gap-1.5 font-display text-[10px] font-medium leading-[1.15] tracking-[0.01em] text-fg3" data-readable-text>
        <span className="mt-px flex-none text-turq"><Sparkles size={14} /></span>
        <HelpTerm id="estimated-context-avoided">Context avoided</HelpTerm>
      </div>
      <div className="grid gap-1 [grid-template-columns:repeat(auto-fit,minmax(58px,1fr))]">
        {windows.map((window, index) => (
          <div key={window.label} className={`${index === 0 ? "" : "border-l border-line pl-1.5"} min-w-0`} title={window.title} aria-label={window.title}>
            <div className="whitespace-nowrap text-[10px] leading-none text-fg3" data-readable-text>{window.label}</div>
            <div className="whitespace-nowrap font-display text-[12px] font-bold leading-tight text-fg1" data-readable-text>{window.value}</div>
          </div>
        ))}
      </div>
      <span className="sr-only">{fmtNum(liveModeled)} modeled recalls in the rolling 15-minute window</span>
    </div>
  );
}

export function MemoryEffectiveness({ snapshot, compact = false, avoidedHistory = null }: { snapshot: MemoryEffectivenessSnapshot | null; compact?: boolean; avoidedHistory?: ContextAvoidedHistorySnapshot | null }) {
  const { itemVisible } = usePagePreferences(compact ? "overview" : "projects");
  if (!snapshot) return <Card className={`${compact ? "min-h-[82px]" : "min-h-[120px]"} flex items-center justify-center text-xs text-fg3`}>Loading memory effectiveness…</Card>;
  const warningTone = snapshot.warnings.some((item) => item.severity === "bad") ? "bad" : snapshot.warnings.length ? "warn" : "ok";
  const stages = (["session_start", "context_recall", "file_enrichment", "manual_search", "observation_capture", "memory_save", "session_end"] as const)
    .filter((stage) => snapshot.lifecycle[stage] > 0);
  const chartData = snapshot.buckets.map((bucket) => ({
    time: new Date(bucket.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    saved: storedCount(bucket.memory),
    automatic: -bucket.economics.automaticHits,
    manual: -bucket.economics.manualHits,
    empty: -bucket.economics.automaticMisses,
  }));
  const attempts = storageAttempts(snapshot.memory);
  const saveRate = attempts > 0 ? storedCount(snapshot.memory) / attempts : null;
  const automaticRate = snapshot.economics.automaticAttempts > 0 ? snapshot.economics.automaticHits / snapshot.economics.automaticAttempts : null;
  const startRate = snapshot.lifecycle.session_start > 0 ? snapshot.sessionStartsAssisted / snapshot.lifecycle.session_start : null;
  const conceptRate = snapshot.quality.total > 0 ? snapshot.quality.conceptTagged / snapshot.quality.total : null;
  const confidence = estimateLabel(snapshot.economics);
  const avoided = snapshot.economics.modeledRetrievals > 0
    ? fmtCompactRange(snapshot.economics.estimatedAvoidedTokensLow, snapshot.economics.estimatedAvoidedTokensHigh)
    : "—";
  const avoidedExact = snapshot.economics.modeledRetrievals > 0
    ? `${fmtNum(snapshot.economics.estimatedAvoidedTokensLow)}–${fmtNum(snapshot.economics.estimatedAvoidedTokensHigh)} tokens`
    : undefined;
  return (
    <Card className={compact ? "px-3 py-2.5" : "p-4"} data-testid="memory-effectiveness">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Brain size={compact ? 14 : 17} className="flex-none text-peri" />
          <div className="truncate font-display text-[12px] font-semibold text-fg1">Memory value · rolling 15 minutes</div>
          <HelpTopic id="estimated-context-avoided" />
          <div className="hidden truncate font-mono text-[9px] text-fg3 xl:block">
            {stages.length ? stages.map((stage) => `${lifecycleLabel(stage)} ${fmtNum(snapshot.lifecycle[stage])}`).join(" · ") : "waiting for lifecycle traffic"}
          </div>
        </div>
        <Pill tone={warningTone}>{snapshot.warnings.length ? `${snapshot.warnings.length} CHECK${snapshot.warnings.length === 1 ? "" : "S"}` : "HEALTHY"}</Pill>
      </div>
      <div className={`grid gap-3 ${compact ? "grid-cols-1 xl:grid-cols-[minmax(250px,0.85fr)_minmax(0,2.35fr)]" : "grid-cols-1 xl:grid-cols-[minmax(360px,1.2fr)_minmax(0,2fr)]"}`}>
        <div className={`${compact ? "h-[64px]" : "h-[105px]"} min-w-0`}>
          <div className="mb-0.5 flex justify-between text-[8px] text-fg3"><span>stored ↑</span><span>automatic / manual context ↓</span></div>
          <ResponsiveContainer width="100%" height="90%"><BarChart data={chartData} barCategoryGap="16%"><ReferenceLine y={0} stroke="var(--color-linestrong)" /><Tooltip cursor={{ fill: "rgb(var(--rgb-fg) / 0.05)" }} contentStyle={{ background: "var(--color-tooltip)", border: "1px solid var(--color-linestrong)", borderRadius: 8, color: "var(--color-fg2)", fontSize: 10 }} /><Bar dataKey="saved" fill="var(--color-turq)" isAnimationActive={false} /><Bar dataKey="automatic" stackId="out" fill="var(--color-peri)" isAnimationActive={false} /><Bar dataKey="manual" stackId="out" fill="var(--color-s1)" isAnimationActive={false} /><Bar dataKey="empty" stackId="out" fill="var(--color-warn)" isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </div>
        <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(132px,1fr))]">
        {itemVisible("memoryFlow", "saveReliability") ? <Mini label="Save reliability" value={pct(saveRate)} sub={`${fmtNum(snapshot.memory.observationStored)} obs · ${fmtNum(snapshot.memory.explicitMemoriesStored)} explicit`} subTitle={`${fmtNum(snapshot.memory.observationStored)} observations · ${fmtNum(snapshot.memory.explicitMemoriesStored)} explicit memories`} icon={<CheckCircle2 size={14} />} /> : null}
        {itemVisible("memoryFlow", "automaticRecall") ? <Mini label="Automatic recall" displayLabel="Recall rate" value={pct(automaticRate)} sub={`${fmtCompactNum(snapshot.economics.automaticContextTokens)} tokens delivered`} icon={<SearchCheck size={14} />} /> : null}
        {itemVisible("memoryFlow", "estimatedAvoided") ? compact
          ? <ContextAvoidedMini liveValue={avoided} liveTitle={avoidedExact} liveModeled={snapshot.economics.modeledRetrievals} history={avoidedHistory} />
          : <Mini label="Estimated context avoided" displayLabel="Context avoided" value={avoided} valueTitle={avoidedExact} sub={`${fmtNum(snapshot.economics.modeledRetrievals)} modeled · ${confidence === "legacy_low" ? "low" : confidence === "live" ? "live" : "pending"}`} subTitle={`${fmtNum(snapshot.economics.modeledRetrievals)} modeled recalls · ${confidence === "legacy_low" ? "low confidence" : confidence === "live" ? "live byte model" : "needs samples"}`} icon={<Sparkles size={14} />} /> : null}
        {itemVisible("memoryFlow", "lifecycleCoverage") ? <Mini label="Start coverage" value={pct(startRate)} sub={`${fmtNum(snapshot.sessionStartsAssisted)} assisted · ${fmtNum(snapshot.sessionCloseouts)} closed`} subTitle={`${fmtNum(snapshot.sessionStartsAssisted)} assisted starts · ${fmtNum(snapshot.sessionCloseouts)} session closeouts`} icon={<Gauge size={14} />} /> : null}
        {itemVisible("memoryFlow", "manualContext") ? <Mini label="Manual context" value={fmtNum(snapshot.economics.manualContextTokens)} sub={`${fmtNum(snapshot.economics.manualHits)}/${fmtNum(snapshot.economics.manualAttempts)} searches returned`} icon={<SearchCheck size={15} />} /> : null}
        {itemVisible("memoryFlow", "projectIntegrity") ? <Mini label="Project integrity" value={pct(snapshot.projectCoverageRate)} sub={`${fmtNum(snapshot.unscopedResults + snapshot.crossProjectResults)} result warnings`} icon={<FolderCheck size={15} />} /> : null}
        {itemVisible("memoryFlow", "semanticCoverage") ? <Mini label="Semantic coverage" value={pct(conceptRate)} sub={`${fmtNum(snapshot.quality.sourceLinked)} source-linked`} subTitle={`${fmtNum(snapshot.quality.sourceLinked)} source-linked · ${fmtNum(snapshot.quality.superseded)} superseded`} icon={<Waypoints size={14} />} /> : null}
        </div>
      </div>
      {!compact && snapshot.warnings.length > 0 ? (
        <div className="mt-3 grid gap-2 lg:grid-cols-2">
          {snapshot.warnings.map((item) => (
            <div key={item.id} className="rounded-lg border border-line bg-side/45 px-3 py-2 text-[10px] leading-[1.45] text-fg3">
              <span className={item.severity === "bad" ? "font-semibold text-bad" : "font-semibold text-warn"}>{item.title}.</span> {item.detail}
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}
