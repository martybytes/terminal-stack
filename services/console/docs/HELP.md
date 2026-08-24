# Agent007Memory Help

Agent007Memory is the intelligence console for an AgentMemory deployment. It observes AgentMemory traffic through a transparent proxy, shows live behavior, stores privacy-safe aggregates for reports, and exposes guarded maintenance actions. It is not the memory database. Normal monitoring does not retain prompt bodies, response bodies, memory text, or complete provider keys.

This guide describes the deployment pinned to AgentMemory 0.9.29 with this stack's compatibility patches. Later AgentMemory releases may expose additional native telemetry.

## System map

The normal agent memory loop is:

1. Claude, Codex, or Cursor starts a session and supplies the agent, project, working directory, and session identifier.
2. The session-start hook requests bounded project context. File hooks and context hooks may request more context later.
3. AgentMemory ranks prior evidence with keyword, vector, and graph signals and returns a compact selection.
4. During work, hooks capture prompts, commands, file edits, tool calls, decisions, errors, and other observations.
5. AgentMemory stores raw observations immediately. Optional derived work compresses observations, summarizes sessions, extracts graph facts, and consolidates durable memories.
6. At session end, hooks record the closeout so future sessions can resume from a coherent boundary.
7. Agent007Memory records only safe metadata: route, method, stage, status, timing, project, agent, byte sizes, numeric result information, and aggregate token telemetry.

Traffic normally enters `127.0.0.1:3111`, the Agent007Memory proxy. The proxy forwards unchanged traffic to AgentMemory. Port 3110 is the direct diagnostic bypass, 3112 carries live events, 3113 is the upstream viewer, and 3114 is Agent007Memory.

## What AgentMemory stores

An **observation** is captured evidence from an agent session. It may describe a prompt, tool call, command, edit, result, decision, or error. Raw observations preserve the evidence needed for later processing.

A **compressed observation** adds a compact title, concepts, importance, and structured meaning. Compression makes retrieval more selective; it does not replace the original evidence.

A **session** groups related observations with project, agent, timestamps, and completion state. A session summary synthesizes enough compressed observations to make the work easier to resume.

A **memory** is longer-lived knowledge distilled from important related evidence. Memories can evolve through versions. A newer version may supersede an older version while retaining lineage.

The Memories total does not increase when a raw observation is captured or when that observation is compressed. Those operations enrich the observation store. The memory total grows only when an agent explicitly saves a memory or a summary/consolidation path creates durable memory records. If Observations and successful compression calls are rising while Memories is flat, capture is healthy; inspect session-end coverage and the Operations recovery preview for due summaries, graph work, or consolidation. The detailed memory inventory is cached for up to 60 seconds, so a confirmed explicit save may take one minute to appear in project-quality and inventory views.

The **knowledge graph** stores entities and relationships extracted from observations. **Semantic entries** describe durable concepts. **Procedural entries** describe repeated ways of working. **Lessons** are explicit confidence-weighted rules. These stores are related, but they are not interchangeable counts.

## Retrieval and semantics

AgentMemory smart search combines BM25 keyword matching, local vector similarity, and graph expansion. Keywords are strong for identifiers and exact phrases. Vectors recognize paraphrases and related meaning. Graph expansion can connect evidence that does not share the same words.

Results are ranked and packed into a token budget. Project and session metadata constrain retrieval when callers provide them. Compact results let an agent inspect identifiers and scores before expanding detailed evidence.

Most lookup endpoints use HTTP POST because the search query is a request body. A low GET count does not mean retrieval is missing. The lifecycle and automatic/manual classifications are the useful indicators.

Agent007Memory can prove that AgentMemory returned context or results to a hook. It cannot prove that the host model attended to, trusted, or acted on those tokens. That would require host-side attention or outcome telemetry that current coding agents do not expose.

## Automatic context and manual search

**Automatic context** includes Session Start, Context Recall, and File Enrichment. It is requested by normal hooks without a manual search.

**Manual search** includes explicit search, recall, timeline, graph-query, lesson-query, verification, and similar tools. It is shown separately because a deliberate large search is not evidence that automatic injection saved context.

