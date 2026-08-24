import { useEffect, useMemo, useState } from "react";
import { BookOpenCheck, Brain, DatabaseZap, GitBranch, RefreshCw, ShieldCheck } from "lucide-react";
import type { OperationPreview, OperationsSnapshot } from "../../shared/types";
import { Card, EmptyState, Eyebrow, PageHeader, Pill } from "../components/ui";
import { apiGet, apiPost } from "../lib/api";
import { fmtNum, fmtUsdNanos, timeAgo } from "../lib/format";
import { BillingRefreshButton } from "./LlmCalls";
import { usePagePreferences } from "../lib/preferences";

const actionButton = "rounded-lg border border-turq/35 bg-turq/10 px-3 py-2 font-display text-[11px] font-semibold text-turq transition hover:bg-turq/15 disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButton = "rounded-lg border border-line bg-side/60 px-3 py-2 font-display text-[11px] font-semibold text-fg2 transition hover:border-peri/40 hover:text-fg1 disabled:cursor-not-allowed disabled:opacity-40";

function PreviewPanel({ title, preview, showCost }: { title: string; preview: OperationPreview; showCost: boolean }) {
  return (
    <div className="rounded-lg border border-peri/25 bg-peri/5 p-3 text-[11px] text-fg2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-display font-semibold text-fg1">{title}</span>
        <Pill tone={preview.scanErrors > 0 ? "warn" : "ok"}>DRY RUN</Pill>
      </div>
      <div className={`mt-3 grid grid-cols-2 gap-2 ${showCost ? "sm:grid-cols-4" : "sm:grid-cols-3"}`}>
        <div><Eyebrow>Sessions</Eyebrow><div className="mt-1 font-mono">{fmtNum(preview.sessions)}</div></div>
        <div><Eyebrow>Raw observations</Eyebrow><div className="mt-1 font-mono">{fmtNum(preview.rawObservations ?? preview.observations)}</div></div>
        <div><Eyebrow>Projected jobs</Eyebrow><div className="mt-1 font-mono">{fmtNum((preview.queuedCompression ?? 0) + (preview.projectedSummaryJobs ?? 0) + (preview.projectedGraphJobs ?? 0) + (preview.queuedJobs ?? 0))}</div></div>
        {showCost ? <div><Eyebrow>Estimated cost</Eyebrow><div className="mt-1 font-mono">{fmtUsdNanos(preview.projectedCostNanos)}</div></div> : null}
      </div>
      {preview.hasMore ? <div className="mt-2 text-warn">This queues one bounded recovery wave; more work remains.</div> : null}
      {preview.scanErrors > 0 ? <div className="mt-2 text-warn">{fmtNum(preview.scanErrors)} session rows could not be scanned.</div> : null}
    </div>
  );
}

