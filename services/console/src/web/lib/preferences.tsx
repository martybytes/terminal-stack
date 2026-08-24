import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Check, ChevronDown, ChevronUp, GripVertical, RotateCcw, Search, X } from "lucide-react";

export const PREFERENCES_KEY = "agent007memory.preferences.v1";

export type PageId =
  | "dashboard" | "overview" | "projects" | "llm" | "reports" | "operations"
  | "requests" | "timeline" | "memories" | "sessions" | "help";
export type ThemeMode = "dark" | "light" | "system";
export type HelpMode = "adaptive" | "minimal" | "off";
export type PageWidth = "fluid" | "wide" | "focused";
export type PageDensity = "compact" | "comfortable";

export interface PreferenceItem { id: string; label: string }
export interface PreferenceSection {
  id: string;
  label: string;
  items?: PreferenceItem[];
  required?: boolean;
}
export interface PreferenceCount {
  id: string;
  label: string;
  min: number;
  max: number;
  step?: number;
  defaultValue: number;
}
export interface PageDefinition {
  id: PageId;
  label: string;
  sections: PreferenceSection[];
  counts?: PreferenceCount[];
  focused?: Partial<PagePreference>;
  projects?: boolean;
}

const METRICS: PreferenceItem[] = [
  { id: "memories", label: "Memories" },
  { id: "sessions", label: "Sessions" },
  { id: "observations", label: "Observations" },
  { id: "requests", label: "Requests per minute" },
  { id: "latency", label: "P95 latency" },
  { id: "uptime", label: "Uptime" },
];

const MEMORY_KPIS: PreferenceItem[] = [
  { id: "saveReliability", label: "Save reliability" },
  { id: "automaticRecall", label: "Automatic recall" },
  { id: "estimatedAvoided", label: "Estimated context avoided" },
  { id: "lifecycleCoverage", label: "Session lifecycle coverage" },
  { id: "manualContext", label: "Manual context" },
  { id: "projectIntegrity", label: "Project integrity" },
  { id: "semanticCoverage", label: "Semantic coverage" },
];

const LLM_KPIS: PreferenceItem[] = [
  { id: "completed", label: "Completed calls" },
  { id: "success", label: "Success rate" },
  { id: "providerLatency", label: "Provider latency" },
  { id: "outputRate", label: "Effective output rate" },
  { id: "queueDepth", label: "Queue depth" },
  { id: "queueWait", label: "Queue wait" },
  { id: "providerGate", label: "Provider gate" },
  { id: "jobRuntime", label: "Job runtime" },
  { id: "deadLetter", label: "Dead letter" },
  { id: "apiCost", label: "API cost today" },
  { id: "billedMtd", label: "Billed month to date" },
];

