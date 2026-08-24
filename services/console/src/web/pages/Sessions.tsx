import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Users } from "lucide-react";
import { apiGet } from "../lib/api";
import { fmtNum, timeAgo } from "../lib/format";
import { AgentPill, Card, EmptyState, PageHeader, Pill } from "../components/ui";
import type { SessionSummary } from "../../shared/types";
import { usePagePreferences } from "../lib/preferences";
import { HelpLabel } from "../components/ContextHelp";

const TH = "border-b border-linestrong px-3 py-2.5 text-left font-display text-[10px] font-semibold uppercase tracking-[0.06em] text-fg3";
const TD = "border-b border-line px-3 py-2.5 align-middle text-[13px] text-fg2";

function fmtDate(ts: number | null): string {
  if (ts == null) return "—";
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function toSessions(data: unknown): SessionSummary[] {
  const pick = (arr: unknown[]) =>
    arr.filter(
      (s): s is SessionSummary =>
        !!s && typeof (s as { id?: unknown }).id === "string",
    );
  if (Array.isArray(data)) return pick(data);
  if (data && typeof data === "object") {
    const inner = (data as { sessions?: unknown }).sessions;
    if (Array.isArray(inner)) return pick(inner);
  }
  return [];
}

export default function Sessions() {
  const { itemVisible, count } = usePagePreferences("sessions");
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    apiGet<unknown>("/api/sessions").then((d) => {
      if (!alive) return;
      if (d === null) {
        setFailed(true);
        setSessions([]);
        return;
      }
      setSessions(toSessions(d));
    });
    return () => {
      alive = false;
    };
  }, []);

  const sorted = useMemo(() => {
    if (!sessions) return [];
    return [...sessions].sort(
      (a, b) =>
        Number(b.active) - Number(a.active) ||
        (b.lastActiveAt ?? 0) - (a.lastActiveAt ?? 0),
    );
  }, [sessions]);

  const activeCount = sorted.filter((s) => s.active).length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Sessions"
        helpId="start-coverage"
        subtitle={
          sessions === null
            ? "loading…"
            : `${fmtNum(sessions.length)} sessions · ${fmtNum(activeCount)} active · click a row to open its timeline`
        }
        right={<Link to="/operations" className="rounded-lg border border-line bg-side px-3 py-2 font-display text-[11px] font-semibold text-fg2 no-underline hover:border-turq/40 hover:text-fg1">Summaries &amp; recovery</Link>}
      />

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {sessions === null ? (
          <div className="flex flex-1 items-center justify-center py-16">
            <span className="font-mono text-xs text-fg3">loading sessions…</span>
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-1 items-center justify-center py-16">
            <EmptyState
              icon={<Users size={24} />}
              title={failed ? "Sessions unavailable" : "No sessions yet"}
              body={
                failed
                  ? "The console API did not answer. Check that the console process is running and can reach agentmemory."
                  : "Sessions appear here once a configured coding agent starts reporting through the proxy."
              }
            />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[1320px] table-fixed border-collapse">
              <thead>
                <tr>
                  <th className={`${TH} ${itemVisible("table", "project") ? "" : "hidden"}`}>Project</th>
                  <th className={`${TH} ${itemVisible("table", "agent") ? "" : "hidden"}`} style={{ width: 104 }}>Agent</th>
                  <th className={`${TH} ${itemVisible("table", "session") ? "" : "hidden"}`} style={{ width: 120 }}>Session</th>
                  <th className={`${TH} ${itemVisible("table", "started") ? "" : "hidden"}`} style={{ width: 160 }}>Started</th>
                  <th className={`${TH} ${itemVisible("table", "active") ? "" : "hidden"}`} style={{ width: 130 }}>Last active</th>
                  <th className={`${TH} text-right ${itemVisible("table", "observations") ? "" : "hidden"}`} style={{ width: 120 }}>Observations</th>
                  <th className={`${TH} ${itemVisible("table", "lifecycle") ? "" : "hidden"}`} style={{ width: 260 }}><HelpLabel label="Lifecycle" /></th>
                  <th className={`${TH} ${itemVisible("table", "recall") ? "" : "hidden"}`} style={{ width: 145 }}><HelpLabel label="Automatic recall" /></th>
                  <th className={`${TH} ${itemVisible("table", "context") ? "" : "hidden"}`} style={{ width: 145 }}><HelpLabel label="Manual context" /></th>
                  <th className={`${TH} ${itemVisible("table", "status") ? "" : "hidden"}`} style={{ width: 110 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, count("rowCount", 100)).map((s) => (
                  <tr
                    key={s.id}
                    onClick={() =>
                      navigate(`/timeline?session=${encodeURIComponent(s.id)}`)
                    }
                    className="cursor-pointer hover:bg-surface2/50"
                  >
                    <td className={`${TD} ${itemVisible("table", "project") ? "" : "hidden"}`}>
                      <div className="truncate font-display text-[13px] font-semibold text-fg1">
                        {s.project ?? "unknown"}
                      </div>
                    </td>
                    <td className={`${TD} ${itemVisible("table", "agent") ? "" : "hidden"}`}><AgentPill agent={s.agent} /></td>
                    <td className={`${TD} font-mono text-xs text-fg3 ${itemVisible("table", "session") ? "" : "hidden"}`}>{s.id.slice(0, 8)}</td>
                    <td className={`${TD} font-mono text-xs ${itemVisible("table", "started") ? "" : "hidden"}`}>{fmtDate(s.startedAt)}</td>
                    <td className={`${TD} font-mono text-xs ${itemVisible("table", "active") ? "" : "hidden"}`}>
                      {s.lastActiveAt != null ? timeAgo(s.lastActiveAt) : "—"}
                    </td>
                    <td className={`${TD} text-right font-mono text-xs ${itemVisible("table", "observations") ? "" : "hidden"}`}>
                      {fmtNum(s.observationCount)}
                    </td>
                    <td className={`${TD} ${itemVisible("table", "lifecycle") ? "" : "hidden"}`}>
                      <div className="flex flex-wrap gap-x-2 gap-y-1 font-mono text-[10px]">
                        <span className={s.startContextDelivered ? "text-turq" : s.lifecycle.session_start > 0 ? "text-warn" : "text-fg3"}>start {s.startContextDelivered ? "assisted" : fmtNum(s.lifecycle.session_start)}</span>
                        <span className="text-turq">auto {fmtNum(s.automaticHits)}/{fmtNum(s.automaticRetrievals)}</span>
                        <span className="text-peri">capture {fmtNum(s.lifecycle.observation_capture + s.lifecycle.memory_save)}</span>
                        <span className={s.closeoutObserved ? "text-fg2" : "text-warn"}>end {s.closeoutObserved ? "yes" : "missing"}</span>
                      </div>
                    </td>
                    <td className={`${TD} font-mono text-xs ${itemVisible("table", "recall") ? "" : "hidden"}`}>
                      <span className={s.automaticRetrievals > 0 && s.automaticHits === 0 ? "text-warn" : "text-turq"}>{fmtNum(s.automaticHits)}/{fmtNum(s.automaticRetrievals)}</span>
                      <div className="mt-0.5 text-[9px] text-fg3">{fmtNum(s.automaticContextTokens)} tokens · {fmtNum(s.startContextTokens)} at start</div>
                    </td>
                    <td className={`${TD} font-mono text-xs ${itemVisible("table", "context") ? "" : "hidden"}`}>
                      {fmtNum(s.manualContextTokens)} tokens
                      <div className="mt-0.5 text-[9px] text-fg3">{fmtNum(s.manualHits)}/{fmtNum(s.manualRetrievals)} manual searches</div>
                    </td>
                    <td className={`${TD} ${itemVisible("table", "status") ? "" : "hidden"}`}>
                      {s.active ? <Pill tone="ok">active</Pill> : <Pill tone="na">completed</Pill>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[11px] text-fg3">
          <span>sessions come from GET /agentmemory/sessions via the console API</span>
          <span className="font-mono">legacy rows without an id are skipped</span>
        </div>
      </Card>
    </div>
  );
}