export default function Operations(): JSX.Element {
  const { sectionVisible } = usePagePreferences("operations");
  const [snapshot, setSnapshot] = useState<OperationsSnapshot | null>(null);
  const [project, setProject] = useState("");
  const [allProjects, setAllProjects] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [preview, setPreview] = useState<{ action: "maintenance" | "recovery"; value: OperationPreview } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const refresh = async () => {
    const next = await apiGet<OperationsSnapshot>("/api/operations");
    if (next) setSnapshot(next);
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5_000);
    return () => window.clearInterval(timer);
  }, []);

  const sessions = useMemo(() => snapshot?.sessions.filter((session) => !project || session.project === project) ?? [], [snapshot, project]);
  const scope = allProjects ? { allProjects: true } : project ? { project } : {};
  const perform = async (key: string, call: () => Promise<{ data: unknown; error: string | null }>, success: string) => {
    setBusy(key); setMessage(null);
    const result = await call();
    setBusy(null);
    if (result.error) setMessage({ tone: "bad", text: result.error });
    else { setMessage({ tone: "ok", text: success }); setPreview(null); void refresh(); }
  };
  const makePreview = async (action: "maintenance" | "recovery") => {
    setBusy(`${action}-preview`); setMessage(null);
    const result = await apiPost<OperationPreview>(`/api/operations/${action}/preview`, scope);
    setBusy(null);
    if (result.error || !result.data) setMessage({ tone: "bad", text: result.error ?? "Preview unavailable" });
    else setPreview({ action, value: result.data });
  };

  return (
    <div className="flex min-h-full flex-col gap-5">
      <PageHeader title="Operations" helpId="full-memory-maintenance" subtitle="safe maintenance, recovery, summaries, graph repair, and billing synchronization" right={snapshot ? <Pill tone={snapshot.upstreamOk ? "ok" : "bad"}>{snapshot.upstreamOk ? "READY" : "UPSTREAM OFFLINE"}</Pill> : null} />

      {sectionVisible("scope") ? <Card className="grid gap-4 p-4 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <div className="font-display text-[13px] font-semibold text-fg1">Operation scope</div>
          <p className="mt-1 max-w-3xl text-[11px] leading-[1.5] text-fg3">Full maintenance requires an explicit project or an explicit all-projects choice. Recovery can also be scoped to reduce queue pressure and projected spend.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select value={project} disabled={allProjects} onChange={(event) => { setProject(event.target.value); setPreview(null); }} className="min-w-[250px] rounded-lg border border-line bg-side px-3 py-2 text-[12px] text-fg1 outline-none focus:border-turq/50">
              <option value="">Select a project…</option>
              {(snapshot?.projects ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <label className="flex items-center gap-2 text-[11px] text-fg2"><input type="checkbox" checked={allProjects} onChange={(event) => { setAllProjects(event.target.checked); setProject(""); setPreview(null); }} /> All projects</label>
          </div>
        </div>
        <div className="text-right text-[10px] text-fg3">{snapshot ? `updated ${timeAgo(snapshot.ts)}` : "loading status…"}<br />{fmtNum(snapshot?.queue?.depth)} queued · {fmtNum(snapshot?.activeJobs.length)} active/recent</div>
      </Card> : null}

      {message ? <div className={`rounded-lg border px-4 py-3 text-[11px] ${message.tone === "ok" ? "border-turq/30 bg-turq/5 text-turq" : "border-bad/35 bg-bad/5 text-bad"}`}>{message.text}</div> : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {sectionVisible("maintenance") ? <Card className="flex flex-col gap-4 p-4">
          <div className="flex items-start gap-3"><div className="rounded-lg bg-peri/10 p-2 text-peri"><Brain size={18} /></div><div><div className="font-display text-[14px] font-semibold text-fg1">Full memory maintenance</div><p className="mt-1 text-[11px] leading-[1.5] text-fg3">Queues basic memory consolidation, then semantic, reflection, procedural, and decay maintenance.{snapshot?.costApplicability === "local" ? " The active local provider has no API fee." : " It can create paid LLM work."}</p></div></div>
          {preview?.action === "maintenance" ? <PreviewPanel title="Maintenance preview" preview={preview.value} showCost={snapshot?.costApplicability !== "local"} /> : null}
          <div className="mt-auto flex gap-2"><button className={secondaryButton} disabled={busy !== null || (!project && !allProjects)} onClick={() => void makePreview("maintenance")}>{busy === "maintenance-preview" ? "Scanning…" : "Preview"}</button><button className={actionButton} disabled={busy !== null || preview?.action !== "maintenance"} onClick={() => void perform("maintenance-run", () => apiPost("/api/operations/maintenance/run", { confirmationToken: preview?.value.confirmationToken }), "Full maintenance was queued.")}>Queue maintenance</button></div>
        </Card> : null}

        {sectionVisible("recovery") ? <Card className="flex flex-col gap-4 p-4">
          <div className="flex items-start gap-3"><div className="rounded-lg bg-warn/10 p-2 text-warn"><DatabaseZap size={18} /></div><div><div className="font-display text-[14px] font-semibold text-fg1">Recover pending LLM work</div><p className="mt-1 text-[11px] leading-[1.5] text-fg3">Scans for raw observations and missing derived work without modifying anything during preview. The run queues a bounded wave.</p></div></div>
          {preview?.action === "recovery" ? <PreviewPanel title="Recovery preview" preview={preview.value} showCost={snapshot?.costApplicability !== "local"} /> : null}
          <div className="mt-auto flex gap-2"><button className={secondaryButton} disabled={busy !== null} onClick={() => void makePreview("recovery")}>{busy === "recovery-preview" ? "Scanning…" : "Preview"}</button><button className={actionButton} disabled={busy !== null || preview?.action !== "recovery"} onClick={() => void perform("recovery-run", () => apiPost("/api/operations/recovery/run", { confirmationToken: preview?.value.confirmationToken }), "A bounded recovery wave was queued.")}>Queue recovery</button></div>
        </Card> : null}

        {sectionVisible("summary") ? <Card className="flex flex-col gap-4 p-4">
          <div className="flex items-start gap-3"><div className="rounded-lg bg-turq/10 p-2 text-turq"><BookOpenCheck size={18} /></div><div><div className="font-display text-[14px] font-semibold text-fg1">Force a session summary</div><p className="mt-1 text-[11px] leading-[1.5] text-fg3">Bypasses the normal change threshold for one selected session and queues the work durably.</p></div></div>
          <select value={sessionId} onChange={(event) => setSessionId(event.target.value)} className="rounded-lg border border-line bg-side px-3 py-2 text-[11px] text-fg1 outline-none focus:border-turq/50"><option value="">Select a session…</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.project ?? "Unscoped"} · {session.id.slice(0, 12)} · {fmtNum(session.observationCount)} observations</option>)}</select>
          <button className={`${actionButton} mt-auto self-start`} disabled={busy !== null || !sessionId} onClick={() => { if (window.confirm("Queue a forced summary for this session?")) void perform("summary", () => apiPost("/api/operations/summarize", { sessionId, project: sessions.find((row) => row.id === sessionId)?.project }), "The forced session summary was queued."); }}>Queue forced summary</button>
        </Card> : null}

        {sectionVisible("repairs") ? <Card className="flex flex-col gap-4 p-4">
          <div className="flex items-start gap-3"><div className="rounded-lg bg-peri/10 p-2 text-peri"><GitBranch size={18} /></div><div><div className="font-display text-[14px] font-semibold text-fg1">Local repairs and reconciliation</div><p className="mt-1 text-[11px] leading-[1.5] text-fg3">Rebuild the graph snapshot from stored graph state without an LLM call.{snapshot?.costApplicability === "local" ? " Billing synchronization is paused while local inference is active." : " You can also synchronize authoritative OpenAI cost buckets."}</p></div></div>
          {snapshot && snapshot.costApplicability !== "local" ? <div className="rounded-lg border border-line bg-side/45 px-3 py-2 text-[10px] text-fg3">{snapshot.billing.billingScope?.name ?? "OpenAI project"} · {snapshot.billing.lastBillingSuccessAt ? `last updated ${timeAgo(snapshot.billing.lastBillingSuccessAt)}` : "never successfully updated"}</div> : null}
          <div className="mt-auto flex flex-wrap items-start gap-2"><button className={secondaryButton} disabled={busy !== null} onClick={() => { if (window.confirm("Rebuild the graph snapshot from current graph state?")) void perform("graph", () => apiPost("/api/operations/graph-snapshot/rebuild"), "The graph snapshot was rebuilt."); }}><GitBranch size={13} className="mr-1 inline" />Rebuild graph snapshot</button>{snapshot && snapshot.costApplicability !== "local" ? <BillingRefreshButton billing={snapshot.billing} onUpdated={(billing) => setSnapshot((current) => current ? { ...current, billing } : current)} /> : null}</div>
        </Card> : null}
      </div>

      {!snapshot ? <Card className="flex min-h-[120px] items-center justify-center"><EmptyState icon={<RefreshCw size={20} />} title="Loading operation status" body="Reading projects, sessions, and queue state from AgentMemory." /></Card> : null}
      {sectionVisible("boundary") ? <Card className="flex items-start gap-3 px-4 py-3"><ShieldCheck size={17} className="mt-0.5 flex-none text-turq" /><div className="text-[11px] leading-[1.55] text-fg3"><span className="font-display font-semibold text-fg2">Safety boundary:</span> this page exposes no forget, delete, reset, restore, or bulk-governance actions. Maintenance and recovery require a fresh dry run; duplicate submissions are suppressed.</div></Card> : null}
    </div>
  );
}