export const PAGE_DEFINITIONS: Record<PageId, PageDefinition> = {
  dashboard: {
    id: "dashboard", label: "Dashboard",
    sections: [
      { id: "metrics", label: "Global metrics", items: METRICS },
      { id: "requestsChart", label: "Requests chart" },
      { id: "observationsChart", label: "Observations chart" },
      { id: "latencyChart", label: "Latency chart" },
      { id: "processHealth", label: "Process health" },
      { id: "ticker", label: "Live request ticker" },
    ],
    focused: { hiddenSections: ["latencyChart", "processHealth"] },
  },
  overview: {
    id: "overview", label: "Overview", projects: true,
    sections: [
      { id: "metrics", label: "Global metrics", items: METRICS },
      { id: "memoryFlow", label: "Memory flow", items: MEMORY_KPIS },
      { id: "projects", label: "Project cards" },
      { id: "llmSummary", label: "LLM summary", items: LLM_KPIS },
      { id: "llmFamilies", label: "Tracked LLM families" },
    ],
    counts: [{ id: "projectCount", label: "Projects shown", min: 1, max: 24, defaultValue: 6 }],
    focused: { hiddenSections: ["metrics", "llmFamilies"] },
  },
  projects: {
    id: "projects", label: "Projects", projects: true,
    sections: [
      { id: "metrics", label: "Global metrics", items: METRICS },
      { id: "memoryFlow", label: "Memory flow", items: MEMORY_KPIS },
      { id: "projects", label: "Project cards" },
    ],
    counts: [{ id: "projectCount", label: "Projects shown", min: 1, max: 100, defaultValue: 100 }],
    focused: { counts: { projectCount: 6 } },
  },
  llm: {
    id: "llm", label: "LLM Calls",
    sections: [
      { id: "metrics", label: "Global metrics", items: METRICS },
      { id: "provider", label: "Provider configuration" },
      { id: "cost", label: "Provider cost" },
      { id: "summary", label: "Completion and queue KPIs", items: LLM_KPIS },
      { id: "queue", label: "Durable queue" },
      { id: "recentCalls", label: "Recent provider calls" },
      { id: "families", label: "Tracked call families" },
      { id: "features", label: "Feature settings" },
      { id: "boundary", label: "Telemetry boundary", required: true },
    ],
    counts: [
      { id: "recentCallCount", label: "Provider calls retained", min: 10, max: 250, step: 10, defaultValue: 100 },
      { id: "recentCallPageSize", label: "Calls per page", min: 10, max: 50, step: 5, defaultValue: 20 },
    ],
    focused: { hiddenSections: ["metrics", "provider", "recentCalls", "features"] },
  },
  reports: {
    id: "reports", label: "Reports",
    sections: [
      { id: "filters", label: "Range and comparison", required: true },
      { id: "totals", label: "Totals and KPI cards" },
      { id: "projects", label: "Project cards and tables" },
      { id: "charts", label: "Charts" },
      { id: "tables", label: "Detailed tables" },
      { id: "boundary", label: "Reporting boundary", required: true },
    ],
    counts: [{ id: "projectCount", label: "Project cards shown", min: 1, max: 24, defaultValue: 6 }],
    focused: { hiddenSections: ["tables"] },
  },
  operations: {
    id: "operations", label: "Operations",
    sections: [
      { id: "scope", label: "Operation scope", required: true },
      { id: "maintenance", label: "Full memory maintenance" },
      { id: "recovery", label: "Recover pending LLM work" },
      { id: "summary", label: "Force a session summary" },
      { id: "repairs", label: "Repairs and reconciliation" },
      { id: "boundary", label: "Safety boundary", required: true },
    ],
    focused: { hiddenSections: ["recovery", "repairs"] },
  },
  requests: {
    id: "requests", label: "Live Requests",
    sections: [
      { id: "filters", label: "Filters" },
      { id: "table", label: "Request table", items: [
        { id: "time", label: "Time" }, { id: "method", label: "Method" },
        { id: "intent", label: "Intent" }, { id: "lifecycle", label: "Lifecycle" },
        { id: "project", label: "Project" }, { id: "agent", label: "Agent" },
        { id: "path", label: "Path" }, { id: "status", label: "Status" },
        { id: "duration", label: "Duration" }, { id: "requestBytes", label: "Request bytes" },
        { id: "responseBytes", label: "Response bytes" },
      ] },
    ],
    counts: [{ id: "rowCount", label: "Rows rendered", min: 25, max: 500, step: 25, defaultValue: 100 }],
    focused: { hiddenItems: ["table.method", "table.intent", "table.requestBytes", "table.responseBytes"] },
  },
  timeline: {
    id: "timeline", label: "Timeline",
    sections: [
      { id: "filters", label: "Session and observation filters" },
      { id: "observations", label: "Observation cards", items: [
        { id: "type", label: "Type" }, { id: "importance", label: "Importance" },
        { id: "agent", label: "Agent" }, { id: "time", label: "Time" },
        { id: "content", label: "Content" },
      ] },
    ],
    counts: [{ id: "pageSize", label: "Observations per page", min: 25, max: 100, step: 25, defaultValue: 50 }],
    focused: { density: "compact" },
  },
  memories: {
    id: "memories", label: "Memories",
    sections: [
      { id: "filters", label: "Search and filters" },
      { id: "warnings", label: "Project-scope warnings" },
      { id: "list", label: "Memory list", items: [
        { id: "type", label: "Type" }, { id: "kind", label: "Record kind" },
        { id: "project", label: "Project" }, { id: "agent", label: "Agent" },
        { id: "score", label: "Search score" }, { id: "preview", label: "Content preview" },
        { id: "tags", label: "Concept tags" },
      ] },
      { id: "detail", label: "Detail panel", items: [
        { id: "content", label: "Full content" }, { id: "tags", label: "Concept tags" },
        { id: "provenance", label: "Provenance metadata" },
      ] },
    ],
    counts: [
      { id: "pageSize", label: "Memories per page", min: 10, max: 100, step: 10, defaultValue: 20 },
      { id: "detailWidth", label: "Detail width (pixels)", min: 320, max: 720, step: 20, defaultValue: 420 },
    ],
    focused: { hiddenItems: ["detail.provenance"], density: "compact" },
  },
  sessions: {
    id: "sessions", label: "Sessions",
    sections: [{ id: "table", label: "Sessions table", items: [
      { id: "project", label: "Project" }, { id: "agent", label: "Agent" },
      { id: "session", label: "Session" }, { id: "started", label: "Started" },
      { id: "active", label: "Last active" }, { id: "observations", label: "Observations" },
      { id: "lifecycle", label: "Memory lifecycle" }, { id: "recall", label: "Recall" },
      { id: "context", label: "Context returned" }, { id: "status", label: "Status" },
    ] }],
    counts: [{ id: "rowCount", label: "Sessions shown", min: 10, max: 250, step: 10, defaultValue: 100 }],
    focused: { hiddenItems: ["table.session", "table.started", "table.context"], density: "compact" },
  },
  help: {
    id: "help", label: "Help",
    sections: [
      { id: "toc", label: "Table of contents" },
      { id: "content", label: "Documentation", required: true },
    ],
    focused: { width: "focused" },
  },
};

