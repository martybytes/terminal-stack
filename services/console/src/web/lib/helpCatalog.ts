export interface HelpDefinition {
  title: string;
  summary: string;
  section: string;
}

export const HELP_CATALOG = {
  memories: { title: "Memories", summary: "Long-lived facts, lessons, and consolidated knowledge. Capturing or compressing observations does not increment this count.", section: "what-agentmemory-stores" },
  sessions: { title: "Sessions", summary: "Units of agent work bounded by a start and, when hooks finish normally, an end event.", section: "system-map" },
  observations: { title: "Observations", summary: "Captured evidence such as prompts, commands, edits, tool calls, decisions, and errors.", section: "what-agentmemory-stores" },
  "requests-per-minute": { title: "Requests per minute", summary: "Proxy requests completed during the most recent rolling minute.", section: "overview-page" },
  "p95-latency": { title: "P95 latency", summary: "Ninety-five percent of requests were this fast or faster in the displayed window.", section: "glossary" },
  uptime: { title: "Uptime", summary: "How long the current AgentMemory process has been running since its last restart.", section: "glossary" },
  "save-reliability": { title: "Save reliability", summary: "Confirmed observation and explicit-memory stores divided by all attempted stores.", section: "retrieval-delivery-and-session-coverage" },
  "automatic-recall": { title: "Automatic recall", summary: "Context requested by session-start, context, and file-enrichment hooks without a manual search.", section: "automatic-context-and-manual-search" },
  "recall-delivered": { title: "Recall delivered", summary: "Retrieval attempts that returned context or results. Delivery does not prove the model used them.", section: "retrieval-delivery-and-session-coverage" },
  "context-returned": { title: "Context returned", summary: "The upstream token estimate and blocks sent back to the agent hook, not proof of attention or use.", section: "automatic-context-and-manual-search" },
  "estimated-context-avoided": { title: "Estimated context avoided", summary: "A modeled range comparing compact automatic context with replaying captured history. Overview totals cover 15 minutes, 24 hours, 7 days, and all retained estimates.", section: "estimated-context-avoided" },
  "manual-context": { title: "Manual context", summary: "Tokens returned by explicit search or recall tools. Kept separate from automatic context savings.", section: "automatic-context-and-manual-search" },
  "start-coverage": { title: "Start coverage", summary: "The share of observed session starts that received confirmed context automatically.", section: "retrieval-delivery-and-session-coverage" },
  "closeout-coverage": { title: "Closeout coverage", summary: "The share of observed sessions with a matching end hook recorded by the console.", section: "retrieval-delivery-and-session-coverage" },
  "project-integrity": { title: "Project integrity", summary: "Whether scoped retrieval results prove they belong to the requested project.", section: "project-scoping" },
  "memory-project-coverage": { title: "Memory project coverage", summary: "The share of durable memories carrying an explicit project identifier.", section: "project-scoping" },
  "semantic-coverage": { title: "Semantic coverage", summary: "The share of durable memories with concept tags that support meaning-based retrieval.", section: "semantics-and-memory-quality" },
  "source-lineage": { title: "Source lineage", summary: "The share of memories linked back to source observations or sessions for verification.", section: "semantics-and-memory-quality" },
  "active-versions": { title: "Active versions", summary: "Current memory versions after older superseded versions are excluded.", section: "semantics-and-memory-quality" },
  "derived-backlog": { title: "Derived backlog", summary: "Queued or running compression, summary, graph, and consolidation work for the project.", section: "queueing-and-derived-work" },
  "intent": { title: "Intent", summary: "A broad semantic grouping: lookup, write, health, admin, or other.", section: "live-requests" },
  "lifecycle": { title: "Lifecycle", summary: "The specific memory-loop stage inferred from the normalized route and bounded operation name.", section: "live-requests" },
  "request-bytes": { title: "Request bytes", summary: "Transport payload size only. Agent007Memory does not retain the request body.", section: "privacy-and-telemetry-boundaries" },
  "response-bytes": { title: "Response bytes", summary: "Transport response size only. Agent007Memory discards response content after safe numeric extraction.", section: "privacy-and-telemetry-boundaries" },
  "token-budget": { title: "Token budget", summary: "The maximum retrieval context requested or reported for a response.", section: "context-budgets-and-truncation" },
  truncation: { title: "Truncation", summary: "Ranked results reached the configured context budget; this can be expected and healthy.", section: "context-budgets-and-truncation" },
  "top-score": { title: "Top score", summary: "The strongest relevance score returned in the response. Scores are useful as trends, not universal grades.", section: "semantics-and-memory-quality" },
  "durable-wait": { title: "Durable wait", summary: "Time from queue insertion until a worker admitted the job.", section: "queueing-and-derived-work" },
  "provider-gate": { title: "Provider gate", summary: "Time a running worker waited for an available provider-concurrency slot.", section: "queueing-and-derived-work" },
  "job-runtime": { title: "Job runtime", summary: "Time from worker start until the derived-memory job completed or failed.", section: "queueing-and-derived-work" },
  "dead-letter": { title: "Dead letter", summary: "Jobs that exhausted retries and now require operator investigation.", section: "queueing-and-derived-work" },
  "estimated-cost": { title: "Estimated cost", summary: "A catalog estimate from reported tokens. It appears only for providers that may charge API fees.", section: "costs-and-provider-switching" },
  "billed-cost": { title: "Billed cost", summary: "Provider-reported project cost for complete billing days, which may lag live activity.", section: "costs-and-provider-switching" },
  "success-rate": { title: "Success rate", summary: "Successful completed calls divided by all completed calls in the displayed window.", section: "llm-calls-page" },
  "output-rate": { title: "Effective output rate", summary: "Exact completion tokens divided by provider latency. It includes time-to-first-token and excludes failed or usage-less calls.", section: "llm-calls-page" },
  "exact-provider-calls": { title: "Exact Provider Calls", summary: "Privacy-safe per-call telemetry: model, tokens, timing, queue delays, outcome, and project—never prompts or completions.", section: "llm-calls-page" },
  "sampled-availability": { title: "Sampled availability", summary: "Successful AgentMemory health polls while this console was running; console downtime is not sampled.", section: "reports-page" },
  "estimated-p95": { title: "Estimated P95", summary: "Historical P95 reconstructed from privacy-safe latency histogram buckets.", section: "reports-page" },
  "dry-run": { title: "Dry run", summary: "A read-only preview of scope and projected work. It does not queue maintenance jobs.", section: "operations-page" },
  "full-memory-maintenance": { title: "Full memory maintenance", summary: "Queues basic consolidation and the broader derived-memory pipeline for the selected scope.", section: "operations-page" },
  "search-score": { title: "Search score", summary: "A combined retrieval relevance signal from keyword, vector, and graph evidence.", section: "semantics-and-memory-quality" },
  strength: { title: "Strength", summary: "AgentMemory's confidence or durability signal for a memory; it is not proof of correctness.", section: "semantics-and-memory-quality" },
  supersedes: { title: "Supersedes", summary: "Older memory versions replaced by this newer version while preserving lineage.", section: "semantics-and-memory-quality" },
} satisfies Record<string, HelpDefinition>;

