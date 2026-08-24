import type { ReactNode } from "react";

export interface HelpSection { title: string; id: string; lines: string[] }

export const helpSlug = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export function helpSectionsFrom(markdown: string): HelpSection[] {
  const sections: HelpSection[] = [];
  let current: HelpSection = { title: "Introduction", id: "introduction", lines: [] };
  for (const line of markdown.split(/\r?\n/)) {
    if (line.startsWith("# ")) continue;
    if (line.startsWith("## ")) {
      if (current.lines.some(Boolean)) sections.push(current);
      const title = line.slice(3).trim();
      current = { title, id: helpSlug(title), lines: [] };
    } else current.lines.push(line);
  }
  if (current.lines.some(Boolean)) sections.push(current);
  return sections;
}

function inline(value: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(value.slice(cursor, index));
    const token = match[0];
    if (token.startsWith("**")) parts.push(<strong key={index} className="font-semibold text-fg1">{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) parts.push(<code key={index} className="rounded bg-side px-1 py-0.5 font-mono text-[0.92em] text-turq">{token.slice(1, -1)}</code>);
    else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (link) parts.push(<a key={index} href={link[2]} target={link[2].startsWith("#") ? undefined : "_blank"} rel="noreferrer" className="text-turq underline decoration-turq/40 underline-offset-2">{link[1]}</a>);
    }
    cursor = index + token.length;
  }
  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts;
}

export function HelpSectionBody({ lines, compact = false }: { lines: string[]; compact?: boolean }) {
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  let ordered = false;
  const flush = () => {
    if (!list.length) return;
    const Tag = ordered ? "ol" : "ul";
    blocks.push(<Tag key={`list-${blocks.length}`} className={`${compact ? "space-y-1 text-[12px]" : "space-y-1.5 text-[12px]"} pl-5 leading-[1.65] text-fg2 ${ordered ? "list-decimal" : "list-disc"}`}>{list.map((line, index) => <li key={index}>{inline(line)}</li>)}</Tag>);
    list = [];
  };
  for (const raw of lines) {
    const line = raw.trim();
    const numbered = /^\d+\.\s+/.test(line);
    const bulleted = line.startsWith("- ");
    if (numbered || bulleted) {
      const nextOrdered = numbered;
      if (list.length && ordered !== nextOrdered) flush();
      ordered = nextOrdered;
      list.push(line.replace(/^(-|\d+\.)\s+/, ""));
      continue;
    }
    flush();
    if (!line) continue;
    if (line.startsWith("### ")) blocks.push(<h3 key={blocks.length} className="font-display text-[13px] font-semibold text-fg1">{line.slice(4)}</h3>);
    else blocks.push(<p key={blocks.length} className={`${compact ? "text-[12px] leading-[1.6]" : "text-[12px] leading-[1.7]"} text-fg2`}>{inline(line)}</p>);
  }
  flush();
  return <div className={compact ? "space-y-2.5" : "space-y-3"}>{blocks}</div>;
}