Automatic and manual requests can both be useful. The split answers different questions: automatic context shows whether the memory loop is helping without prompting; manual context shows how much evidence agents deliberately requested.

## Retrieval delivery and session coverage

An attempt is **returned** when safe response metadata confirms at least one result, context block, or context token. It is **empty** when the response explicitly contains zero. It is **failed** on an HTTP or network failure. It is **unknown** when a successful response cannot be classified safely.

**Automatic recall rate** is confirmed automatic returns divided by all automatic attempts. Failed, empty, and unknown attempts remain in the denominator.

**Start coverage** is the share of observed session starts that returned confirmed automatic context. A start with no context can be legitimate for a new project, but repeated empty starts on an established project deserve investigation.

**Closeout coverage** uses a privacy-safe salted hash of the session identifier to correlate starts and ends in reporting history. Raw session identifiers are not stored in the reports database. A missing closeout may mean the agent crashed, the hook was disabled, or the console did not observe the end event.

**Context returned** is AgentMemory's reported token estimate and block count. It means delivered to the caller, not proven model use.

## Estimated context avoided

True token savings are a counterfactual: nobody can know exactly what the agent would have read or repeated if memory were absent. Agent007Memory therefore reports **Estimated context avoided** as a range, never an exact saved-token claim.

The Overview keeps four windows together: rolling 15 minutes, past 24 hours, past 7 days, and **All tracked**. The longer windows come from privacy-safe minute aggregates in Agent007Memory's reporting database. All tracked means every estimate still retained by this console, not activity from before historical collection began; hover it to see the tracking start date and exact range.

For a successful, project-scoped automatic retrieval, the model compares compact returned context with replaying the project's captured observation payloads:

1. Request payload bytes are measured exactly for future observation captures.
2. Bytes become a conservative token range using bytes divided by four through bytes divided by three.
3. Existing observations from before deployment are calibrated from observed project payload sizes, or from the global sample when needed.
4. Reported automatic context tokens are subtracted from that modeled full-history range.
5. Negative values become zero.

Empty, failed, unscoped, cross-project, and manual retrievals receive no avoided-context credit. This prevents large manual searches or unsafe scope results from inflating the headline.

**Modeled · live data** means the corpus consists of request bytes seen by this console. **Modeled · low confidence** means legacy observations were estimated from sampled payload sizes. **Needs samples** means the console lacks enough capture-size evidence.

The upstream AgentMemory viewer uses a different fixed observation/token formula. Agent007Memory intentionally does not copy it because fixed tokens per observation ignore real payload size, retrieval stage, project scope, and delivery.

## Context budgets and truncation

A **token budget** is the maximum context requested by the caller or reported by AgentMemory. The proxy extracts only bounded numeric `budget`, `token_budget`, and `tokens_budget` fields; it never retains the accompanying query or content.

**Budget utilization** compares reported context with the known budget. A response marked **truncated** filled the budget before every ranked result could fit. Truncation is often healthy because it proves the bound is working.

An **oversized retrieval** reports more context tokens than the known budget. This can indicate mismatched client/server budget fields, incompatible telemetry, or an upstream defect.

Manual searches returning very large context deserve review even when valid. Consider a smaller budget or more specific query.

## Semantics and memory quality

Memory usefulness cannot be reduced to one score. Agent007Memory reports observable signals instead:

- Semantic coverage: durable memories carrying concept tags.
- Source lineage: memories linked to source observations or sessions.
- Project coverage: memories carrying an explicit project identifier.
- Active versions: current versions that are not superseded.
- Superseded versions: preserved historical versions replaced by newer knowledge.
- Search score: the strongest relevance score returned by retrieval.
- Derived backlog: queued or running compression, summary, graph, or consolidation jobs.

A high search score is not a universal correctness grade. A strong memory can still be obsolete or inappropriate. Source lineage lets a human or agent verify it against captured evidence.

Current automatic context responses do not expose every source memory identifier. Agent007Memory therefore cannot accurately show unique-memory reuse, never-retrieved memories, or proof that a specific memory caused an action. Those metrics remain unavailable rather than appearing as misleading zeros.

