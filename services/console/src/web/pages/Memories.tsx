import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Database, MousePointerClick, Search, X } from "lucide-react";
import { apiGet } from "../lib/api";
import { useLive } from "../lib/ws";
import { usePagePreferences } from "../lib/preferences";
import { fmtNum } from "../lib/format";
import {
  AgentPill,
  Card,
  EmptyState,
  Eyebrow,
  PageHeader,
  Paginator,
  Pill,
  SelectBox,
} from "../components/ui";
import type { PillTone } from "../components/ui";
import type { MemoriesPage, MemoryItem } from "../../shared/types";

const PAGE_SIZE = 20;

const TONE_CYCLE: PillTone[] = ["get", "post", "ok", "info", "put"];

function toneFor(t: string | null): PillTone {
  const s = (t ?? "").toLowerCase();
  if (!s) return "na";
  if (s.includes("semantic")) return "get";
  if (s.includes("procedur") || s.includes("workflow")) return "post";
  if (s.includes("lesson")) return "ok";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return TONE_CYCLE[h % TONE_CYCLE.length];
}

function fmtDate(ts: number | null): string {
  if (ts == null) return "—";
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function TagRow({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <span
          key={t}
          className="rounded-full border border-linestrong px-[7px] py-px font-mono text-[10px] text-fg3"
        >
          {t}
        </span>
      ))}
    </div>
  );
}

function MetaRow({ k, v, last }: { k: string; v: string; last?: boolean }) {
  return (
    <div
      className={
        "flex items-center justify-between gap-3 py-1.5" + (last ? "" : " border-b border-line")
      }
    >
      <Eyebrow>{k}</Eyebrow>
      <span className="min-w-0 truncate font-mono text-xs text-fg2" title={v}>
        {v}
      </span>
    </div>
  );
}

