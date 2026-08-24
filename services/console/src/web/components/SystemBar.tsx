// Slim dependency-health toolbar pinned to the bottom of <main>.
// One Dot + label per tick.deps entry, "checked Xs ago" on the right —
// or the red no-response message when upstream is unreachable.

import { useEffect, useState } from "react";
import { useLive } from "../lib/ws";
import { fmtClock, timeAgo } from "../lib/format";
import { Dot } from "./ui";

/** Re-render every `intervalMs` so relative times stay fresh. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function SystemBar(): JSX.Element {
  const { tick, upstreamOk } = useLive();
  useNow(1_000);

  const deps = tick?.deps ?? [];

  return (
    <div
      className="flex items-center gap-3.5 px-3.5 py-[9px] rounded-[10px] border font-display font-medium text-[11px] text-fg3 overflow-x-auto"
      style={{
        background: "rgba(4,8,31,0.75)",
        borderColor: upstreamOk ? "var(--color-line)" : "rgba(194,64,40,0.35)",
      }}
    >
      <span className="font-semibold tracking-[0.06em] text-fg2 flex-none">SYSTEM</span>
      {deps.map((d) => (
        <span
          key={d.id}
          className="inline-flex items-center gap-[5px] whitespace-nowrap flex-none"
          style={d.state === "down" ? { color: "var(--color-bad-bright)" } : undefined}
          title={d.detail ?? undefined}
        >
          <Dot state={d.state} />
          {d.label}
          {d.detail ? <span> · {d.detail}</span> : null}
        </span>
      ))}
      {deps.length === 0 ? <span className="text-fg3">no health data yet</span> : null}
      <span className="flex-1 min-w-4" />
      <span
        className="font-mono font-normal whitespace-nowrap flex-none"
        style={!upstreamOk && tick ? { color: "var(--color-bad-bright)" } : undefined}
      >
        {tick
          ? upstreamOk
            ? `checked ${timeAgo(tick.ts)}`
            : `no response since ${fmtClock(tick.ts)}`
          : "waiting for first check…"}
      </span>
    </div>
  );
}
