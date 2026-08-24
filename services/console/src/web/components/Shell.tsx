// App frame: persistent collapsible sidebar, scrollable routed main content,
// and the SystemBar pinned below it.

import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BrainCircuit,
  ChartColumn,
  Clock,
  Database,
  FolderKanban,
  PanelLeftClose,
  PanelLeftOpen,
  PanelsTopLeft,
  Users,
  Wrench,
  CircleHelp,
  Minus,
  Moon,
  Plus,
  Settings2,
  Sun,
} from "lucide-react";
import { useLive } from "../lib/ws";
import { SCALE_MAX, SCALE_MIN, SCALE_STEP, usePagePreferences, usePreferences, type PageId } from "../lib/preferences";
import SystemBar from "./SystemBar";

const SIDEBAR_COLLAPSED_KEY = "agent007memory.sidebar.collapsed";

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/overview", label: "Overview", icon: PanelsTopLeft },
  { to: "/", label: "Dashboard", icon: ChartColumn, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/llm", label: "LLM Calls", icon: BrainCircuit },
  { to: "/reports", label: "Reports", icon: ChartColumn },
  { to: "/operations", label: "Operations", icon: Wrench },
  { to: "/requests", label: "Live Requests", icon: Activity },
  { to: "/timeline", label: "Timeline", icon: Clock },
  { to: "/memories", label: "Memories", icon: Database },
  { to: "/sessions", label: "Sessions", icon: Users },
  { to: "/help", label: "Help", icon: CircleHelp },
];

const PAGE_BY_PATH: Record<string, PageId> = {
  "/": "dashboard", "/overview": "overview", "/projects": "projects", "/llm": "llm",
  "/reports": "reports", "/operations": "operations", "/requests": "requests",
  "/timeline": "timeline", "/memories": "memories", "/sessions": "sessions", "/help": "help",
};

function BrandMark({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={`flex items-center ${collapsed ? "justify-center" : "gap-2.5 px-1.5"}`}>
      <img
        src="/assets/agent007memory-mark.png"
        alt=""
        aria-hidden="true"
        className="w-[34px] h-[34px] object-contain flex-none"
      />
      {collapsed ? (
        <span className="sr-only">Agent007Memory Intelligence Console</span>
      ) : (
        <div>
          <div className="font-display font-bold text-sm text-fg1 tracking-[-0.01em] leading-tight">
            Agent007Memory
          </div>
          <div className="font-display font-semibold text-[9px] tracking-[0.12em] text-turq leading-tight mt-0.5">
            INTELLIGENCE CONSOLE
          </div>
        </div>
      )}
    </div>
  );
}

function StatusCard({ collapsed }: { collapsed: boolean }) {
  const { wsConnected, upstreamOk } = useLive();
  const live = wsConnected && upstreamOk;
  const detail = !wsConnected ? "console unreachable" : upstreamOk ? "ws connected" : "upstream down";

  if (collapsed) {
    return (
      <div
        className="flex h-10 items-center justify-center rounded-[10px] border"
        title={`${live ? "Live" : "Offline"} · ${detail}`}
        aria-label={`${live ? "Live" : "Offline"}: ${detail}`}
        style={
          live
            ? { borderColor: "var(--color-line)", background: "rgb(var(--rgb-surface) / 0.6)" }
            : { borderColor: "rgba(194,64,40,0.4)", background: "rgba(194,64,40,0.08)" }
        }
      >
        <span
          className="h-2 w-2 rounded-full"
          style={
            live
              ? { background: "var(--color-turq)", boxShadow: "0 0 0 3px rgba(83,226,221,0.18)" }
              : { background: "var(--color-bad)", boxShadow: "0 0 0 3px rgba(194,64,40,0.2)" }
          }
        />
      </div>
    );
  }

  return (
    <div
      className="rounded-[10px] p-3 border"
      style={
        live
          ? { borderColor: "var(--color-line)", background: "rgb(var(--rgb-surface) / 0.6)" }
          : { borderColor: "rgba(194,64,40,0.4)", background: "rgba(194,64,40,0.08)" }
      }
    >
      <div className="flex items-center gap-[7px]">
        <span
          className="w-2 h-2 rounded-full flex-none"
          style={
            live
              ? { background: "var(--color-turq)", boxShadow: "0 0 0 3px rgba(83,226,221,0.18)" }
              : { background: "var(--color-bad)", boxShadow: "0 0 0 3px rgba(194,64,40,0.2)" }
          }
        />
        <span
          className="font-display font-semibold text-[11px] tracking-[0.06em]"
          style={{ color: live ? "var(--color-fg1)" : "var(--color-bad-bright)" }}
        >
          {live ? "LIVE" : "OFFLINE"}
        </span>
        <span className="text-[11px] text-fg3">{detail}</span>
      </div>
      <div className="text-[11px] text-fg3 mt-1.5 leading-normal">
        Agent007Memory
        <br />
        proxy on 127.0.0.1:3111
      </div>
    </div>
  );
}