## Project scoping

Every session should use one stable canonical project identifier. Filesystem paths and display names that change between machines can silently split or mix history.

**Project integrity** measures attribution on relevant traffic and checks returned project metadata. A matching result proves the response identifies the requested project. An unscoped result lacks proof. A cross-project result explicitly identifies another project and is a higher-severity warning.

**Memory project coverage** is the share of durable memories with project metadata. Legacy unscoped memories may appear in global searches, but strict project searches should reject results that cannot prove scope.

When a project is empty in Live Requests, inspect the session/start payload, tagged agent path, and session-to-project cache. Old sessions created before project attribution may remain unscoped.

## Queueing and derived work

Raw capture is designed to be immediate and zero-LLM. Expensive work is represented by durable ID-only queue jobs. A worker loads source content only after it starts the job.

**Queue depth** counts waiting jobs. **Durable wait** runs from enqueue until worker admission. **Provider gate** measures time waiting for a provider-concurrency slot. **Job runtime** runs from worker start to completion. **Dead-letter depth** counts jobs that exhausted retries.

Queueing improves reliability and burst handling; it does not inherently save tokens. Efficiency comes from bounded prompts, selective retrieval, change-aware summaries, deduplication, and routing work to appropriate models.

Project cards show queued, running, and failed derived work when safe job telemetry contains a project. Global jobs remain on LLM Calls.

## Costs and provider switching

Cost cards appear only when the active provider may charge API fees. Local loopback, RFC 1918, link-local, `.local`, and local IPv6 vLLM endpoints are classified as local when their model matches. Hosted providers remain paid behind private gateways. Unknown public endpoints remain unpriced rather than silently free.

**Estimated cost** uses provider token categories and the reviewed pricing catalog. **Billed month to date** comes from the provider's project-scoped Costs API and may lag because only completed UTC days are imported.

Switching to local inference hides live cost and key cards but never deletes paid history. Reports containing past paid or unknown-fee calls continue to show relevant cost fields.

OpenAI hints use `LLM_API_KEY_HINT` for inference and `LLM_ADMIN_KEY_HINT` for billing administration. A hint shows only the key family prefix, six identifier characters, and final four. Complete keys never enter the browser or history database.

### OpenAI project and key setup

Create a dedicated OpenAI project named **Agentmemory**. The `proj_...` ID in OpenAI's Projects table is used by the billing helper. Put the inference key inside that project and configure model rate limits, a spend limit, and alerts.

The restricted inference key currently needs only **Model capabilities → Chat completions (`/v1/chat/completions`) → Request**. Unrelated capabilities remain None. The dashboard calls this permission Request, not Write.

The restricted organization Admin key needs **Usage API Scope → Read** at runtime. Give **Organization Administration → Read** temporarily while `configure-openai-billing` validates the project ID and canonical name; it can return to None once the helper has been applied. Audit Logs Scope, Fine-tuning Checkpoints, and all unrelated permissions remain None. Re-enable Organization Administration Read only when the helper must validate the project again.

A `.key` file contains exactly the raw secret on one line—no `OPENAI_API_KEY=`, `export`, quotes, or second line. A Docker `.env` file uses `NAME=value`. Generated `.billing.env` contains non-secret project settings and masked hints, not raw secrets.

## Overview page

The top row shows memories, sessions, today's observations, requests per minute, P95 proxy latency, and process uptime.

The Memory Value row covers the rolling 15-minute agent loop. It shows storage, automatic recall, context avoided across 15-minute, 24-hour, 7-day, and all-tracked windows, session-start assistance, manual search context, project integrity, semantic coverage, and warnings. The chart places successful storage above zero and automatic/manual retrieval below zero.

The project area uses the stable saved reorder interval. Live values change immediately, but positions refresh only at that interval so cards do not jump constantly.

The LLM area shows completion, success, latency, queue, and tracked-family activity. Paid cost fields appear only when the active path may charge fees.

## Projects page

Project cards answer four questions: is evidence being stored, is automatic context delivered, how much context is selected instead of replayed, and is the memory corpus scoped and enriched?