export interface PagePreference {
  scale: number;
  width: PageWidth;
  density: PageDensity;
  sectionOrder: string[];
  hiddenSections: string[];
  itemOrder: Record<string, string[]>;
  hiddenItems: string[];
  counts: Record<string, number>;
  pinnedProjects: string[];
  excludedProjects: string[];
}

interface StoredPreferences {
  version: 2;
  theme: ThemeMode;
  helpMode: HelpMode;
  pages: Partial<Record<PageId, Partial<PagePreference>>>;
}

function defaultPage(id: PageId): PagePreference {
  const definition = PAGE_DEFINITIONS[id];
  return {
    scale: 100,
    width: "fluid",
    density: "comfortable",
    sectionOrder: definition.sections.map((section) => section.id),
    hiddenSections: [],
    itemOrder: Object.fromEntries(definition.sections.map((section) => [section.id, (section.items ?? []).map((item) => item.id)])),
    hiddenItems: [],
    counts: Object.fromEntries((definition.counts ?? []).map((count) => [count.id, count.defaultValue])),
    pinnedProjects: [],
    excludedProjects: [],
  };
}

function uniqueKnown(values: unknown, known: string[]): string[] {
  if (!Array.isArray(values)) return [];
  const allowed = new Set(known);
  return [...new Set(values.filter((value): value is string => typeof value === "string" && allowed.has(value)))];
}

function strings(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter((value): value is string => typeof value === "string" && value.trim().length > 0).map((value) => value.trim().slice(0, 512)))];
}

function normalizePage(id: PageId, raw?: Partial<PagePreference>): PagePreference {
  const definition = PAGE_DEFINITIONS[id];
  const base = defaultPage(id);
  const sectionIds = definition.sections.map((section) => section.id);
  const storedOrder = uniqueKnown(raw?.sectionOrder, sectionIds);
  const itemOrder: Record<string, string[]> = {};
  for (const section of definition.sections) {
    const ids = (section.items ?? []).map((item) => item.id);
    const saved = uniqueKnown(raw?.itemOrder?.[section.id], ids);
    itemOrder[section.id] = [...saved, ...ids.filter((id) => !saved.includes(id))];
  }
  const required = new Set(definition.sections.filter((section) => section.required).map((section) => section.id));
  const knownItemKeys = definition.sections.flatMap((section) => (section.items ?? []).map((item) => `${section.id}.${item.id}`));
  const counts = { ...base.counts };
  for (const count of definition.counts ?? []) {
    const value = raw?.counts?.[count.id];
    if (typeof value === "number" && Number.isFinite(value)) {
      const stepped = Math.round(value / (count.step ?? 1)) * (count.step ?? 1);
      counts[count.id] = Math.min(count.max, Math.max(count.min, stepped));
    }
  }
  return {
    scale: typeof raw?.scale === "number" && Number.isFinite(raw.scale) ? Math.min(125, Math.max(80, Math.round(raw.scale / 5) * 5)) : 100,
    width: raw?.width === "wide" || raw?.width === "focused" ? raw.width : "fluid",
    density: raw?.density === "compact" ? "compact" : "comfortable",
    sectionOrder: [...storedOrder, ...sectionIds.filter((section) => !storedOrder.includes(section))],
    hiddenSections: uniqueKnown(raw?.hiddenSections, sectionIds).filter((section) => !required.has(section)),
    itemOrder,
    hiddenItems: uniqueKnown(raw?.hiddenItems, knownItemKeys),
    counts,
    pinnedProjects: strings(raw?.pinnedProjects),
    excludedProjects: strings(raw?.excludedProjects),
  };
}