// Zoom the console applies to itself, in 5% steps, persisted with the rest of
// the preferences.
//
// Not the browser's zoom, which is what people reach for otherwise: browser
// zoom shrinks the VIEWPORT, so the app frame gets shorter and the SystemBar
// pinned at its bottom goes off the end of the window. This scales the content
// inside a frame that stays exactly as tall as the window, so nothing can fall
// off it however far you zoom in.
function ZoomStepper({ collapsed }: { collapsed: boolean }) {
  const { scale, setScale, nudgeScale } = usePreferences();
  const button = "flex h-7 w-7 flex-none items-center justify-center rounded-md border border-line bg-surface/60 text-fg3 transition-colors hover:border-turq/40 hover:text-turq disabled:opacity-35 disabled:hover:border-line disabled:hover:text-fg3";

  if (collapsed) {
    return (
      <div className="mb-1 flex flex-col items-center gap-1">
        <button type="button" className={button} onClick={() => nudgeScale(SCALE_STEP)} disabled={scale >= SCALE_MAX} aria-label="Zoom in" title={`Zoom in (${scale}%)`}>
          <Plus size={13} />
        </button>
        <button type="button" onClick={() => setScale(100)} className="font-mono text-[10px] text-fg3 hover:text-turq" aria-label={`Zoom ${scale}%, click to reset`} title="Reset zoom to 100%">
          {scale}
        </button>
        <button type="button" className={button} onClick={() => nudgeScale(-SCALE_STEP)} disabled={scale <= SCALE_MIN} aria-label="Zoom out" title={`Zoom out (${scale}%)`}>
          <Minus size={13} />
        </button>
      </div>
    );
  }

  return (
    <div className="mb-1 flex items-center gap-1">
      <button type="button" className={button} onClick={() => nudgeScale(-SCALE_STEP)} disabled={scale <= SCALE_MIN} aria-label="Zoom out" title="Zoom out 5%">
        <Minus size={13} />
      </button>
      <button
        type="button"
        onClick={() => setScale(100)}
        className="flex h-7 flex-1 items-center justify-center rounded-md border border-line bg-surface/60 font-mono text-[11px] text-fg2 transition-colors hover:border-turq/40 hover:text-turq"
        aria-label={`Zoom ${scale} percent, click to reset to 100 percent`}
        title="Click to reset to 100%"
      >
        {scale}%
      </button>
      <button type="button" className={button} onClick={() => nudgeScale(SCALE_STEP)} disabled={scale >= SCALE_MAX} aria-label="Zoom in" title="Zoom in 5%">
        <Plus size={13} />
      </button>
    </div>
  );
}

