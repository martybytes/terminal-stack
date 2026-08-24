// Dashboard: live stat tiles, four chart cards, and a request ticker.
// Three states, mirroring the Main / DashboardEmpty / DashboardOffline mockups:
//   empty   — no tick yet, or no traffic captured (hero with first steps)
//   offline — tick present but upstream unreachable (amber banner, dimmed data)
//   live    — the full chart grid

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Activity, RefreshCw, TriangleAlert } from "lucide-react";
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, IntentPill, MethodPill, PageHeader, Pill, StatusPill } from "../components/ui";
import { MetricsTiles } from "../components/MetricsTiles";
import { useLive } from "../lib/ws";
import { fmtClock, fmtMs, timeAgo } from "../lib/format";
import type { MetricsTick, RequestRecord } from "../../shared/types";
import { requestIntent } from "../../shared/requestIntent";
import { usePagePreferences } from "../lib/preferences";

// ---------------------------------------------------------------- helpers

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function fmtHm(t: number): string {
  const d = new Date(t);
  const p = (n: number) => (n < 10 ? `0${n}` : String(n));
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

const TOOLTIP_PROPS = {
  contentStyle: {
    background: "var(--color-tooltip)",
    border: "1px solid rgb(var(--rgb-fg) / 0.16)",
    borderRadius: 8,
    fontSize: 11,
    color: "var(--color-fg2)",
    boxShadow: "0 8px 20px rgba(0,7,45,0.5)",
    padding: "8px 10px",
  },
  labelStyle: {
    color: "var(--color-fg1)",
    fontFamily: "Montserrat, 'Helvetica Neue', Arial, sans-serif",
    fontWeight: 600,
  },
  itemStyle: { color: "var(--color-fg2)", padding: 0 },
} as const;

const AXIS_TICK = { fontSize: 10, fill: "var(--color-fg3)" } as const;

function Legend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div className="flex items-center gap-3.5 text-[11px] text-fg3">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-[5px]">
          <span className="w-2 h-2 rounded-[2px] inline-block" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

function ChartCard({
  title,
  legend,
  children,
}: {
  title: string;
  legend?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="p-4 flex flex-col gap-2 h-[230px] min-w-0">
      <div className="flex items-center justify-between gap-2">
        <div className="font-display font-semibold text-[13px] text-fg1">{title}</div>
        {legend}
      </div>
      <div className="flex-1 min-h-0">{children}</div>
    </Card>
  );
}

// ---------------------------------------------------------------- ticker

function Ticker({ requests, streaming }: { requests: RequestRecord[]; streaming: boolean }) {
  const rows = requests.slice(0, 9);
  return (
    <Card className="p-4 flex flex-col min-h-0 min-w-0">
      <div className="flex items-center justify-between mb-1.5">
        <div className="font-display font-semibold text-[13px] text-fg1">Live requests</div>
        <span
          className="inline-flex items-center gap-[5px] text-[11px]"
          style={{ color: streaming ? "var(--color-turq-bright)" : "var(--color-fg3)" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: streaming ? "var(--color-turq)" : "var(--color-na)" }}
          />
          {streaming ? "streaming" : "paused"}
        </span>
      </div>
      <div className="flex-1 overflow-hidden">
        {rows.length === 0 ? (
          <div className="text-xs text-fg3 py-4">waiting for requests…</div>
        ) : (
          rows.map((r, i) => (
            <div
              key={r.id}
              className={`flex items-center gap-2 py-2 ${
                i === rows.length - 1 ? "" : "border-b border-line"
              }`}
            >
              <span className="font-mono text-xs text-fg3 flex-none">{fmtClock(r.ts)}</span>
              <MethodPill method={r.method} />
              <span
                className="w-[82px] flex-none truncate font-display text-[10px] font-semibold text-fg1"
                title={r.project?.trim() || "Global request (no project scope)"}
              >
                {r.project?.trim() || "Global"}
              </span>
              <IntentPill intent={requestIntent(r)} />
              <span className="font-mono text-xs text-fg2 flex-1 truncate" title={r.path}>
                {r.path}
              </span>
              <StatusPill status={r.status} />
              <span className="font-mono text-xs text-fg3 w-[52px] text-right flex-none">
                {fmtMs(r.durMs)}
              </span>
            </div>
          ))
        )}
      </div>
      <div className="border-t border-line pt-2.5 mt-1.5">
        <Link
          to="/requests"
          className="font-display font-semibold text-xs text-turq hover:underline"
        >
          Open Live Requests →
        </Link>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- empty state

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <div className="flex gap-3 items-start">
      <span
        className="w-[22px] h-[22px] flex-none rounded-full flex items-center justify-center font-display font-semibold text-[11px]"
        style={{ background: "rgba(83,226,221,0.14)", color: "#8FEDEA" }}
      >
        {n}
      </span>
      <div className="text-[13px] text-fg2 leading-normal">{children}</div>
    </div>
  );
}

function EmptyDashboard({ tick }: { tick: MetricsTick | null }) {
  return (
    <div className="flex flex-col gap-5 min-h-full">
      <PageHeader
        title="Dashboard"
        subtitle="agentmemory via console proxy · waiting for first traffic"
      />
      <MetricsTiles tick={tick} empty />
      <Card className="relative flex-1 min-h-[440px] flex items-center overflow-hidden">
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage: "url('/assets/agent007memory-empty-state.webp')",
            opacity: 0.58,
          }}
        />
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(90deg, rgba(11,18,56,0.98) 0%, rgba(11,18,56,0.9) 39%, rgba(11,18,56,0.22) 72%, rgba(11,18,56,0.1) 100%)",
          }}
        />
        <div className="relative max-w-[540px] flex flex-col gap-[18px] py-10 px-8">
          <div
            className="w-[52px] h-[52px] rounded-[14px] flex items-center justify-center"
            style={{
              background: "rgba(83,226,221,0.10)",
              border: "1px solid rgba(83,226,221,0.3)",
            }}
          >
            <Activity className="w-[26px] h-[26px]" style={{ color: "var(--color-turq)" }} strokeWidth={1.8} />
          </div>
          <div>
            <div className="font-display font-semibold text-[19px] tracking-[-0.01em] text-fg1">
              Listening on 127.0.0.1:3111
            </div>
            <div className="text-sm text-fg2 mt-1.5 leading-[1.55]">
              The proxy is up and agentmemory is healthy behind it. The first call from a hook,
              MCP client, or the stock viewer will appear here the moment it happens.
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <Step n={1}>
              Start a Claude Code session in a project with agentmemory hooks — observations begin
              flowing automatically.
            </Step>
            <Step n={2}>
              Or send a test call:{" "}
              <code
                className="font-mono text-xs px-1.5 py-0.5 rounded"
                style={{ background: "rgb(var(--rgb-side) / 0.8)" }}
              >
                curl 127.0.0.1:3111/agentmemory/livez
              </code>
            </Step>
            <Step n={3}>
              Charts fill as traffic accrues — the first minute bucket appears within 60 seconds.
            </Step>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- offline state

