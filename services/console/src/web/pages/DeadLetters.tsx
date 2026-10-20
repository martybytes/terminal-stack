import { useEffect, useMemo, useState } from "react";
import { Inbox, RefreshCw, ShieldCheck } from "lucide-react";
import type { DlqRow, DlqSnapshot } from "../../shared/types";
import { Card, EmptyState, PageHeader, Paginator, Pill } from "../components/ui";
import { apiGet, apiPost } from "../lib/api";
import { fmtNum, fmtUsdNanos, timeAgo } from "../lib/format";
import { usePagePreferences } from "../lib/preferences";

const actionButton = "rounded-lg border border-turq/35 bg-turq/10 px-3 py-2 font-display text-[11px] font-semibold text-turq transition hover:bg-turq/15 disabled:cursor-not-allowed disabled:opacity-40";
const dangerButton = "rounded-lg border border-bad/35 bg-bad/5 px-3 py-2 font-display text-[11px] font-semibold text-bad transition hover:bg-bad/10 disabled:cursor-not-allowed disabled:opacity-40";
const PAGE_SIZE = 50;

function age(ms: number | null): string {
  if (ms === null) return "unknown";
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

function costText(snapshot: DlqSnapshot, count: number): string {
  if (snapshot.costApplicability === "local") return "no API fee";
  if (snapshot.estimatedCostNanos === null || snapshot.rows.length === 0) return "cost unknown (no priced calls to average yet)";
  return `about ${fmtUsdNanos(Math.round((snapshot.estimatedCostNanos / snapshot.rows.length) * count))}`;
}

export default function DeadLetters(): JSX.Element {
  const { sectionVisible } = usePagePreferences("deadLetters");
  const [snapshot, setSnapshot] = useState<DlqSnapshot | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const refresh = async () => {
    const next = await apiGet<DlqSnapshot>("/api/dlq");
    if (!next) return;
    setSnapshot(next);
    setSelected((current) => new Set([...current].filter((id) => next.rows.some((row) => row.id === id))));
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const rows = snapshot?.rows ?? [];
  const pages = Math.ceil(rows.length / PAGE_SIZE);
  const visible = useMemo(() => rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [rows, page]);
  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const run = async (action: "redrive" | "discard", all: boolean) => {
    if (!snapshot) return;
    const count = all ? rows.length : selected.size;
    if (count === 0) return;
    const what = `${fmtNum(count)} dead letter${count === 1 ? "" : "s"}`;
    const question = action === "discard"
      ? `Clear ${what}? The jobs are discarded for good. Their observations stay stored, uncompressed, and recovery can still pick them up later.`
      : `Process ${what}? They go back on the LLM queue (${costText(snapshot, count)}). Each job re-checks current state first, so finished work is skipped.`;
    if (!window.confirm(question)) return;
    setBusy(`${action}-${all ? "all" : "selected"}`); setMessage(null);
    const result = await apiPost<{ done: number; failed: number }>(`/api/dlq/${action}`, all ? { all: true } : { ids: [...selected] });
    setBusy(null);
    if (result.error || !result.data) setMessage({ tone: "bad", text: result.error ?? "AgentMemory did not accept the operation" });
    else {
      const verb = action === "redrive" ? "Requeued" : "Cleared";
      setMessage({ tone: "ok", text: `${verb} ${fmtNum(result.data.done)}${result.data.failed ? `; ${fmtNum(result.data.failed)} were already gone` : ""}.` });
      setSelected(new Set());
      void refresh();
    }
  };
  const resume = async () => {
    setBusy("resume"); setMessage(null);
    const result = await apiPost("/api/dlq-auto/resume");
    setBusy(null);
    if (result.error) setMessage({ tone: "bad", text: result.error });
    else { setMessage({ tone: "ok", text: "Automatic processing resumed." }); void refresh(); }
  };

  const paused = snapshot?.processor.pausedUntil !== null && (snapshot?.processor.pausedUntil ?? 0) > Date.now();
  const allOnPage = visible.length > 0 && visible.every((row) => selected.has(row.id));

  return (
    <div className="flex min-h-full flex-col gap-5">
      <PageHeader title="Dead letters" helpId="dead-letter" subtitle="LLM jobs that failed every retry, and what happens to them next" right={snapshot ? <Pill tone={rows.length === 0 ? "ok" : "warn"}>{fmtNum(rows.length)} WAITING</Pill> : null} />

      {sectionVisible("mode") && snapshot ? <Card className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={snapshot.mode === "automatic" ? "ok" : "info"}>{snapshot.mode === "automatic" ? "AUTOMATIC" : "MANUAL"}</Pill>
          {paused ? <Pill tone="warn">PAUSED</Pill> : null}
          <span className="font-display text-[13px] font-semibold text-fg1">
            {snapshot.mode === "automatic"
              ? "Free local model: dead letters under 24 hours old are reprocessed automatically once the model answers again."
              : "Paid or unrecognised model: nothing is reprocessed without you. Process or clear them below."}
          </span>
        </div>
        <p className="text-[11px] leading-[1.5] text-fg3">
          {snapshot.costReason}
          {snapshot.mode === "automatic" ? " Older dead letters are probably stale and wait here for a decision." : ` Processing all of them would cost ${costText(snapshot, rows.length)}.`}
        </p>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-fg2">
          <span>Last automatic run: {snapshot.processor.lastRunAt ? `${timeAgo(snapshot.processor.lastRunAt)}, ${fmtNum(snapshot.processor.lastRedriven)} requeued` : "never"}</span>
          {snapshot.processor.lastReason ? <span className="text-fg3">· {snapshot.processor.lastReason}</span> : null}
          {paused ? <button className={actionButton} disabled={busy !== null} onClick={() => void resume()}>Resume automatic processing</button> : null}
        </div>
      </Card> : null}

      {message ? <div className={`rounded-lg border px-4 py-3 text-[11px] ${message.tone === "ok" ? "border-turq/30 bg-turq/5 text-turq" : "border-bad/35 bg-bad/5 text-bad"}`}>{message.text}</div> : null}

      {sectionVisible("table") && snapshot && snapshot.available && rows.length > 0 ? <Card className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <button className={actionButton} disabled={busy !== null || selected.size === 0} onClick={() => void run("redrive", false)}>Process selected ({fmtNum(selected.size)})</button>
          <button className={dangerButton} disabled={busy !== null || selected.size === 0} onClick={() => void run("discard", false)}>Clear selected</button>
          <span className="mx-1 h-5 w-px bg-line" />
          <button className={actionButton} disabled={busy !== null} onClick={() => void run("redrive", true)}>Process all</button>
          <button className={dangerButton} disabled={busy !== null} onClick={() => void run("discard", true)}>Clear all</button>
          <div className="ml-auto"><Paginator page={page} pages={pages} onPage={setPage} /></div>
        </div>
        <table className="w-full text-left text-[11px]">
          <thead className="text-fg3">
            <tr>
              <th className="w-8 py-1"><input type="checkbox" checked={allOnPage} onChange={() => setSelected((current) => {
                const next = new Set(current);
                for (const row of visible) { if (allOnPage) next.delete(row.id); else next.add(row.id); }
                return next;
              })} /></th>
              <th>Family</th><th>Age</th><th>Retries</th><th>Project</th><th>Session</th><th />
            </tr>
          </thead>
          <tbody>
            {visible.map((row: DlqRow) => (
              <tr key={row.id} className="border-t border-line/60 text-fg2">
                <td className="py-1.5"><input type="checkbox" checked={selected.has(row.id)} onChange={() => toggle(row.id)} /></td>
                <td className="font-mono">{row.family}</td>
                <td className="font-mono">{age(row.ageMs)}</td>
                <td className="font-mono">{fmtNum(row.retries)}</td>
                <td>{row.project ?? <span className="text-fg3">-</span>}</td>
                <td className="font-mono">{row.sessionId ? row.sessionId.slice(0, 12) : "-"}</td>
                <td>{row.autoEligible ? <Pill tone="ok">AUTO</Pill> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card> : null}

      {snapshot && snapshot.available && rows.length === 0 ? <Card className="flex min-h-[120px] items-center justify-center"><EmptyState icon={<Inbox size={20} />} title="No dead letters" body="Every LLM job either finished or is still being retried." /></Card> : null}
      {snapshot && !snapshot.available ? <Card className="flex min-h-[120px] items-center justify-center"><EmptyState icon={<RefreshCw size={20} />} title="Dead letters unavailable" body="AgentMemory did not answer the dead-letter listing. It may be restarting." /></Card> : null}
      {!snapshot ? <Card className="flex min-h-[120px] items-center justify-center"><EmptyState icon={<RefreshCw size={20} />} title="Loading dead letters" body="Reading the LLM queue from AgentMemory." /></Card> : null}

      <Card className="flex items-start gap-3 px-4 py-3"><ShieldCheck size={17} className="mt-0.5 flex-none text-turq" /><div className="text-[11px] leading-[1.55] text-fg3"><span className="font-display font-semibold text-fg2">What these actions touch:</span> only the queued job. Process puts it back on the LLM queue, where it re-checks state before calling the model. Clear discards the job; the observation it was about is never deleted.</div></Card>
    </div>
  );
}