function loadPreferences(): StoredPreferences {
  const fallback: StoredPreferences = { version: 2, theme: "dark", helpMode: "adaptive", pages: {} };
  if (typeof window === "undefined") return fallback;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PREFERENCES_KEY) ?? "null") as (Partial<Omit<StoredPreferences, "version">> & { version?: number }) | null;
    if (!parsed || (parsed.version !== 1 && parsed.version !== 2)) return fallback;
    const theme: ThemeMode = parsed.theme === "light" || parsed.theme === "system" ? parsed.theme : "dark";
    const helpMode: HelpMode = parsed.helpMode === "minimal" || parsed.helpMode === "off" ? parsed.helpMode : "adaptive";
    const pages: StoredPreferences["pages"] = {};
    for (const id of Object.keys(PAGE_DEFINITIONS) as PageId[]) pages[id] = normalizePage(id, parsed.pages?.[id]);
    return { version: 2, theme, helpMode, pages };
  } catch {
    return fallback;
  }
}

function resolvedTheme(theme: ThemeMode): "dark" | "light" {
  if (theme !== "system") return theme;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

interface PreferencesContextValue {
  preferences: StoredPreferences;
  theme: ThemeMode;
  helpMode: HelpMode;
  page(id: PageId): PagePreference;
  updatePage(id: PageId, updater: (current: PagePreference) => PagePreference): void;
  setTheme(theme: ThemeMode): void;
  setHelpMode(mode: HelpMode): void;
  resetPage(id: PageId): void;
  applyFocused(id: PageId): void;
  resetAll(): void;
  drawerPage: PageId | null;
  openDrawer(id: PageId): void;
  closeDrawer(): void;
  projects: Partial<Record<PageId, string[]>>;
  registerProjects(id: PageId, projects: string[]): void;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<StoredPreferences>(loadPreferences);
  const [drawerPage, setDrawerPage] = useState<PageId | null>(null);
  const [projects, setProjects] = useState<Partial<Record<PageId, string[]>>>({});

  useEffect(() => {
    try { window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences)); } catch { /* optional */ }
  }, [preferences]);

  useEffect(() => {
    const apply = () => {
      const resolved = resolvedTheme(preferences.theme);
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.background = resolved === "light" ? "#eef2f8" : "#00072d";
      document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", resolved === "light" ? "#eef2f8" : "#00072d");
    };
    apply();
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    media?.addEventListener("change", apply);
    return () => media?.removeEventListener("change", apply);
  }, [preferences.theme]);

  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === PREFERENCES_KEY) setPreferences(loadPreferences());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);

  const page = useCallback((id: PageId) => normalizePage(id, preferences.pages[id]), [preferences.pages]);
  const updatePage = useCallback((id: PageId, updater: (current: PagePreference) => PagePreference) => {
    setPreferences((current) => ({ ...current, pages: { ...current.pages, [id]: normalizePage(id, updater(normalizePage(id, current.pages[id]))) } }));
  }, []);
  const setTheme = useCallback((theme: ThemeMode) => setPreferences((current) => ({ ...current, theme })), []);
  const setHelpMode = useCallback((helpMode: HelpMode) => setPreferences((current) => ({ ...current, helpMode })), []);
  const resetPage = useCallback((id: PageId) => setPreferences((current) => ({ ...current, pages: { ...current.pages, [id]: defaultPage(id) } })), []);
  const applyFocused = useCallback((id: PageId) => {
    const focused = PAGE_DEFINITIONS[id].focused ?? {};
    setPreferences((current) => ({ ...current, pages: { ...current.pages, [id]: normalizePage(id, { ...defaultPage(id), ...focused }) } }));
  }, []);
  const resetAll = useCallback(() => setPreferences({ version: 2, theme: "dark", helpMode: "adaptive", pages: {} }), []);
  const registerProjects = useCallback((id: PageId, values: string[]) => {
    const next = [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    setProjects((current) => JSON.stringify(current[id] ?? []) === JSON.stringify(next) ? current : { ...current, [id]: next });
  }, []);

  const value = useMemo<PreferencesContextValue>(() => ({
    preferences, theme: preferences.theme, helpMode: preferences.helpMode, page, updatePage, setTheme, setHelpMode, resetPage, applyFocused, resetAll,
    drawerPage, openDrawer: setDrawerPage, closeDrawer: () => setDrawerPage(null), projects, registerProjects,
  }), [preferences, page, updatePage, setTheme, setHelpMode, resetPage, applyFocused, resetAll, drawerPage, projects, registerProjects]);

  return <PreferencesContext.Provider value={value}>{children}{drawerPage ? <CustomizerDrawer pageId={drawerPage} /> : null}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesContextValue {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("PreferencesProvider is missing");
  return value;
}

export function usePagePreferences(id: PageId) {
  const context = usePreferences();
  const preference = context.page(id);
  const sectionVisible = useCallback((section: string) => !preference.hiddenSections.includes(section), [preference.hiddenSections]);
  const itemVisible = useCallback((section: string, item: string) => !preference.hiddenItems.includes(`${section}.${item}`), [preference.hiddenItems]);
  const count = useCallback((key: string, fallback: number) => preference.counts[key] ?? fallback, [preference.counts]);
  return { ...context, preference, sectionVisible, itemVisible, count };
}

export function useRegisterProjects(id: PageId, values: string[]) {
  const { registerProjects } = usePreferences();
  const key = values.join("\u0000");
  useEffect(() => registerProjects(id, values), [registerProjects, id, key]);
}

export function orderProjectNames(values: string[], preference: PagePreference, count: number): string[] {
  const available = new Set(values);
  const pinned = preference.pinnedProjects.filter((project) => available.has(project));
  const excluded = new Set(preference.excludedProjects.filter((project) => !pinned.includes(project)));
  const rest = values.filter((project) => !pinned.includes(project) && !excluded.has(project));
  return [...pinned, ...rest].slice(0, Math.max(count, pinned.length));
}

function reorder(values: string[], from: string, to: string): string[] {
  if (from === to) return values;
  const result = values.filter((value) => value !== from);
  const index = result.indexOf(to);
  result.splice(index < 0 ? result.length : index, 0, from);
  return result;
}

function Toggle({ on, onChange, disabled = false }: { on: boolean; onChange: () => void; disabled?: boolean }) {
  return <button type="button" disabled={disabled} onClick={onChange} aria-pressed={on} className={`relative h-5 w-9 rounded-full border transition ${on ? "border-turq/45 bg-turq/30" : "border-line bg-side"} ${disabled ? "cursor-not-allowed opacity-50" : ""}`}><span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full bg-fg1 transition-all ${on ? "left-[18px]" : "left-0.5"}`} /></button>;
}

function CustomizerDrawer({ pageId }: { pageId: PageId }) {
  const { theme, setTheme, helpMode, setHelpMode, page, updatePage, resetPage, applyFocused, resetAll, closeDrawer, projects } = usePreferences();
  const definition = PAGE_DEFINITIONS[pageId];
  const preference = page(pageId);
  const [dragged, setDragged] = useState<string | null>(null);
  const [projectQuery, setProjectQuery] = useState("");
  const update = (next: Partial<PagePreference>) => updatePage(pageId, (current) => ({ ...current, ...next }));
  const orderedSections = preference.sectionOrder.flatMap((id) => definition.sections.find((section) => section.id === id) ?? []);
  const availableProjects = (projects[pageId] ?? []).filter((project) => project.toLowerCase().includes(projectQuery.toLowerCase()));

  const moveSection = (id: string, offset: number) => {
    const order = [...preference.sectionOrder];
    const index = order.indexOf(id);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    update({ sectionOrder: order });
  };

  return (
    <div className="fixed inset-0 z-[80] flex justify-end bg-black/35" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDrawer(); }}>
      <aside className="flex h-full w-[430px] max-w-[95vw] flex-col border-l border-linestrong bg-surface shadow-[-20px_0_50px_rgba(0,0,0,0.28)]" role="dialog" aria-modal="true" aria-label={`Customize ${definition.label}`}>
        <div className="flex items-start justify-between border-b border-line px-5 py-4">
          <div><div className="font-display text-base font-semibold text-fg1">Customize {definition.label}</div><div className="mt-0.5 text-[11px] text-fg3">Changes save locally and preview immediately.</div></div>
          <button type="button" onClick={closeDrawer} className="rounded-lg p-2 text-fg3 hover:bg-surface2 hover:text-fg1" aria-label="Close customizer"><X size={17} /></button>
        </div>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <section>
            <div className="mb-2 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-fg3">Theme</div>
            <div className="grid grid-cols-3 gap-2">{(["dark", "light", "system"] as ThemeMode[]).map((mode) => <button key={mode} type="button" onClick={() => setTheme(mode)} className={`rounded-lg border px-3 py-2 text-xs capitalize ${theme === mode ? "border-turq/60 bg-turq/10 text-turq" : "border-line bg-side text-fg2"}`}>{mode}</button>)}</div>
          </section>
          <section>
            <div className="mb-2 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-fg3">Context help</div>
            <div className="grid grid-cols-3 gap-2">{(["adaptive", "minimal", "off"] as HelpMode[]).map((mode) => <button key={mode} type="button" onClick={() => setHelpMode(mode)} className={`rounded-lg border px-3 py-2 text-xs capitalize ${helpMode === mode ? "border-turq/60 bg-turq/10 text-turq" : "border-line bg-side text-fg2"}`}>{mode}</button>)}</div>
            <div className="mt-1.5 text-[10px] leading-relaxed text-fg3">Adaptive explains ambiguous labels on hover. Minimal keeps only section help icons. Off leaves the full Help page available.</div>
          </section>
          <section className="grid grid-cols-2 gap-3">
            <label className="text-[11px] text-fg3"><span className="mb-1.5 block font-display font-semibold uppercase tracking-[0.05em]">Page width</span><select value={preference.width} onChange={(event) => update({ width: event.target.value as PageWidth })} className="w-full rounded-lg border border-line bg-side px-3 py-2 text-xs text-fg1"><option value="fluid">Fluid</option><option value="wide">Wide · 1600px</option><option value="focused">Focused · 1280px</option></select></label>
            <label className="text-[11px] text-fg3"><span className="mb-1.5 block font-display font-semibold uppercase tracking-[0.05em]">Density</span><select value={preference.density} onChange={(event) => update({ density: event.target.value as PageDensity })} className="w-full rounded-lg border border-line bg-side px-3 py-2 text-xs text-fg1"><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
          </section>
          <section>
            <div className="mb-1 flex items-center justify-between text-[11px] text-fg3"><span className="font-display font-semibold uppercase tracking-[0.05em]">UI scale</span><span className="font-mono text-fg1">{preference.scale}%</span></div>
            <input type="range" min="80" max="125" step="5" value={preference.scale} onChange={(event) => update({ scale: Number(event.target.value) })} className="w-full accent-turq" />
          </section>
          {(definition.counts ?? []).length > 0 ? <section className="grid grid-cols-2 gap-3">{definition.counts?.map((count) => <label key={count.id} className="text-[11px] text-fg3"><span className="mb-1.5 block font-display font-semibold uppercase tracking-[0.05em]">{count.label}</span><input type="number" min={count.min} max={count.max} step={count.step ?? 1} value={preference.counts[count.id] ?? count.defaultValue} onChange={(event) => update({ counts: { ...preference.counts, [count.id]: Number(event.target.value) } })} className="w-full rounded-lg border border-line bg-side px-3 py-2 font-mono text-xs text-fg1" /></label>)}</section> : null}
          <section>
            <div className="mb-2 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-fg3">Sections and cards</div>
            <div className="space-y-2">{orderedSections.map((section, sectionIndex) => {
              const visible = !preference.hiddenSections.includes(section.id);
              const items = preference.itemOrder[section.id] ?? [];
              return <div key={section.id} draggable onDragStart={() => setDragged(section.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (dragged) update({ sectionOrder: reorder(preference.sectionOrder, dragged, section.id) }); setDragged(null); }} className="rounded-xl border border-line bg-side/60 p-3">
                <div className="flex items-center gap-2"><GripVertical size={14} className="text-fg3" /><div className="min-w-0 flex-1 truncate font-display text-xs font-semibold text-fg1">{section.label}</div><button type="button" onClick={() => moveSection(section.id, -1)} disabled={sectionIndex === 0} className="p-1 text-fg3 disabled:opacity-25" aria-label={`Move ${section.label} up`}><ChevronUp size={13} /></button><button type="button" onClick={() => moveSection(section.id, 1)} disabled={sectionIndex === orderedSections.length - 1} className="p-1 text-fg3 disabled:opacity-25" aria-label={`Move ${section.label} down`}><ChevronDown size={13} /></button><Toggle on={visible} disabled={section.required} onChange={() => update({ hiddenSections: visible ? [...preference.hiddenSections, section.id] : preference.hiddenSections.filter((id) => id !== section.id) })} /></div>
                {items.length > 0 ? <div className="mt-2 space-y-1 border-t border-line pt-2">{items.map((itemId) => { const item = section.items?.find((candidate) => candidate.id === itemId); if (!item) return null; const key = `${section.id}.${item.id}`; const itemOn = !preference.hiddenItems.includes(key); return <div key={key} className="flex items-center gap-2 py-1 pl-5"><span className="min-w-0 flex-1 truncate text-[11px] text-fg2">{item.label}</span><Toggle on={itemOn} onChange={() => update({ hiddenItems: itemOn ? [...preference.hiddenItems, key] : preference.hiddenItems.filter((id) => id !== key) })} /></div>; })}</div> : null}
              </div>;
            })}</div>
          </section>
          {definition.projects ? <section>
            <div className="mb-2 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-fg3">Project cards</div>
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-line bg-side px-3 py-2"><Search size={13} className="text-fg3" /><input value={projectQuery} onChange={(event) => setProjectQuery(event.target.value)} placeholder="Find a project…" className="w-full bg-transparent text-xs text-fg1 outline-none placeholder:text-fg3" /></div>
            <div className="max-h-56 space-y-1 overflow-y-auto">{availableProjects.map((project) => { const pinned = preference.pinnedProjects.includes(project); const excluded = preference.excludedProjects.includes(project); return <div key={project} className="flex items-center gap-2 rounded-lg border border-line bg-side/55 px-3 py-2"><span className="min-w-0 flex-1 truncate text-[11px] text-fg2" title={project}>{project}</span><button type="button" onClick={() => update({ pinnedProjects: pinned ? preference.pinnedProjects.filter((value) => value !== project) : [...preference.pinnedProjects, project], excludedProjects: preference.excludedProjects.filter((value) => value !== project) })} className={`rounded px-2 py-1 text-[9px] font-semibold uppercase ${pinned ? "bg-turq/15 text-turq" : "bg-surface2 text-fg3"}`}>{pinned ? "Pinned" : "Pin"}</button><button type="button" onClick={() => update({ excludedProjects: excluded ? preference.excludedProjects.filter((value) => value !== project) : [...preference.excludedProjects, project], pinnedProjects: preference.pinnedProjects.filter((value) => value !== project) })} className={`rounded px-2 py-1 text-[9px] font-semibold uppercase ${excluded ? "bg-bad/15 text-bad" : "bg-surface2 text-fg3"}`}>{excluded ? "Hidden" : "Hide"}</button></div>; })}</div>
          </section> : null}
        </div>
        <div className="border-t border-line p-4">
          <div className="mb-3 flex items-center gap-1.5 text-[10px] text-ok"><Check size={12} /> Saved locally</div>
          <div className="grid grid-cols-2 gap-2"><button type="button" onClick={() => resetPage(pageId)} className="rounded-lg border border-line bg-side px-3 py-2 text-xs text-fg2 hover:text-fg1">Default</button><button type="button" onClick={() => applyFocused(pageId)} className="rounded-lg border border-peri/35 bg-peri/10 px-3 py-2 text-xs text-peri">Focused</button></div>
          <button type="button" onClick={() => { if (window.confirm("Reset every Agent007Memory display preference?")) resetAll(); }} className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[10px] text-fg3 hover:bg-bad/10 hover:text-bad"><RotateCcw size={12} /> Reset all pages and theme</button>
        </div>
      </aside>
    </div>
  );
}