const GHOST_BAR_HEIGHTS = [40, 55, 35, 62, 48, 70, 52, 66];

function OfflineDashboard({ tick }: { tick: MetricsTick }) {
  return (
    <div className="flex flex-col gap-4 min-h-full">
      <div
        className="flex items-center gap-3 rounded-[10px] px-4 py-3"
        style={{
          background: "rgba(187,132,18,0.12)",
          border: "1px solid rgba(187,132,18,0.45)",
        }}
      >
        <RefreshCw
          className="w-[18px] h-[18px] flex-none animate-spin [animation-duration:3s]"
          style={{ color: "#E4B24C" }}
        />
        <div className="flex-1 text-[13px]">
          <span className="font-display font-semibold" style={{ color: "#E4B24C" }}>
            Reconnecting to agentmemory
          </span>
          <span className="text-fg2">
            {" "}
            — retrying automatically. The proxy is returning 502 while upstream is unreachable.
          </span>
        </div>
      </div>

      <PageHeader
        title="Dashboard"
        subtitle={`showing last data from ${fmtClock(tick.ts)} · stream paused`}
        right={<Pill tone="bad">UPSTREAM DOWN</Pill>}
      />

      <div className="opacity-[0.45] pointer-events-none">
        <MetricsTiles tick={tick} />
      </div>

      <div className="grid grid-cols-[2fr_1fr] gap-3.5 flex-1 min-h-[400px]">
        <Card className="relative flex items-center justify-center overflow-hidden">
          <div className="absolute inset-0 opacity-[0.18] flex items-end gap-2.5 p-10">
            {GHOST_BAR_HEIGHTS.map((h, i) => (
              <div
                key={i}
                className="w-4 rounded-[3px]"
                style={{ height: `${h}%`, background: "var(--color-s1)" }}
              />
            ))}
          </div>
          <div className="relative max-w-[440px] text-center flex flex-col items-center gap-3.5 p-8">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{
                background: "rgba(194,64,40,0.12)",
                border: "1px solid rgba(194,64,40,0.4)",
              }}
            >
              <TriangleAlert className="w-6 h-6" style={{ color: "var(--color-bad-bright)" }} strokeWidth={1.8} />
            </div>
            <div className="font-display font-semibold text-[17px] text-fg1">
              Charts paused — upstream unreachable
            </div>
            <div className="text-[13px] text-fg2 leading-[1.55]">
              The console keeps 24 hours of chart history in memory. Charts resume automatically
              when agentmemory answers again.
            </div>
          </div>
        </Card>

        <Card className="p-4 flex flex-col gap-3">
          <div className="font-display font-semibold text-[13px] text-fg1">Isolate the fault</div>
          <div className="text-[13px] text-fg2 leading-[1.55]">
            The bypass port skips this proxy and hits agentmemory directly. If it answers, the
            console is the problem; if it doesn't, upstream is down.
          </div>
          <div
            className="font-mono text-xs rounded-lg px-3 py-2.5 text-fg2 border border-line"
            style={{ background: "rgb(var(--rgb-side) / 0.8)" }}
          >
            curl 127.0.0.1:3110/agentmemory/livez
          </div>
          <div className="text-xs text-fg3 leading-[1.55]">Container status:</div>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-[7px] h-[7px] rounded-full" style={{ background: "var(--color-ok)" }} />
              <span className="font-mono">console</span>
              <span className="text-fg3">healthy · this app</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-[7px] h-[7px] rounded-full" style={{ background: "var(--color-bad)" }} />
              <span className="font-mono">agentmemory</span>
              <span className="text-fg3">no response since {fmtClock(tick.ts)}</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- live state

interface ReqBar {
  t: number;
  label: string;
  ok: number;
  err4: number;
  err5: number;
}

export default function Dashboard(): JSX.Element {
  const { sectionVisible } = usePagePreferences("dashboard");
  const { tick, snapshot, requests, observations, upstreamOk, wsConnected, paused } = useLive();
  useNow(1_000);

  // Requests/min: 5s buckets from the last 15 minutes, aggregated per 30s.
  const reqBars = useMemo<ReqBar[]>(() => {
    const src = snapshot?.buckets5s ?? [];
    const out: ReqBar[] = [];
    for (const b of src) {
      const t = Math.floor(b.t / 30_000) * 30_000;
      const last = out[out.length - 1];
      if (last && last.t === t) {
        last.ok += b.ok;
        last.err4 += b.err4;
        last.err5 += b.err5;
      } else {
        out.push({ t, label: fmtHm(t), ok: b.ok, err4: b.err4, err5: b.err5 });
      }
    }
    return out.slice(-30);
  }, [snapshot]);

  const latencyData = useMemo(
    () =>
      (snapshot?.buckets5s ?? []).map((b) => ({
        label: fmtHm(b.t),
        p50: b.p50,
        p95: b.p95,
      })),
    [snapshot],
  );

  const obsData = useMemo(
    () =>
      (snapshot?.obsBuckets1m ?? []).slice(-15).map((b) => ({
        label: fmtHm(b.t),
        raw: b.raw,
        compressed: b.compressed,
      })),
    [snapshot],
  );

  const healthData = useMemo(
    () =>
      (snapshot?.healthSeries ?? []).slice(-120).map((h) => ({
        label: fmtHm(h.ts),
        heapMb: h.heapMb,
        lagMs: h.lagMs,
      })),
    [snapshot],
  );

  const hasTraffic =
    requests.length > 0 || reqBars.some((b) => b.ok + b.err4 + b.err5 > 0);

  if (tick && !upstreamOk) return <OfflineDashboard tick={tick} />;
  if (!tick || !hasTraffic) return <EmptyDashboard tick={tick} />;

  const lastEventTs = requests[0]?.ts ?? observations[0]?.ts ?? tick.ts;
  const latestHeap = tick.health?.heapMb ?? healthData[healthData.length - 1]?.heapMb ?? null;
  const latestLag = tick.health?.lagMs ?? healthData[healthData.length - 1]?.lagMs ?? null;

  return (
    <div className="flex flex-col gap-5 min-h-full">
      <PageHeader
        title="Dashboard"
        subtitle="agentmemory via console proxy · updating live"
        right={
          <>
            <Pill tone="ok">UPSTREAM HEALTHY</Pill>
            <span className="text-xs text-fg3">last event {timeAgo(lastEventTs)}</span>
          </>
        }
      />

      {sectionVisible("metrics") ? <MetricsTiles tick={tick} /> : null}

      <div className={`grid gap-3.5 ${sectionVisible("ticker") ? "grid-cols-[2fr_1fr]" : "grid-cols-1"}`}>
        <div className="grid grid-cols-2 gap-3.5 min-w-0">
          {sectionVisible("requestsChart") ? <ChartCard
            title="Requests per minute"
            legend={
              <Legend
                items={[
                  { color: "var(--color-s1)", label: "2xx" },
                  { color: "var(--color-warn)", label: "4xx" },
                  { color: "var(--color-bad)", label: "5xx" },
                ]}
              />
            }
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={reqBars} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  tick={AXIS_TICK}
                  interval="preserveStartEnd"
                  minTickGap={48}
                  height={16}
                />
                <YAxis hide domain={[0, "auto"]} />
                <Tooltip {...TOOLTIP_PROPS} cursor={{ fill: "rgb(var(--rgb-fg) / 0.05)" }} />
                <Bar dataKey="ok" name="2xx" stackId="s" fill="var(--color-s1)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                <Bar dataKey="err4" name="4xx" stackId="s" fill="var(--color-warn)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                <Bar dataKey="err5" name="5xx" stackId="s" fill="var(--color-bad)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard> : null}

          {sectionVisible("observationsChart") ? <ChartCard
            title="Observations per minute"
            legend={
              <Legend
                items={[
                  { color: "var(--color-s1)", label: "raw" },
                  { color: "var(--color-peri)", label: "compressed" },
                ]}
              />
            }
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={obsData} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  tick={AXIS_TICK}
                  interval="preserveStartEnd"
                  minTickGap={48}
                  height={16}
                />
                <YAxis hide domain={[0, "auto"]} />
                <Tooltip {...TOOLTIP_PROPS} cursor={{ stroke: "rgb(var(--rgb-fg) / 0.16)" }} />
                <Line type="monotone" dataKey="raw" name="raw" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="compressed" name="compressed" stroke="var(--color-peri)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard> : null}

          {sectionVisible("latencyChart") ? <ChartCard
            title="Proxy latency (ms)"
            legend={
              <Legend
                items={[
                  { color: "#6ECBD2", label: "p95" },
                  { color: "var(--color-s1)", label: "p50" },
                ]}
              />
            }
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={latencyData} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  tick={AXIS_TICK}
                  interval="preserveStartEnd"
                  minTickGap={48}
                  height={16}
                />
                <YAxis hide domain={[0, "auto"]} />
                <Tooltip {...TOOLTIP_PROPS} cursor={{ stroke: "rgb(var(--rgb-fg) / 0.16)" }} />
                <Line type="monotone" dataKey="p95" name="p95" stroke="#6ECBD2" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="p50" name="p50" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard> : null}

          {sectionVisible("processHealth") ? <Card className="p-4 flex flex-col gap-2 h-[230px] min-w-0">
            <div className="font-display font-semibold text-[13px] text-fg1">
              Upstream process health
            </div>
            <div className="grid grid-cols-2 gap-3.5 flex-1 min-h-0">
              <div className="flex flex-col gap-1 min-h-0">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-fg3">Heap (MB)</span>
                  <span style={{ color: "var(--color-turq-bright)" }}>
                    {latestHeap != null ? Math.round(latestHeap) : "—"}
                  </span>
                </div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={healthData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                      <Tooltip {...TOOLTIP_PROPS} cursor={{ stroke: "rgb(var(--rgb-fg) / 0.16)" }} />
                      <Line type="monotone" dataKey="heapMb" name="heap MB" stroke="var(--color-s1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="flex flex-col gap-1 min-h-0">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-fg3">Event-loop lag (ms)</span>
                  <span style={{ color: "var(--color-peri-bright)" }}>
                    {latestLag != null ? (latestLag < 10 ? latestLag.toFixed(1) : Math.round(latestLag)) : "—"}
                  </span>
                </div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={healthData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                      <Tooltip {...TOOLTIP_PROPS} cursor={{ stroke: "rgb(var(--rgb-fg) / 0.16)" }} />
                      <Line type="monotone" dataKey="lagMs" name="lag ms" stroke="var(--color-peri)" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </Card> : null}
        </div>

        {sectionVisible("ticker") ? <Ticker requests={requests} streaming={wsConnected && !paused} /> : null}
      </div>
    </div>
  );
}
