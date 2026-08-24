import type { ReactNode } from "react";
import type { MetricsTick } from "../../shared/types";
import { fmtMs, fmtNum, fmtUptime } from "../lib/format";
import { StatTile } from "./ui";
import { useLocation } from "react-router-dom";
import { usePagePreferences, type PageId } from "../lib/preferences";

function latencyValue(ms: number): ReactNode {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms < 1000) {
    return (
      <>
        {Math.round(ms)}
        <span className="text-sm font-semibold text-fg3">ms</span>
      </>
    );
  }
  return fmtMs(ms);
}

export function MetricsTiles({ tick, empty }: { tick: MetricsTick | null; empty?: boolean }) {
  const location = useLocation();
  const pageId = ({ "/": "dashboard", "/overview": "overview", "/projects": "projects", "/llm": "llm" } as Record<string, PageId>)[location.pathname] ?? "dashboard";
  const { preference, itemVisible } = usePagePreferences(pageId);
  const heap = tick?.health?.heapMb;
  const uptime = fmtUptime(tick?.health?.uptimeSec ?? null);
  const tiles: Record<string, ReactNode> = {
    memories: <StatTile
        key="memories"
        label="Memories"
        value={fmtNum(tick?.memoriesTotal)}
        sub={
          empty || tick?.memoriesTotal == null ? undefined : (
            <span style={{ color: "var(--color-turq-bright)" }}>durable knowledge total</span>
          )
        }
        dim={empty}
      />,
    sessions: <StatTile
        key="sessions"
        label="Sessions"
        value={fmtNum(tick?.sessionsTotal)}
        sub={
          empty || tick?.sessionsActive == null
            ? undefined
            : `${fmtNum(tick.sessionsActive)} active now`
        }
        dim={empty}
      />,
    observations: <StatTile
        key="observations"
        label="Observations"
        value={fmtNum(tick?.obsToday)}
        sub={empty || tick?.obsToday == null ? undefined : "today"}
        dim={empty}
      />,
    requests: <StatTile
        key="requests"
        label="Requests / min"
        value={fmtNum(tick?.reqPerMin ?? 0)}
        sub={
          empty
            ? undefined
            : (tick?.errLast15m ?? 0) === 0
              ? "no errors last 15 min"
              : `${fmtNum(tick?.errLast15m)} errors last 15 min`
        }
        dim={empty}
      />,
    latency: <StatTile
        key="latency"
        label="p95 latency"
        value={latencyValue(tick?.p95 ?? 0)}
        sub={empty ? undefined : `p50 ${fmtMs(tick?.p50 ?? 0)}`}
        dim={empty}
      />,
    uptime: <StatTile
        key="uptime"
        label="Uptime"
        value={uptime}
        sub={empty || heap == null ? undefined : `heap ${Math.round(heap)} MB`}
        dim={empty && uptime === "—"}
      />,
  };
  const order = preference.itemOrder.metrics ?? Object.keys(tiles);
  const visible = order.filter((id) => itemVisible("metrics", id) && tiles[id]);
  return (
    <div className="grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-6">
      {visible.map((id) => tiles[id])}
    </div>
  );
}