export default function Shell(): JSX.Element {
  const location = useLocation();
  const pageId = PAGE_BY_PATH[location.pathname] ?? "overview";
  const { preference } = usePagePreferences(pageId);
  const { theme, setTheme, openDrawer, scale } = usePreferences();
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    } catch {
      // Storage may be unavailable in privacy-restricted browser contexts.
    }
  }, [collapsed]);

  return (
    // The zoom lives HERE, on the frame, not on the routed content: everything
    // chrome included scales together, and because the frame is sized in
    // inverse-scaled viewport units it still occupies exactly one screen. Zoom
    // to 150% and the SystemBar is still on screen -- it is the content inside
    // that scrolls, which is the whole difference from browser zoom.
    <div
      className="flex overflow-hidden bg-app"
      style={{
        zoom: scale / 100,
        width: `${100 / (scale / 100)}vw`,
        height: `${100 / (scale / 100)}vh`,
      }}
    >
      <aside
        className={`flex flex-none flex-col overflow-y-auto border-r border-line bg-side pb-4 pt-5 transition-[width,padding] duration-200 ${
          collapsed ? "w-[72px] px-2" : "w-[232px] px-3.5"
        }`}
        data-collapsed={collapsed}
      >
        <div className={`mb-[18px] flex ${collapsed ? "flex-col items-center gap-2" : "items-start justify-between gap-2"}`}>
          <BrandMark collapsed={collapsed} />
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-line bg-surface/60 text-fg3 transition-colors hover:border-turq/40 hover:text-turq"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            data-testid="sidebar-toggle"
          >
            {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={`flex items-center rounded-lg py-[9px] font-display text-[13px] font-medium no-underline ${
                collapsed ? "justify-center px-0" : "gap-2.5 px-3"
              }`}
              aria-label={collapsed ? label : undefined}
              title={collapsed ? label : undefined}
              style={({ isActive }) =>
                isActive
                  ? {
                      background: "rgba(138,128,240,0.14)",
                      color: "var(--color-fg1)",
                      boxShadow: "inset 2px 0 0 #53E2DD",
                    }
                  : { color: "var(--color-fg2)" }
              }
            >
              <Icon className="w-4 h-4 flex-none" strokeWidth={2} />
              {collapsed ? <span className="sr-only">{label}</span> : label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1" />
        <div className={`mb-2 grid gap-1 ${collapsed ? "grid-cols-1" : "grid-cols-2"}`}>
          <button
            type="button"
            onClick={() => openDrawer(pageId)}
            className={`flex h-9 items-center justify-center rounded-lg border border-line bg-surface/60 text-fg3 transition-colors hover:border-turq/40 hover:text-turq ${collapsed ? "px-0" : "gap-2 px-2"}`}
            aria-label={`Customize ${pageId} page`}
            title={`Customize ${pageId} page`}
            data-testid="customize-page"
          >
            <Settings2 size={14} />{collapsed ? <span className="sr-only">Customize</span> : <span className="text-[10px] font-semibold">Customize</span>}
          </button>
          <button
            type="button"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            className={`flex h-9 items-center justify-center rounded-lg border border-line bg-surface/60 text-fg3 transition-colors hover:border-peri/40 hover:text-peri ${collapsed ? "px-0" : "gap-2 px-2"}`}
            aria-label={theme === "light" ? "Use dark theme" : "Use light theme"}
            title={theme === "light" ? "Use dark theme" : "Use light theme"}
            data-testid="theme-toggle"
          >
            {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}{collapsed ? null : <span className="text-[10px] font-semibold">Theme</span>}
          </button>
        </div>
        <ZoomStepper collapsed={collapsed} />
        <StatusCard collapsed={collapsed} />
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 min-h-0 overflow-y-auto px-8 pt-7 pb-5">
          <div
            className="page-canvas"
            data-page={pageId}
            data-density={preference.density}
            style={{
              maxWidth: preference.width === "wide" ? 1600 : preference.width === "focused" ? 1280 : undefined,
              marginInline: "auto",
            }}
          >
            <Outlet />
          </div>
        </div>
        <div className="flex-none px-8 pb-4">
          <SystemBar />
        </div>
      </main>
    </div>
  );
}