Turquoise glow means recent storage into AgentMemory. Violet means retrieval out to an agent. Both can appear together, with intensity increasing with activity.

The chart shows confirmed stores above zero, automatic retrieval below zero in violet, and manual retrieval below zero in blue. HTTP methods remain a small transport diagnostic because GET/POST/PUT/DELETE do not describe memory semantics reliably.

Project order is newest to oldest, left to right, and refreshes at the saved interval. Pinning and exclusions override normal order.

## LLM Calls page

Provider configuration mirrors the active AgentMemory runtime. Local inference hides irrelevant OpenAI key and cost details even when stale environment values remain mounted.

The completion row shows calls, success, latency, effective output rate, queue depth, waits, runtime, and dead letters. Family cards cover compression, summaries, graph extraction, consolidation, and other calls.

**Effective output rate** is exact completion tokens divided by provider latency in seconds. It is weighted across calls by total measured time, includes time-to-first-token, and therefore describes end-to-end observed throughput rather than the model's decode-only benchmark. Failed calls, running calls, and calls without exact completion-token usage are excluded. A dash means no eligible calls were observed in the window.

**Exact Provider Calls** is the final section. It uses a bounded 360-pixel internal scroll window and pagination so a large ledger does not make the page excessively tall. The customizer controls retained calls and calls per page.

Rows contain start time, family, outcome, model, project, character count, token categories, effective output rate, cost when applicable, durable wait, provider-gate wait, and provider latency. Prompt text, completion text, raw errors, and full keys are never included.

## Reports page

Reports read Agent007Memory's SQLite aggregate database; they do not replay raw memories. Ranges use an inclusive start and exclusive end. Compare mode uses the immediately preceding equal-length range.

Memory reports preserve automatic and manual retrieval separately, captured bytes, budgets, truncation, modeled avoided-context bounds, confidence counts, latency, relevance scores, session coverage, storage outcomes, and scope warnings. LLM reports retain exact measured completion tokens and provider time so effective output rate remains available over time.

Session identifiers become salted hashes before storage. This supports unique lifecycle correlation without exposing raw IDs. Aggregate history follows the configured retention period.

Historical P95 is reconstructed from histogram counts. Sampled availability includes health polls made while the console ran; it does not pretend to measure console downtime.

CSV exports contain the same safe aggregates and neutralize spreadsheet-formula-leading text.

## Live Requests

Live Requests is a metadata-only ring buffer. It shows time, method, intent, lifecycle, project, agent, route, status, duration, and byte sizes. Expanding a row shows automatic/manual mode, safe outcome, session correlation, context/result counts, budget, truncation, relevance, project proof, and eligible avoided context.

**Intent** is a broad grouping: Lookup, Write, Health, Admin, or Other. **Lifecycle** is the specific stage, such as Session Start, File Enrichment, Observation Capture, or Manual Search. Both use one shared classifier based on normalized route and bounded MCP operation name.

The ring is temporary. Reports store aggregates, not a permanent request ledger.

## Timeline, Memories, and Sessions

Timeline displays observations for one session with type, importance, sort, and paging. Content comes directly from AgentMemory and is cached briefly only while viewing.

Memories lists durable memories and uses real hybrid search. It can show concepts, sources, files, sessions, strength, versions, and supersession. A selected project rejects results that cannot prove matching scope.

Sessions shows start assistance, automatic hits and context, manual context, captures, and closeout. Clicking a row opens its timeline. A missing closeout is diagnostic, not automatic proof of data loss.

## Operations page

Operations are guarded because they may queue significant work. Actions require the console action header and confirmation flow.

**Full memory maintenance** previews and queues basic consolidation plus the broader pipeline for one project or explicitly confirmed all-project scope.

**Recover pending work** inspects incomplete derived processing. **Force summary** summarizes a selected session even when normal thresholds defer it. **Rebuild graph snapshot** is a local repair and does not itself call an LLM.

A **dry run** is read-only. Preview counts can change before execution because agents remain active. Local inference removes external API fees but not CPU, memory, queue, or time costs.

