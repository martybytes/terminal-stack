import { useMemo, useState } from "react";
import { BookOpen, Search } from "lucide-react";
import helpMarkdown from "../../../docs/HELP.md?raw";
import { Card, PageHeader } from "../components/ui";
import { usePagePreferences } from "../lib/preferences";
import { HelpSectionBody, helpSectionsFrom } from "../components/HelpMarkdown";

export default function Help(): JSX.Element {
  const { sectionVisible } = usePagePreferences("help");
  const [query, setQuery] = useState("");
  const allSections = useMemo(() => helpSectionsFrom(helpMarkdown), []);
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return term ? allSections.filter((section) => `${section.title}\n${section.lines.join("\n")}`.toLowerCase().includes(term)) : allSections;
  }, [allSections, query]);
  return (
    <div className="flex min-h-full flex-col gap-5">
      <PageHeader title="Help" subtitle="how Agent007Memory, AgentMemory, retrieval, costs, history, and operations work" />
      <div className={`grid items-start gap-5 ${sectionVisible("toc") ? "xl:grid-cols-[250px_minmax(0,1fr)]" : "grid-cols-1"}`}>
        {sectionVisible("toc") ? <Card className="sticky top-0 p-3">
          <label className="flex items-center gap-2 rounded-lg border border-line bg-side px-3 py-2"><Search size={14} className="text-fg3" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search help" className="min-w-0 flex-1 bg-transparent text-[11px] text-fg1 outline-none placeholder:text-fg3" /></label>
          <nav className="mt-3 max-h-[calc(100vh-250px)] space-y-0.5 overflow-y-auto pr-1">{allSections.map((section) => <a key={section.id} href={`#${section.id}`} className="block rounded-md px-2 py-1.5 font-display text-[10px] text-fg3 no-underline hover:bg-peri/10 hover:text-fg1">{section.title}</a>)}</nav>
        </Card> : null}
        {sectionVisible("content") ? <div className="space-y-4">
          {visible.length === 0 ? <Card className="p-8 text-center text-sm text-fg3">No help sections match “{query}”.</Card> : visible.map((section) => <section key={section.id} id={section.id} className="scroll-mt-4"><Card className="p-5"><div className="mb-3 flex items-center gap-2"><BookOpen size={16} className="text-turq" /><h2 className="font-display text-[16px] font-semibold text-fg1">{section.title}</h2></div><HelpSectionBody lines={section.lines} /></Card></section>)}
        </div> : null}
      </div>
    </div>
  );
}