export type HelpId = keyof typeof HELP_CATALOG;

const LABEL_IDS: Record<string, HelpId> = {
  memories: "memories", sessions: "sessions", observations: "observations", uptime: "uptime",
  "requests / min": "requests-per-minute", "requests per minute": "requests-per-minute",
  "p95 latency": "p95-latency", "estimated p95": "estimated-p95", "save reliability": "save-reliability",
  "recall delivered": "recall-delivered", "context returned": "context-returned",
  "estimated context avoided": "estimated-context-avoided", "manual context": "manual-context",
  "start coverage": "start-coverage", "closeout coverage": "closeout-coverage",
  "project integrity": "project-integrity", "memory project coverage": "memory-project-coverage",
  "semantic coverage": "semantic-coverage", "source lineage": "source-lineage",
  "active versions": "active-versions", "derived backlog": "derived-backlog",
  intent: "intent", lifecycle: "lifecycle", "request bytes": "request-bytes", "response bytes": "response-bytes",
  "token budget": "token-budget", truncated: "truncation", "top score": "top-score",
  "durable wait": "durable-wait", "provider gate": "provider-gate", "job runtime": "job-runtime",
  "dead letter": "dead-letter", "estimated cost": "estimated-cost", "billed cost": "billed-cost",
  "success rate": "success-rate", "exact provider calls": "exact-provider-calls",
  "output rate": "output-rate", "effective output rate": "output-rate",
  "sampled availability": "sampled-availability", "full memory maintenance": "full-memory-maintenance",
  "search score": "search-score", strength: "strength", supersedes: "supersedes",
};

export function helpIdForLabel(label: string): HelpId | null {
  const normalized = label.trim().toLowerCase().replace(/·.*$/, "").replace(/\s+/g, " ").trim();
  return LABEL_IDS[normalized] ?? null;
}
