// Display formatting helpers. All of these are render-path functions: keep
// them allocation-light and never throw on odd inputs.

const NUM = new Intl.NumberFormat("en-US");
const COMPACT_UNITS = [
  { value: 1_000_000_000_000, suffix: "T" },
  { value: 1_000_000_000, suffix: "G" },
  { value: 1_000_000, suffix: "M" },
  { value: 1_000, suffix: "K" },
] as const;

function trimFixed(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.0+$|(?<=\.[0-9])0+$/, "");
}

/** 12847 -> "12,847" · null/undefined -> "—" */
export function fmtNum(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return NUM.format(n);
}

/** Compact large dashboard counts while keeping smaller operational counts exact. */
export function fmtCompactNum(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const magnitude = Math.abs(n);
  if (magnitude < 100_000) return fmtNum(n);
  const unit = COMPACT_UNITS.find((item) => magnitude >= item.value) ?? COMPACT_UNITS.at(-1)!;
  const scaled = n / unit.value;
  const digits = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2;
  return `${trimFixed(scaled, digits)}${unit.suffix}`;
}

/** Compact a dashboard range with one shared suffix so the value stays readable in narrow cards. */
export function fmtCompactRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null || !Number.isFinite(low) || !Number.isFinite(high)) return "—";
  const magnitude = Math.max(Math.abs(low), Math.abs(high));
  if (magnitude < 10_000) return `${fmtNum(low)}–${fmtNum(high)}`;
  const unit = COMPACT_UNITS.find((item) => magnitude >= item.value) ?? COMPACT_UNITS.at(-1)!;
  const largestScaled = magnitude / unit.value;
  const digits = largestScaled >= 100 ? 0 : 1;
  return `${trimFixed(low / unit.value, digits)}–${trimFixed(high / unit.value, digits)}${unit.suffix}`;
}

export function fmtUsdNanos(nanos: number | null | undefined): string {
  if (nanos == null || !Number.isFinite(nanos)) return "—";
  const dollars = nanos / 1_000_000_000;
  return dollars.toLocaleString("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2,
    maximumFractionDigits: dollars > 0 && dollars < 0.01 ? 4 : 2,
  });
}

/** Byte counts. -1 (unknown / chunked) -> "—" · 2131 -> "2.1 KB" */
export function fmtBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${Math.round(n)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

/** Durations. 31 -> "31 ms" · 1240 -> "1.24 s" */
export function fmtMs(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1000) return `${Math.round(n)} ms`;
  const s = n / 1000;
  return `${s >= 10 ? s.toFixed(1) : s.toFixed(2)} s`;
}

/** Effective output throughput. This includes time-to-first-token. */
export function fmtTokensPerSecond(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n < 0) return "—";
  return `${n >= 100 ? Math.round(n) : n >= 10 ? n.toFixed(1) : n.toFixed(2)} tok/s`;
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** Epoch ms -> local "14:35:07" */
export function fmtClock(ts: number): string {
  const d = new Date(ts);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

/** Epoch ms -> local "14:35:07.412" */
export function fmtClockMs(ts: number): string {
  const d = new Date(ts);
  return `${fmtClock(ts)}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/** Epoch ms -> "4s ago" / "3m ago" / "2h ago" / "5d ago" */
export function timeAgo(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Seconds of uptime -> "6d 4h" / "3h 12m" / "2m" / "45s" · null -> "—" */
export function fmtUptime(sec: number | null): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "—";
  const s = Math.floor(sec);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}
