import { Fragment, useMemo, useState } from "react";
import { Activity, Pause, Play } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useLive } from "../lib/ws";
import { fmtBytes, fmtClockMs, fmtMs, fmtNum } from "../lib/format";
import {
  Card,
  AgentPill,
  Chip,
  EmptyState,
  Eyebrow,
  IntentPill,
  LifecyclePill,
  MethodPill,
  PageHeader,
  StatusPill,
  SelectBox,
} from "../components/ui";
import { KNOWN_AGENTS, type KnownAgent, type RequestRecord } from "../../shared/types";
import { REQUEST_INTENTS, requestIntent, type RequestIntent } from "../../shared/requestIntent";
import { lifecycleLabel, MEMORY_LIFECYCLE_STAGES, requestLifecycle, type MemoryLifecycleStage } from "../../shared/memoryLifecycle";
import { usePagePreferences } from "../lib/preferences";
import { retrievalMode } from "../../shared/memoryEconomics";
import { HelpLabel } from "../components/ContextHelp";

const METHODS = ["GET", "POST", "PUT", "DELETE"] as const;
const STATUS_CLASSES = ["2xx", "4xx", "5xx"] as const;

type StatusClass = (typeof STATUS_CLASSES)[number];
type AgentClass = KnownAgent | "unknown";

function agentClass(agent: string | null): AgentClass {
  if (agent === "claude" || agent === "codex" || agent === "cursor") return agent;
  return "unknown";
}

function statusClass(status: number): StatusClass {
  if (status === 0 || status >= 500) return "5xx";
  if (status >= 400) return "4xx";
  return "2xx";
}

const TH = "border-b border-linestrong px-3 py-2.5 text-left font-display text-[10px] font-semibold uppercase tracking-[0.06em] text-fg3";
const TD = "border-b border-line px-3 py-2 align-middle text-[13px] text-fg2";

function DetailBand({ r }: { r: RequestRecord }) {
  const stage = r.lifecycle ?? requestLifecycle(r);
  const outcome = r.outcome;
  const resultScope = outcome && outcome.projectMatchCount !== null
    ? `${fmtNum(outcome.projectMatchCount)} project match · ${fmtNum(outcome.unscopedResultCount)} unscoped · ${fmtNum(outcome.crossProjectResultCount)} cross-project`
    : null;
  const topScore = outcome?.topScore !== null && outcome?.topScore !== undefined
    ? `top score ${outcome.topScore.toFixed(3)}`
    : null;
  const mode = retrievalMode(stage);
  const budget = outcome?.reportedTokenBudget ?? r.requestedTokenBudget;
  const avoided = outcome?.estimatedAvoidedTokensLow !== null && outcome?.estimatedAvoidedTokensLow !== undefined
    ? `${fmtNum(outcome.estimatedAvoidedTokensLow)}–${fmtNum(outcome.estimatedAvoidedTokensHigh)} estimated context avoided`
    : null;
  return (
    <div className="grid grid-cols-5 gap-4 text-xs">
      <div className="min-w-0">
        <div className="mb-1"><Eyebrow>Lifecycle</Eyebrow></div>
        <div className="flex items-center gap-2"><LifecyclePill stage={stage} />{mode !== "none" ? <span className="font-mono text-[9px] uppercase text-fg3">{mode}</span> : null}</div>
        <span className="mt-1 block truncate font-mono text-[10px] text-fg3" title={r.sessionId ?? undefined}>{r.sessionId ? `session ${r.sessionId.slice(0, 12)}` : "no session ID captured"}</span>
      </div>
      <div className="min-w-0">
        <div className="mb-1"><Eyebrow>Route</Eyebrow></div>
        <span className="block truncate font-mono text-xs text-fg2" title={r.operation ? `${r.route} · ${r.operation}` : r.route}>
          {r.route}{r.operation ? ` · ${r.operation}` : ""}
        </span>
      </div>
      <div className="min-w-0">
        <div className="mb-1"><Eyebrow>Captured</Eyebrow></div>
        <span className="block truncate font-mono text-xs text-fg2">
          #{r.id} · {fmtClockMs(r.ts)} · metadata only
        </span>
      </div>
      <div className="min-w-0">
        <div className="mb-1"><Eyebrow>Upstream</Eyebrow></div>
        <span className="block truncate font-mono text-xs text-fg2">
          {r.status === 0 ? "unreachable · 502 emitted by proxy" : `agentmemory · ${fmtMs(r.durMs)}`}
        </span>
      </div>
      <div className="min-w-0">
        <div className="mb-1"><Eyebrow>Safe outcome</Eyebrow></div>
        <span className="block truncate font-mono text-xs text-fg2">
          {outcome ? `${outcome.kind}${outcome.resultCount !== null ? ` · ${fmtNum(outcome.resultCount)} results` : ""}` : "not observable"}
        </span>
        <span className="mt-1 block truncate font-mono text-[10px] text-fg3">
          {outcome && ((outcome.contextTokens ?? 0) > 0 || (outcome.contextBlocks ?? 0) > 0)
            ? `${fmtNum(outcome.contextTokens)} tokens · ${fmtNum(outcome.contextBlocks)} blocks returned`
            : resultScope ?? topScore ?? "content never retained"}
        </span>
        {resultScope && topScore ? <span className="mt-1 block truncate font-mono text-[10px] text-fg3">{resultScope} · {topScore}</span> : null}
        {budget !== null || outcome?.truncated !== null || avoided ? <span className="mt-1 block truncate font-mono text-[10px] text-fg3">{budget !== null ? `budget ${fmtNum(budget)} · ` : ""}{outcome?.truncated === true ? "truncated · " : ""}{avoided ?? "within budget"}</span> : null}
      </div>
    </div>
  );
}