## Display customization

Customize opens page-specific controls for sections, cards, columns, counts, width, density, scale, pins, and exclusions.

Theme is global: Dark, Light, or System. Context help is also global:

- Adaptive: ambiguous words receive subtle hover and keyboard-focus explanations; complex sections show question-mark dialogs.
- Minimal: only section question-mark dialogs remain.
- Off: inline help is hidden, while this full Help page remains available.

Preferences stay in browser local storage under `agent007memory.preferences.v1`. The internal schema migrates older settings without losing layouts, themes, pins, or visibility choices.

## Privacy and telemetry boundaries

The proxy forwards streams unchanged. For selected JSON routes it keeps a bounded temporary copy only long enough to extract approved scalars, then discards it.

Agent007Memory retains no prompt body, completion body, memory body, lesson text, raw provider error, or complete key in history. Byte lengths are transport measurements, not stored content.

Project, agent, route, operation name, status, duration, token counts, result counts, scores, and scope counts are retained because they explain behavior. Raw session IDs exist in the live ring and upstream view; reports store salted hashes.

Tooltips and dialogs are bundled documentation. Opening them changes no operational state.

## Docker deployment and live updates

The normal deployment builds Agent007Memory into its image. Source changes are not live until the image is rebuilt and the service recreated unless a development override explicitly bind-mounts source and runs watchers.

After changes, use the repository's documented Docker Compose command. Verify `/healthz`, port 3114, and browser console. Keep the SQLite reporting volume mounted so history survives replacement.

The proxy must remain the agent-facing port. Direct traffic to the diagnostic bypass makes metrics incomplete.

## Troubleshooting

### Automatic recall is missing

Use lifecycle counts, not GET counts. Confirm `AGENTMEMORY_INJECT_CONTEXT=true` in the **agent's environment**, because the hook decides whether to request injection. Check Session Start, Context Recall, and File Enrichment traffic.

### Memories are stored but never returned

Check automatic attempts, empty responses, budgets, project consistency, semantic coverage, and scope warnings. Perform a project-scoped manual search for a known fact. Successful manual search with absent automatic traffic points to hooks; failed manual search points to storage, indexing, or scope.

### Project is empty or Global

Inspect session/start and the tagged proxy path. Confirm the same stable project identifier throughout the session. Legacy sessions may predate attribution.

### Estimated context avoided is unavailable

It needs a confirmed, safely scoped automatic return plus capture-byte samples. New projects may show Needs samples. Manual searches and unsafe scope results are intentionally excluded.

### Estimated context avoided looks unusually large

The counterfactual is replaying the captured project history, not predicting the next agent action. Check confidence, corpus size, and automatic context delivered. Use the range as a trend, not an invoice-grade total.

### Queue depth keeps growing

Compare durable wait, provider-gate wait, workers, provider slots, failures, and dead letters. High durable wait suggests worker throughput; high gate wait suggests concurrency pressure; dead letters need investigation.

### Paid costs or key hints are hidden

That is expected for local inference. Historical paid data remains in Reports. For hosted inference, verify endpoint/provider classification and safe hints without exposing raw keys.

### Reporting is empty

History begins after deployment with its SQLite volume. Check history status, writable storage, range, and filters. Earlier live ring data cannot be reconstructed.

## Glossary

**P50** is median latency. **P95** means 95 percent of requests were at or below that latency.

**Automatic retrieval** is context requested by normal hooks. **Manual retrieval** is an explicit search or recall tool.

**Reported tokens** are AgentMemory or provider telemetry. **Modeled tokens** come from the documented byte-range counterfactual.

**BM25** is keyword ranking. **Vector similarity** matches meaning. **Graph expansion** follows connected concepts.

**Scoped** means carrying project proof. **Unscoped** means no proof. **Cross-project** identifies another project.

**Durable memory** is consolidated knowledge. **Observation** is session evidence. **Lineage** links derived knowledge to sources.

**Truncated** means a budget was filled. **Oversized** means reported context exceeded the known budget.

**Local provider** means no external API fee is expected. Local work still uses machine resources.