export default function Memories() {
  const { sectionVisible, itemVisible, count } = usePagePreferences("memories");
  const pageSize = count("pageSize", PAGE_SIZE);
  const { tick } = useLive();

  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [typeFilter, setTypeFilter] = useState("all");
  const [projectFilter, setProjectFilter] = useState("all");
  const [data, setData] = useState<MemoriesPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  // Types seen across every page fetched so far — the dropdown must offer
  // more than whatever happens to be on the current 20-item page.
  const [knownTypes, setKnownTypes] = useState<string[]>([]);

  // Debounce the search box 400ms into the effective query.
  useEffect(() => {
    const t = window.setTimeout(() => {
      const q = input.trim();
      setQuery((prev) => (prev === q ? prev : q));
    }, 400);
    return () => window.clearTimeout(t);
  }, [input]);

  useEffect(() => {
    setPage(0);
  }, [query, typeFilter, projectFilter]);

  // The type filter is applied SERVER-side (the /api/memories `type` param),
  // so paging and totals reflect the filter across all memories, not just
  // the rows that happen to be on the current page.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    const qs = new URLSearchParams();
    if (query) qs.set("query", query);
    if (typeFilter !== "all") qs.set("type", typeFilter);
    if (projectFilter !== "all") qs.set("project", projectFilter);
    qs.set("page", String(page));
    qs.set("size", String(pageSize));
    apiGet<MemoriesPage>(`/api/memories?${qs.toString()}`).then((d) => {
      if (!alive) return;
      setData(d);
      setLoading(false);
      if (d) {
        setKnownTypes((prev) => {
          const set = new Set(prev);
          for (const m of d.items) if (m.type) set.add(m.type);
          return set.size === prev.length ? prev : [...set].sort();
        });
      }
    });
    return () => {
      alive = false;
    };
  }, [query, page, typeFilter, projectFilter, pageSize]);

  const typeOptions = useMemo(() => {
    const set = new Set(knownTypes);
    if (typeFilter !== "all") set.add(typeFilter);
    return [
      { value: "all", label: "all" },
      ...Array.from(set)
        .sort()
        .map((t) => ({ value: t, label: t })),
    ];
  }, [knownTypes, typeFilter]);

  const shown = data?.items ?? [];
  const filtered = query !== "" || typeFilter !== "all" || projectFilter !== "all";

  const total = data?.total ?? tick?.memoriesTotal ?? null;
  const size = data?.size ?? pageSize;
  const pages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Memories"
        helpId="semantic-coverage"
        subtitle={`${fmtNum(total)} shown · ${fmtNum(data?.scopedTotal)} project-scoped · ${fmtNum(data?.unscopedTotal)} unscoped · ${query ? "hybrid BM25 + vector + graph search" : "stored memory inventory"}`}
        right={<Link to="/operations" className="rounded-lg border border-line bg-side px-3 py-2 font-display text-[11px] font-semibold text-fg2 no-underline hover:border-turq/40 hover:text-fg1">Memory operations</Link>}
      />

      {sectionVisible("filters") ? <div className="flex items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded-lg border border-linestrong bg-side px-3 py-2 focus-within:border-turq/50">
          <Search size={14} className="flex-none text-fg3" />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search memories… (hybrid semantic + keyword)"
            className="w-full bg-transparent font-mono text-xs text-fg1 placeholder:text-fg3 focus:outline-none"
          />
        </div>
        <SelectBox label="Type" value={typeFilter} onChange={setTypeFilter} options={typeOptions} />
        <SelectBox
          label="Project"
          value={projectFilter}
          onChange={setProjectFilter}
          options={[{ value: "all", label: "all projects" }, ...(data?.projects ?? []).map((project) => ({ value: project, label: project }))]}
        />
      </div> : null}

      {sectionVisible("warnings") && data && (data.unscopedTotal > 0 || data.rejectedResults > 0) ? (
        <div className="rounded-lg border border-warn/35 bg-warn/10 px-3 py-2 text-[11px] text-fg2">
          {data.unscopedTotal > 0 ? `${fmtNum(data.unscopedTotal)} explicit memories lack project metadata. ` : ""}
          {data.rejectedResults > 0 ? `${fmtNum(data.rejectedResults)} upstream search results were rejected because they did not prove the selected project.` : ""}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-3.5" style={{ gridTemplateColumns: sectionVisible("detail") ? `minmax(0,1fr) ${count("detailWidth", 420)}px` : "minmax(0,1fr)" }}>
        {sectionVisible("list") ? <Card className="flex min-h-0 flex-col overflow-hidden">
          {loading && !data ? (
            <div className="flex flex-1 items-center justify-center py-16">
              <span className="font-mono text-xs text-fg3">loading memories…</span>
            </div>
          ) : !data ? (
            <div className="flex flex-1 items-center justify-center py-16">
              <EmptyState
                icon={<Database size={24} />}
                title="Memories unavailable"
                body="The console API did not answer. Check that the console process is running and can reach agentmemory."
              />
            </div>
          ) : shown.length === 0 ? (
            <div className="flex flex-1 items-center justify-center py-16">
              <EmptyState
                icon={<Database size={24} />}
                title={filtered ? "No matches" : "No memories yet"}
                body={
                  filtered
                    ? "No memories match the current search and type filter. Try different terms or set Type back to all."
                    : "Memories appear here once agentmemory has compressed some observations."
                }
              />
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              {shown.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelected(m)}
                  className={
                    "block w-full border-b border-line px-4 py-3 text-left hover:bg-surface2/50" +
                    (selected?.id === m.id ? " bg-peri/10 shadow-[inset_2px_0_0_#8a80f0]" : "")
                  }
                >
                  <div className="mb-0.5 flex items-center gap-2">
                    {itemVisible("list", "type") ? <Pill tone={toneFor(m.type)}>{m.type ?? "unknown"}</Pill> : null}
                    {itemVisible("list", "kind") ? <Pill tone={m.recordKind === "memory" ? "info" : "na"}>{m.recordKind.toUpperCase()}</Pill> : null}
                    {itemVisible("list", "project") ? <Pill tone={m.project ? "ok" : "warn"}>{m.project ?? "UNSCOPED"}</Pill> : null}
                    {itemVisible("list", "agent") ? <AgentPill agent={m.agent} /> : null}
                    <span className="truncate font-display text-[13px] font-semibold text-fg1">
                      {m.title ?? "Untitled"}
                    </span>
                    <span className="flex-1" />
                    {itemVisible("list", "score") && query && m.score != null && (
                      <span className="font-mono text-xs text-turq">{m.score.toFixed(2)}</span>
                    )}
                  </div>
                  {itemVisible("list", "preview") ? <div className="truncate text-[13px] text-fg2">{m.content ?? ""}</div> : null}
                  {itemVisible("list", "tags") ? <TagRow tags={m.tags.slice(0, 6)} /> : null}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
            <span className="text-[11px] text-fg3">
              {data
                ? `${fmtNum(data.total)} ${filtered ? "matches" : "memories"} · ${shown.length} shown on this page`
                : "—"}
            </span>
            <Paginator page={page} pages={pages} onPage={setPage} />
          </div>
        </Card> : null}

        {sectionVisible("detail") ? <Card className="flex min-h-0 flex-col overflow-hidden">
          {selected ? (
            <>
              <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
                <Pill tone={toneFor(selected.type)}>{selected.type ?? "unknown"}</Pill>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="text-fg3 hover:text-fg1"
                  aria-label="Close detail"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                <div className="font-display text-base font-semibold leading-tight text-fg1">
                  {selected.title ?? "Untitled"}
                </div>
                {itemVisible("detail", "content") ? <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-fg2">
                  {selected.content ?? ""}
                </div> : null}
                {itemVisible("detail", "tags") ? <TagRow tags={selected.tags} /> : null}
                {itemVisible("detail", "provenance") ? <div>
                  <MetaRow k="ID" v={selected.id} />
                  <MetaRow k="Created" v={fmtDate(selected.createdAt)} />
                  <MetaRow k="Updated" v={fmtDate(selected.updatedAt)} />
                  <MetaRow k="Record kind" v={selected.recordKind} />
                  <MetaRow k="Project" v={selected.project ?? "Unscoped"} />
                  <MetaRow k="Agent" v={selected.agent ?? "Unknown"} />
                  <MetaRow k="Type" v={selected.type ?? "—"} />
                  <MetaRow k="Strength" v={selected.strength === null ? "—" : String(selected.strength)} />
                  <MetaRow k="Version" v={selected.version === null ? "—" : String(selected.version)} />
                  <MetaRow k="Latest" v={selected.isLatest ? "yes" : "superseded"} />
                  <MetaRow k="Files" v={selected.files.length ? selected.files.join(", ") : "—"} />
                  <MetaRow k="Sessions" v={selected.sessionIds.length ? selected.sessionIds.join(", ") : "—"} />
                  <MetaRow k="Source observations" v={selected.sourceObservationIds.length ? selected.sourceObservationIds.join(", ") : "—"} last />
                </div> : null}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState
                icon={<MousePointerClick size={24} />}
                title="No memory selected"
                body="Click a result to inspect its full content, tags, and metadata."
              />
            </div>
          )}
        </Card> : null}
      </div>
    </div>
  );
}
