import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, SearchX, Users } from "lucide-react";
import { apiGet } from "../lib/api";
import { useLive } from "../lib/ws";
import { fmtClock, fmtNum } from "../lib/format";
import {
  AgentPill,
  Card,
  Chip,
  EmptyState,
  PageHeader,
  Paginator,
  Pill,
  SelectBox,
} from "../components/ui";
import type { PillTone } from "../components/ui";
import type { SessionSummary, TimelineItem, TimelinePage } from "../../shared/types";
import { usePagePreferences } from "../lib/preferences";

const SIZES = [25, 50, 75, 100];

const IMP_OPTIONS = [
  { value: "", label: "any" },
  { value: "3", label: "3+" },
  { value: "5", label: "5+" },
  { value: "7", label: "7+" },
  { value: "9", label: "9+" },
];

function typeTone(t: string | null): PillTone {
  const s = (t ?? "").toLowerCase();
  if (s.includes("summary") || s.includes("lesson")) return "ok";
  if (s.includes("file") || s.includes("edit")) return "post";
  if (s.includes("message") || s.includes("msg") || s.includes("prompt")) return "info";
  if (s.includes("tool") || s.includes("command") || s.includes("run")) return "get";
  return "na";
}

function hourLabel(ts: number | null): string {
  if (ts == null) return "Unknown time";
  const d = new Date(ts);
  const now = new Date();
  const day =
    d.toDateString() === now.toDateString()
      ? "Today"
      : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${day} · ${String(d.getHours()).padStart(2, "0")}:00`;
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

function ObsRow({ item, visible }: { item: TimelineItem; visible: (item: string) => boolean }) {
  return (
    <div className="flex gap-3 border-b border-line px-4 py-3 hover:bg-surface2/50">
      {visible("time") ? <span className="w-[60px] flex-none pt-0.5 font-mono text-xs text-fg3">
        {item.ts != null ? fmtClock(item.ts) : "—"}
      </span> : null}
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex items-center gap-2">
          {visible("type") ? <Pill tone={typeTone(item.type)}>{item.type ?? "unknown"}</Pill> : null}
          {visible("agent") ? <AgentPill agent={item.agent} /> : null}
          <span className="truncate font-display text-[13px] font-semibold text-fg1">
            {item.title ?? "Untitled"}
          </span>
          <span className="flex-1" />
          {visible("importance") ? <span className="whitespace-nowrap font-mono text-xs text-fg3">
            importance {item.importance ?? "—"}
          </span> : null}
        </div>
        {visible("content") ? <div className="truncate text-[13px] text-fg2">{item.content ?? ""}</div> : null}
      </div>
    </div>
  );
}

export default function Timeline() {
  const { sectionVisible, itemVisible, count, updatePage } = usePagePreferences("timeline");
  const { observations } = useLive();
  const [searchParams, setSearchParams] = useSearchParams();

  const session = searchParams.get("session") ?? "";
  const sort: "newest" | "oldest" = searchParams.get("sort") === "oldest" ? "oldest" : "newest";
  const sizeRaw = Number(searchParams.get("size"));
  const size = SIZES.includes(sizeRaw) ? sizeRaw : count("pageSize", 50);
  const pageRaw = Number(searchParams.get("page"));
  const page = Number.isFinite(pageRaw) && pageRaw > 0 ? Math.floor(pageRaw) : 0;
  const typesParam = searchParams.get("types") ?? "";
  const imp = searchParams.get("imp") ?? "";

  const [sessionList, setSessionList] = useState<SessionSummary[] | null>(null);
  const [data, setData] = useState<TimelinePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  function update(patch: Record<string, string | null>, replace = false) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v === null || v === "") next.delete(k);
          else next.set(k, v);
        }
        return next;
      },
      { replace },
    );
  }

  useEffect(() => {
    let alive = true;
    apiGet<unknown>("/api/sessions").then((d) => {
      if (!alive) return;
      const list = toSessions(d);
      list.sort((a, b) => (b.lastActiveAt ?? 0) - (a.lastActiveAt ?? 0));
      setSessionList(list);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Default to the most recently active session when none is in the URL.
  useEffect(() => {
    if (!session && sessionList && sessionList.length > 0) {
      update({ session: sessionList[0].id }, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, sessionList]);

  useEffect(() => {
    if (!session) {
      setData(null);
      return;
    }
    let alive = true;
    setLoading(true);
    // Note: the page URL uses short names (session/imp); the API expects
    // sessionId/minImportance — see /api/timeline in src/server/api.ts.
    const qs = new URLSearchParams();
    qs.set("sessionId", session);
    qs.set("sort", sort);
    qs.set("size", String(size));
    qs.set("page", String(page));
    if (typesParam) qs.set("types", typesParam);
    if (imp) qs.set("minImportance", imp);
    apiGet<TimelinePage>(`/api/timeline?${qs.toString()}`).then((d) => {
      if (!alive) return;
      setData(d);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [session, sort, size, page, typesParam, imp, refreshTick]);

  // Live prepend: a fresh observation for THIS session (while on newest/page 0)
  // schedules a refetch 2s out. Keyed on the newest matching observation so
  // other sessions' events can't disturb the schedule, and an already-pending
  // timer is never reset — a busy stream can't postpone the refresh forever.
  const latestObs = useMemo(
    () => observations.find((o) => o.sessionId === session) ?? null,
    [observations, session],
  );
  const refreshTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!latestObs || !session) return;
    if (sort !== "newest" || page !== 0) return;
    if (refreshTimer.current !== null) return; // refresh already pending
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      setRefreshTick((n) => n + 1);
    }, 2000);
  }, [latestObs, session, sort, page]);
  useEffect(() => {
    // Drop any pending refresh when the session changes or the page unmounts.
    return () => {
      if (refreshTimer.current !== null) {
        window.clearTimeout(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [session]);

  const selectedTypes = useMemo(
    () => (typesParam ? typesParam.split(",").filter(Boolean) : null),
    [typesParam],
  );

  function toggleType(t: string) {
    const all = data?.types ?? [];
    const cur = new Set(selectedTypes ?? all);
    if (cur.has(t)) cur.delete(t);
    else cur.add(t);
    const arr = all.filter((x) => cur.has(x));
    update({
      types: arr.length === all.length || arr.length === 0 ? null : arr.join(","),
      page: null,
    });
  }

  function clearFilters() {
    update({ types: null, imp: null, page: null });
  }

  const sessionOptions = (sessionList ?? []).map((s) => ({
    value: s.id,
    label: `${s.project ?? "unknown"} · ${s.agent ?? "unknown"} — ${s.id.slice(0, 8)}`,
  }));
  const selectedSession = sessionList?.find((s) => s.id === session) ?? null;

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));
  const from = total === 0 ? 0 : page * size + 1;
  const to = page * size + (data?.items.length ?? 0);

  const listRows: JSX.Element[] = [];
  if (data) {
    let lastLabel = "";
    for (const item of data.items) {
      const label = hourLabel(item.ts);
      if (label !== lastLabel) {
        lastLabel = label;
        listRows.push(
          <div key={`h-${item.id}`} className="flex items-center gap-2.5 px-4 pt-2.5 pb-1">
            <span className="whitespace-nowrap font-display text-[10px] font-semibold uppercase tracking-[0.06em] text-fg3">
              {label}
            </span>
            <span className="h-px flex-1 bg-line" />
          </div>,
        );
      }
      listRows.push(<ObsRow key={item.id} item={item} visible={(field) => itemVisible("observations", field)} />);
    }
  }

  if (sessionList !== null && sessionList.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col gap-4">
        <PageHeader title="Timeline" subtitle="per-session observation stream" />
        <Card className="flex flex-1 items-center justify-center">
          <EmptyState
            icon={<Users size={24} />}
            title="No sessions yet"
            body="Observations arrive once a configured coding agent starts reporting through the proxy."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Timeline"
        subtitle={
          <>
            {fmtNum(data?.total)} observations · session{" "}
            <span className="font-mono text-fg2">{session ? session.slice(0, 8) : "—"}</span>{" "}
            · <AgentPill agent={selectedSession?.agent ?? null} /> · new items appear at the top
          </>
        }
        right={
          <span className="rounded-lg border border-line bg-side/80 px-2.5 py-1.5 font-mono text-[11px] text-fg3">
            #/timeline?{searchParams.toString()}
          </span>
        }
      />

      {sectionVisible("filters") ? <div className="flex flex-wrap items-center gap-2">
        <SelectBox
          label="Session"
          value={session}
          onChange={(v) => update({ session: v, types: null, page: null })}
          options={sessionOptions}
        />
        <SelectBox
          label="Importance"
          value={imp}
          onChange={(v) => update({ imp: v || null, page: null })}
          options={IMP_OPTIONS}
        />
        <button
          type="button"
          onClick={() => update({ sort: sort === "newest" ? "oldest" : null, page: null })}
          className="inline-flex items-center gap-1.5 rounded-lg border border-linestrong bg-surface2 px-3.5 py-2 font-display text-xs font-semibold text-fg1 hover:border-turq/50"
        >
          {sort === "newest" ? <ArrowDownWideNarrow size={14} /> : <ArrowUpNarrowWide size={14} />}
          {sort === "newest" ? "Newest first" : "Oldest first"}
        </button>
        {(data?.types.length ?? 0) > 0 && <span className="mx-1 h-[22px] w-px bg-linestrong" />}
        {(data?.types ?? []).map((t) => (
          <Chip
            key={t}
            on={selectedTypes === null || selectedTypes.includes(t)}
            onClick={() => toggleType(t)}
          >
            {t}
          </Chip>
        ))}
        <span className="flex-1" />
        <SelectBox
          label="Page size"
          value={String(size)}
          onChange={(v) => { updatePage("timeline", (current) => ({ ...current, counts: { ...current.counts, pageSize: Number(v) } })); update({ size: null, page: null }); }}
          options={SIZES.map((s) => ({ value: String(s), label: `${s} / page` }))}
        />
      </div> : null}

      {sectionVisible("observations") ? <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {data && data.items.length > 0 ? (
          <>
            <div className="min-h-0 flex-1 overflow-y-auto">{listRows}</div>
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
              <span className="text-[11px] text-fg3">
                Showing {fmtNum(from)}–{fmtNum(to)} of {fmtNum(total)} · served pre-sorted by the
                console, the browser never downloads the full session
              </span>
              <Paginator page={page} pages={pages} onPage={(p) => update({ page: p === 0 ? null : String(p) })} />
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center py-16">
            {loading || (!data && sessionList === null) ? (
              <span className="font-mono text-xs text-fg3">loading observations…</span>
            ) : !data ? (
              <EmptyState
                icon={<SearchX size={24} />}
                title="Timeline unavailable"
                body="The console API did not answer. Check that the console process is running and can reach agentmemory."
              />
            ) : (
              <EmptyState
                icon={<SearchX size={24} />}
                title="No observations match"
                body={
                  <>
                    Session <span className="font-mono">{session.slice(0, 8)}</span> has no
                    observations matching the current filters. Loosen a filter, or switch sessions.
                  </>
                }
                actions={
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="rounded-lg border border-turq/50 bg-turq/15 px-3.5 py-2 font-display text-xs font-semibold text-turq hover:bg-turq/25"
                  >
                    Clear filters
                  </button>
                }
              />
            )}
          </div>
        )}
      </Card> : null}
    </div>
  );
}
