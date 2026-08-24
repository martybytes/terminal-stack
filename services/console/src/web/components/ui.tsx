// Shared UI primitives, styled 1:1 after the .dc.html mockups.
// Token colors come from src/web/index.css (@theme); the translucent tints
// used by pills/chips are mockup-exact rgba values kept inline.

import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import type { RequestIntent } from "../../shared/requestIntent";
import { lifecycleLabel, type MemoryLifecycleStage } from "../../shared/memoryLifecycle";
import { HelpLabel, HelpTopic } from "./ContextHelp";
import type { HelpId } from "../lib/helpCatalog";

// ---------------------------------------------------------------- Card

export function Card({
  className,
  children,
  style,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  style?: CSSProperties;
} & Omit<HTMLAttributes<HTMLDivElement>, "className" | "children" | "style">) {
  return (
    <div {...rest} className={`bg-surface border border-line rounded-xl ${className ?? ""}`} style={style}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- Eyebrow

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-display font-medium text-[11px] leading-[1.25] tracking-[0.01em] text-fg3">
      {typeof children === "string" ? <HelpLabel label={children} /> : children}
    </div>
  );
}

// ---------------------------------------------------------------- StatTile

export function StatTile({
  label,
  value,
  sub,
  action,
  dim,
  compact = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  action?: ReactNode;
  dim?: boolean;
  compact?: boolean;
}) {
  return (
    <Card className={`${compact ? "px-3 py-2.5" : "px-4 py-3.5"} min-w-0`}>
      <div className="flex items-start justify-between gap-2"><Eyebrow>{label}</Eyebrow>{action}</div>
      <div
        className={`font-display font-bold ${compact ? "mt-0.5 text-[22px]" : "mt-1 text-[26px]"} leading-tight tracking-[-0.02em] truncate ${
          dim ? "text-fg3" : "text-fg1"
        }`}
      >
        {value}
      </div>
      {sub != null ? (
        <div className={`${compact ? "text-[10px]" : "text-[11px]"} text-fg3 mt-0.5 truncate`}>
          {sub}
        </div>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------- Pill

export type PillTone = "ok" | "warn" | "bad" | "na" | "get" | "post" | "put" | "del" | "info";

const PILL_STYLES: Record<PillTone, CSSProperties> = {
  ok: { background: "rgba(31,160,169,0.16)", color: "var(--color-turq-bright)" },
  warn: { background: "rgba(187,132,18,0.18)", color: "#E4B24C" },
  bad: { background: "rgba(194,64,40,0.18)", color: "var(--color-bad-bright)" },
  na: { background: "rgba(58,65,96,0.45)", color: "var(--color-fg2)" },
  get: { background: "rgba(31,160,169,0.14)", color: "var(--color-turq-bright)" },
  post: { background: "rgba(138,128,240,0.16)", color: "var(--color-peri-bright)" },
  put: { background: "rgba(79,160,92,0.18)", color: "#8FCB9A" },
  del: { background: "rgba(194,64,40,0.16)", color: "var(--color-bad-bright)" },
  info: { background: "rgba(83,226,221,0.12)", color: "#8FEDEA" },
};

export function Pill({ tone, children }: { tone: PillTone; children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-[5px] font-mono text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
      style={PILL_STYLES[tone]}
    >
      {children}
    </span>
  );
}

export function MethodPill({ method }: { method: string }) {
  const m = method.toUpperCase();
  const tone: PillTone =
    m === "GET"
      ? "get"
      : m === "POST"
        ? "post"
        : m === "PUT" || m === "PATCH"
          ? "put"
          : m === "DELETE"
            ? "del"
            : "info";
  return <Pill tone={tone}>{m}</Pill>;
}

export function IntentPill({ intent }: { intent: RequestIntent }) {
  const tone: PillTone =
    intent === "lookup"
      ? "get"
      : intent === "write"
        ? "post"
        : intent === "health"
          ? "ok"
          : intent === "admin"
            ? "warn"
            : "na";
  return <Pill tone={tone}>{intent === "lookup" ? "LOOKUP" : intent.toUpperCase()}</Pill>;
}

export function LifecyclePill({ stage }: { stage: MemoryLifecycleStage }) {
  const tone: PillTone =
    stage === "context_recall" || stage === "file_enrichment" || stage === "manual_search" || stage === "session_start"
      ? "get"
      : stage === "observation_capture" || stage === "memory_save"
        ? "post"
        : stage === "compress" || stage === "summarize" || stage === "graph_extract" || stage === "consolidate"
          ? "put"
          : stage === "health"
            ? "ok"
            : stage === "admin"
              ? "warn"
              : "na";
  return <Pill tone={tone}>{lifecycleLabel(stage).toUpperCase()}</Pill>;
}

export function AgentPill({ agent }: { agent: string | null }) {
  const normalized = agent?.trim().toLowerCase() ?? "";
  const tone: PillTone =
    normalized === "claude"
      ? "post"
      : normalized === "codex"
        ? "get"
        : normalized === "cursor"
          ? "put"
          : "na";
  const label = normalized
    ? normalized.charAt(0).toUpperCase() + normalized.slice(1)
    : "Unknown";
  return <Pill tone={tone}>{label}</Pill>;
}

export function StatusPill({ status }: { status: number }) {
  const tone: PillTone = status === 0 || status >= 500 ? "bad" : status >= 400 ? "warn" : "ok";
  return <Pill tone={tone}>{status === 0 ? "ERR" : status}</Pill>;
}

// ---------------------------------------------------------------- Chip

export function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 font-display font-medium text-xs px-3 py-1.5 rounded-full border transition-colors cursor-pointer"
      style={
        on
          ? {
              background: "rgba(83,226,221,0.12)",
              borderColor: "rgba(83,226,221,0.5)",
              color: "#8FEDEA",
            }
          : {
              background: "transparent",
              borderColor: "var(--color-linestrong)",
              color: "var(--color-fg2)",
            }
      }
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- SelectBox

export function SelectBox({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  label?: string;
}) {
  return (
    <label className="inline-flex items-center gap-2">
      {label ? (
        <span className="font-display font-medium text-[11px] text-fg3"><HelpLabel label={label} /></span>
      ) : null}
      <span className="relative inline-flex items-center">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="appearance-none bg-side border border-linestrong rounded-lg pl-3 pr-8 py-2 text-fg1 font-display font-medium text-xs cursor-pointer"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 w-3.5 h-3.5 text-fg3" />
      </span>
    </label>
  );
}

// ---------------------------------------------------------------- PageHeader

export function PageHeader({
  title,
  subtitle,
  right,
  helpId,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  helpId?: HelpId;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5"><h1 className="font-display font-semibold text-[26px] leading-tight tracking-[-0.02em] text-fg1 m-0">{title}</h1>{helpId ? <HelpTopic id={helpId} /> : null}</div>
        {subtitle != null ? <div className="text-[13px] text-fg3 mt-[3px]">{subtitle}</div> : null}
      </div>
      {right != null ? <div className="flex items-center gap-2.5 flex-none">{right}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------- EmptyState

export function EmptyState({
  icon,
  title,
  body,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center text-center gap-4 max-w-[440px] mx-auto py-10 px-6">
      {icon != null ? (
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{
            background: "rgba(138,128,240,0.10)",
            border: "1px solid rgba(138,128,240,0.35)",
          }}
        >
          {icon}
        </div>
      ) : null}
      <div>
        <div className="font-display font-semibold text-[17px] text-fg1">{title}</div>
        {body != null ? (
          <div className="text-[13px] text-fg2 mt-1.5 leading-[1.55]">{body}</div>
        ) : null}
      </div>
      {actions != null ? <div className="flex gap-2">{actions}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------- Paginator

/** Page numbers to render for a 0-based pager; -1 marks an ellipsis gap. */
function pageList(page: number, pages: number): number[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i);
  const out: number[] = [0];
  const lo = Math.max(1, page - 1);
  const hi = Math.min(pages - 2, page + 1);
  if (lo > 1) out.push(-1);
  for (let i = lo; i <= hi; i++) out.push(i);
  if (hi < pages - 2) out.push(-1);
  out.push(pages - 1);
  return out;
}

const PG_BTN =
  "inline-flex items-center justify-center min-w-[30px] h-[30px] px-2 rounded-lg font-display font-medium text-xs border cursor-pointer disabled:opacity-40 disabled:cursor-default";

export function Paginator({
  page,
  pages,
  onPage,
}: {
  page: number;
  pages: number;
  onPage: (p: number) => void;
}) {
  if (pages <= 0) return null;
  const items = pageList(page, pages);
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        className={`${PG_BTN} border-transparent text-fg2`}
        disabled={page <= 0}
        onClick={() => onPage(page - 1)}
        aria-label="Previous page"
      >
        <ChevronLeft className="w-3.5 h-3.5" />
        Prev
      </button>
      {items.map((p, i) =>
        p === -1 ? (
          <span key={`gap-${i}`} className="px-1 text-fg3 text-xs select-none">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            className={`${PG_BTN} ${p === page ? "text-fg1" : "border-transparent text-fg2"}`}
            style={
              p === page
                ? {
                    background: "rgba(138,128,240,0.18)",
                    borderColor: "rgba(138,128,240,0.5)",
                  }
                : undefined
            }
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
          >
            {p + 1}
          </button>
        ),
      )}
      <button
        type="button"
        className={`${PG_BTN} border-transparent text-fg2`}
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
        aria-label="Next page"
      >
        Next
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- Dot

const DOT_COLORS: Record<"ok" | "warn" | "down" | "unknown", string> = {
  ok: "var(--color-ok)",
  warn: "var(--color-warn)",
  down: "var(--color-bad)",
  unknown: "var(--color-na)",
};

export function Dot({ state }: { state: "ok" | "warn" | "down" | "unknown" }) {
  return (
    <span
      className="inline-block w-[7px] h-[7px] rounded-full flex-none"
      style={{ background: DOT_COLORS[state] }}
    />
  );
}