function ProjectName({ project }: { project: string | null }) {
  const scopedProject = project?.trim() || null;
  return (
    <div
      className={
        "truncate font-display text-xs font-semibold" +
        (scopedProject ? " text-fg1" : " text-fg3")
      }
      title={scopedProject ?? "Global request (no project scope)"}
    >
      {scopedProject ?? "Global"}
    </div>
  );
}

export default function Requests() {
  const { sectionVisible, itemVisible, count } = usePagePreferences("requests");
  const { requests, tick, paused, setPaused } = useLive();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectFilter = searchParams.get("project")?.trim() || null;

  const [pathQ, setPathQ] = useState("");
  const [methods, setMethods] = useState<Record<string, boolean>>({
    GET: true,
    POST: true,
    PUT: true,
    DELETE: true,
  });
  const [classes, setClasses] = useState<Record<StatusClass, boolean>>({
    "2xx": true,
    "4xx": true,
    "5xx": true,
  });
  const [agents, setAgents] = useState<Record<AgentClass, boolean>>({
    claude: true,
    codex: true,
    cursor: true,
    unknown: true,
  });
  const [intents, setIntents] = useState<Record<RequestIntent, boolean>>({
    lookup: true,
    write: true,
    health: true,
    admin: true,
    other: true,
  });
  const [hideHealth, setHideHealth] = useState(false);
  const [lifecycle, setLifecycle] = useState<"all" | MemoryLifecycleStage>("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const q = pathQ.trim().toLowerCase();
    return requests.filter((r) => {
      if (projectFilter && r.project?.trim() !== projectFilter) return false;
      if (hideHealth && requestIntent(r) === "health") return false;
      const m = r.method.toUpperCase();
      if (m in methods && !methods[m]) return false;
      if (!classes[statusClass(r.status)]) return false;
      if (!agents[agentClass(r.agent)]) return false;
      if (!intents[requestIntent(r)]) return false;
      if (lifecycle !== "all" && (r.lifecycle ?? requestLifecycle(r)) !== lifecycle) return false;
      if (q && !r.path.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [requests, projectFilter, pathQ, methods, classes, agents, intents, hideHealth, lifecycle]);

  const clearProjectFilter = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("project");
    setSearchParams(next, { replace: true });
  };

  const renderCap = count("rowCount", 100);
  const rows = filtered.slice(0, renderCap);
  const truncated = filtered.length > renderCap;
  const columnIds = ["time", "method", "intent", "lifecycle", "project", "agent", "path", "status", "duration", "requestBytes", "responseBytes"];
  const visibleColumns = columnIds.filter((id) => itemVisible("table", id));

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Live Requests"
        helpId="intent"
        subtitle="HTTP transport plus semantic intent · AgentMemory lookups often use POST · bodies are never captured"
        right={
          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 text-xs text-turq">
              <span className="h-[7px] w-[7px] rounded-full bg-turq" />
              {fmtNum(tick?.reqPerMin)} req/min
            </span>
            <button
              type="button"
              onClick={() => setPaused(!paused)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3.5 py-2 font-display text-xs font-semibold text-fg1 hover:border-turq/50"
            >
              {paused ? <Play size={14} /> : <Pause size={14} />}
              {paused ? "Resume" : "Pause"}
            </button>
          </div>
        }
      />

      {sectionVisible("filters") ? <div className="flex flex-wrap items-center gap-2">
        {projectFilter ? (
          <>
            <Chip on onClick={clearProjectFilter}>Project: {projectFilter} ×</Chip>
            <span className="mx-1 h-[22px] w-px bg-linestrong" />
          </>
        ) : null}
        <input
          type="text"
          value={pathQ}
          onChange={(e) => setPathQ(e.target.value)}
          placeholder="Filter by path…"
          className="w-[260px] rounded-lg border border-linestrong bg-side px-3 py-2 font-mono text-xs text-fg1 placeholder:text-fg3 focus:border-turq/50 focus:outline-none"
        />
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        {METHODS.map((m) => (
          <Chip key={m} on={methods[m]} onClick={() => setMethods((p) => ({ ...p, [m]: !p[m] }))}>
            {m}
          </Chip>
        ))}
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        {REQUEST_INTENTS.map((intent) => (
          <Chip key={intent} on={intents[intent]} onClick={() => setIntents((p) => ({ ...p, [intent]: !p[intent] }))}>
            {intent === "lookup" ? "Lookup" : intent.charAt(0).toUpperCase() + intent.slice(1)}
          </Chip>
        ))}
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        <SelectBox
          label="Lifecycle"
          value={lifecycle}
          onChange={(value) => setLifecycle(value as "all" | MemoryLifecycleStage)}
          options={[{ value: "all", label: "All stages" }, ...MEMORY_LIFECYCLE_STAGES.map((stage) => ({ value: stage, label: lifecycleLabel(stage) }))]}
        />
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        {STATUS_CLASSES.map((c) => (
          <Chip key={c} on={classes[c]} onClick={() => setClasses((p) => ({ ...p, [c]: !p[c] }))}>
            {c}
          </Chip>
        ))}
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        {[...KNOWN_AGENTS, "unknown" as const].map((agent) => (
          <Chip
            key={agent}
            on={agents[agent]}
            onClick={() => setAgents((p) => ({ ...p, [agent]: !p[agent] }))}
          >
            {agent.charAt(0).toUpperCase() + agent.slice(1)}
          </Chip>
        ))}
        <span className="mx-1 h-[22px] w-px bg-linestrong" />
        <Chip on={hideHealth} onClick={() => setHideHealth(!hideHealth)}>
          Hide health polls
        </Chip>
      </div> : null}

      {sectionVisible("table") ? <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {rows.length === 0 ? (
          <div className="flex flex-1 items-center justify-center py-16">
            <EmptyState
              icon={<Activity size={24} />}
              title={requests.length === 0 ? "Waiting for traffic" : "No requests match"}
              body={
                requests.length === 0
                  ? "Requests appear here the moment anything calls the 127.0.0.1:3111 proxy."
                  : projectFilter
                    ? `No requests for ${projectFilter} are present in the live buffer.`
                    : "Every captured request is filtered out. Loosen a filter to see traffic again."
              }
            />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <table className="w-full table-fixed border-collapse">
              <thead>
                <tr>
                  {itemVisible("table", "time") ? <th className={TH} style={{ width: 96 }}>Time</th> : null}
                  {itemVisible("table", "method") ? <th className={TH} style={{ width: 80 }}>Method</th> : null}
                  {itemVisible("table", "intent") ? <th className={TH} style={{ width: 92 }}><HelpLabel label="Intent" /></th> : null}
                  {itemVisible("table", "lifecycle") ? <th className={TH} style={{ width: 142 }}><HelpLabel label="Lifecycle" /></th> : null}
                  {itemVisible("table", "project") ? <th className={TH} style={{ width: 144 }}>Project</th> : null}
                  {itemVisible("table", "agent") ? <th className={TH} style={{ width: 104 }}>Agent</th> : null}
                  {itemVisible("table", "path") ? <th className={TH}>Path</th> : null}
                  {itemVisible("table", "status") ? <th className={TH} style={{ width: 72 }}>Status</th> : null}
                  {itemVisible("table", "duration") ? <th className={`${TH} text-right`} style={{ width: 88 }}>Duration</th> : null}
                  {itemVisible("table", "requestBytes") ? <th className={`${TH} text-right`} style={{ width: 80 }}><HelpLabel label="Request bytes" /></th> : null}
                  {itemVisible("table", "responseBytes") ? <th className={`${TH} text-right`} style={{ width: 80 }}><HelpLabel label="Response bytes" /></th> : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr
                      onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                      className={
                        "cursor-pointer hover:bg-surface2/50" +
                        (expanded === r.id ? " bg-peri/10" : "")
                      }
                    >
                      {itemVisible("table", "time") ? <td className={`${TD} font-mono text-xs text-fg3`}>{fmtClockMs(r.ts)}</td> : null}
                      {itemVisible("table", "method") ? <td className={TD}><MethodPill method={r.method} /></td> : null}
                      {itemVisible("table", "intent") ? <td className={TD}><IntentPill intent={requestIntent(r)} /></td> : null}
                      {itemVisible("table", "lifecycle") ? <td className={TD}><LifecyclePill stage={r.lifecycle ?? requestLifecycle(r)} /></td> : null}
                      {itemVisible("table", "project") ? <td className={TD}><ProjectName project={r.project} /></td> : null}
                      {itemVisible("table", "agent") ? <td className={TD}><AgentPill agent={r.agent} /></td> : null}
                      {itemVisible("table", "path") ? <td className={TD}>
                        <div
                          className={
                            "truncate font-mono text-xs" +
                            (requestIntent(r) === "health" ? " text-fg3" : "")
                          }
                          title={r.path}
                        >
                          {r.path}
                        </div>
                      </td> : null}
                      {itemVisible("table", "status") ? <td className={TD}><StatusPill status={r.status} /></td> : null}
                      {itemVisible("table", "duration") ? <td className={`${TD} text-right font-mono text-xs`}>{fmtMs(r.durMs)}</td> : null}
                      {itemVisible("table", "requestBytes") ? <td className={`${TD} text-right font-mono text-xs text-fg3`}>{fmtBytes(r.reqBytes)}</td> : null}
                      {itemVisible("table", "responseBytes") ? <td className={`${TD} text-right font-mono text-xs text-fg3`}>{fmtBytes(r.resBytes)}</td> : null}
                    </tr>
                    {expanded === r.id && (
                      <tr>
                        <td colSpan={Math.max(1, visibleColumns.length)} className="border-b border-line bg-side/50 px-4 py-3.5">
                          <DetailBand r={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[11px] text-fg3">
          <span>
            5,000-entry ring buffer · oldest entries roll off
            {truncated ? ` · first ${renderCap} of ${fmtNum(filtered.length)} rendered` : ""}
            {paused ? " · paused — new requests are not being appended" : ""}
          </span>
          <span className="font-mono">
            {fmtNum(rows.length)} shown · filtered from {fmtNum(requests.length)}
          </span>
        </div>
      </Card> : null}
    </div>
  );
}
