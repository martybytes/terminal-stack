import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { HelpCircle, X } from "lucide-react";
import helpMarkdown from "../../../docs/HELP.md?raw";
import { HELP_CATALOG, helpIdForLabel, type HelpId } from "../lib/helpCatalog";
import { usePreferences } from "../lib/preferences";
import { HelpSectionBody, helpSectionsFrom } from "./HelpMarkdown";

function useTooltipPosition(open: boolean, trigger: React.RefObject<HTMLElement>) {
  const [style, setStyle] = useState<CSSProperties>({ opacity: 0 });
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(320, window.innerWidth - 24);
      const left = Math.max(12, Math.min(window.innerWidth - width - 12, rect.left + rect.width / 2 - width / 2));
      const below = rect.bottom + 10;
      const top = below + 120 < window.innerHeight ? below : Math.max(12, rect.top - 130);
      setStyle({ position: "fixed", left, top, width, zIndex: 120, opacity: 1 });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, trigger]);
  return style;
}

export function HelpTerm({ id, children, className = "" }: { id?: HelpId | null; children: ReactNode; className?: string }) {
  const { helpMode } = usePreferences();
  const definition = id ? HELP_CATALOG[id] : null;
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const trigger = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();
  const style = useTooltipPosition(open, trigger);
  if (!definition || helpMode !== "adaptive") return <>{children}</>;
  const show = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 180);
  };
  const hide = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(false), 80);
  };
  return <>
    <span
      ref={trigger}
      tabIndex={0}
      aria-describedby={open ? tooltipId : undefined}
      className={`cursor-help border-b border-dotted border-fg3/60 outline-none transition-colors hover:border-turq/80 focus:border-turq focus:text-fg1 ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onClick={(event) => { event.preventDefault(); event.stopPropagation(); setOpen((value) => !value); }}
      onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
    >{children}</span>
    {open && typeof document !== "undefined" ? createPortal(
      <div
        id={tooltipId}
        role="tooltip"
        style={{ ...style, background: "var(--color-tooltip, var(--color-surface))", backdropFilter: "blur(14px)" }}
        className="pointer-events-none isolate rounded-xl border border-linestrong px-3.5 py-3 text-left shadow-[0_14px_40px_rgba(0,0,0,0.58)]"
      >
        <div className="font-display text-[12px] font-semibold text-fg1">{definition.title}</div>
        <div className="mt-1 text-[11px] leading-[1.55] text-fg2">{definition.summary}</div>
      </div>, document.body,
    ) : null}
  </>;
}

export function HelpLabel({ label, id }: { label: string; id?: HelpId | null }) {
  return <HelpTerm id={id ?? helpIdForLabel(label)}>{label}</HelpTerm>;
}

export function HelpTopic({ id, label }: { id: HelpId; label?: string }) {
  const { helpMode } = usePreferences();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const definition = HELP_CATALOG[id];
  const section = useMemo(() => helpSectionsFrom(helpMarkdown).find((item) => item.id === definition.section), [definition.section]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); return; }
      if (event.key !== "Tab") return;
      const focusable = [...(dialog.current?.querySelectorAll<HTMLElement>('button,a[href],[tabindex]:not([tabindex="-1"])') ?? [])];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => dialog.current?.querySelector<HTMLElement>("button")?.focus());
    return () => { document.removeEventListener("keydown", onKey); (previous ?? trigger.current)?.focus(); };
  }, [open]);
  if (helpMode === "off") return null;
  return <>
    <button ref={trigger} type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); setOpen(true); }} className="inline-flex h-5 w-5 flex-none items-center justify-center rounded-full text-fg3 transition hover:bg-peri/12 hover:text-peri focus:outline-none focus:ring-1 focus:ring-turq" aria-label={label ?? `Learn about ${definition.title}`} title={label ?? `Learn about ${definition.title}`}>
      <HelpCircle size={14} />
    </button>
    {open && typeof document !== "undefined" ? createPortal(
      <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/55 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`help-topic-${id}`} className="max-h-[82vh] w-full max-w-[680px] overflow-hidden rounded-2xl border border-linestrong bg-surface shadow-[0_28px_90px_rgba(0,0,0,0.55)]">
          <div className="flex items-start justify-between border-b border-line px-5 py-4">
            <div><div id={`help-topic-${id}`} className="font-display text-lg font-semibold text-fg1">{definition.title}</div><div className="mt-1 text-[12px] leading-relaxed text-fg3">{definition.summary}</div></div>
            <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-2 text-fg3 hover:bg-side hover:text-fg1" aria-label="Close help"><X size={17} /></button>
          </div>
          <div className="max-h-[calc(82vh-130px)] overflow-y-auto p-5">{section ? <HelpSectionBody lines={section.lines} /> : <p className="text-sm text-fg2">More detail is available in the complete Help guide.</p>}</div>
          <div className="flex items-center justify-between border-t border-line px-5 py-3"><span className="text-[10px] text-fg3">Plain-language guidance · no live data is changed</span><a href="#/help" onClick={() => setOpen(false)} className="font-display text-[11px] font-semibold text-turq no-underline hover:underline">Open full Help</a></div>
        </div>
      </div>, document.body,
    ) : null}
  </>;
}
