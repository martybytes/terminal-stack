// Privacy-safe response outcome extraction.
//
// Selected AgentMemory JSON responses are observed while they stream through
// the proxy. Bytes are forwarded unchanged. A bounded temporary copy is parsed
// only to retain numeric counts, scores, project-integrity signals, and context
// size. Prompt, memory, lesson, and error text is never retained.

import { Transform, type Readable } from "node:stream";
import type { MemoryRequestOutcome } from "../shared/types.js";
import type { MemoryLifecycleStage } from "../shared/memoryLifecycle.js";

export const RESPONSE_METADATA_BODY_MAX = 512 * 1024;

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function string(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function boolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function nestedMcpPayload(root: Record<string, unknown>): Record<string, unknown> {
  const content = Array.isArray(root.content) ? root.content : [];
  const first = record(content[0]);
  const text = string(first?.text);
  if (!text) return root;
  try {
    return record(JSON.parse(text)) ?? root;
  } catch {
    return root;
  }
}

function resultRows(root: Record<string, unknown>): unknown[] {
  const results = Array.isArray(root.results) ? root.results : [];
  const lessons = Array.isArray(root.lessons) ? root.lessons : [];
  const memories = Array.isArray(root.memories) ? root.memories : [];
  return results.length > 0 || lessons.length > 0 ? [...results, ...lessons] : memories;
}

function scoreOf(value: unknown): number | null {
  const row = record(value);
  return finite(row?.score) ?? finite(row?.combinedScore) ?? finite(row?.confidence);
}

function projectOf(value: unknown): string | null {
  const row = record(value);
  return string(row?.project) ?? string(record(row?.observation)?.project) ?? string(record(row?.memory)?.project);
}

function sessionIdOf(value: unknown): string | null {
  const row = record(value);
  return string(row?.sessionId) ?? string(row?.session_id) ?? string(record(row?.observation)?.sessionId) ?? string(record(row?.observation)?.session_id);
}

interface OutcomeExtraction {
  outcome: MemoryRequestOutcome | null;
  /** Transient only: used to resolve result project scope, never captured. */
  unresolvedSessionIds: string[];
}

function extractOutcome(
  value: unknown,
  lifecycle: MemoryLifecycleStage,
  requestProject: string | null,
): OutcomeExtraction {
  const unresolvedSessionIds: string[] = [];
  let root = record(value);
  if (!root) return { outcome: null, unresolvedSessionIds };
  root = nestedMcpPayload(root);

  const memory = record(root.memory);
  const returnedProject = string(memory?.project) ?? string(root.project);
  const rows = resultRows(root);
  const explicitResultCount = finite(root.resultCount) ?? finite(root.count);
  const resultCount = rows.length > 0 ? rows.length : explicitResultCount;
  const context = string(root.context);
  const contextChars = context === null ? null : context.length;
  const contextBlocks = finite(root.blocks);
  const contextTokens = finite(root.tokens) ?? finite(root.tokens_used);
  const reportedTokenBudget = finite(root.tokens_budget) ?? finite(root.token_budget) ?? finite(root.budget);
  const scores = rows.map(scoreOf).filter((score): score is number => score !== null);
  const topScore = scores.length > 0 ? Math.max(...scores) : null;

  let projectMatchCount: number | null = null;
  let unscopedResultCount: number | null = null;
  let crossProjectResultCount: number | null = null;
  if (requestProject && rows.length > 0) {
    projectMatchCount = 0;
    unscopedResultCount = 0;
    crossProjectResultCount = 0;
    for (const value of rows) {
      const project = projectOf(value);
      if (project === null) {
        unscopedResultCount++;
        const sessionId = sessionIdOf(value);
        if (sessionId) unresolvedSessionIds.push(sessionId);
      } else if (project === requestProject) projectMatchCount++;
      else crossProjectResultCount++;
    }
  }

  const hasReturnedContext = (contextChars ?? 0) > 0 || (contextBlocks ?? 0) > 0 || (contextTokens ?? 0) > 0;
  const hasResults = (resultCount ?? 0) > 0;
  const hasMemory = memory !== null || lifecycle === "memory_save" && string(root.id) !== null;
  const kind = hasMemory
    ? "stored"
    : hasReturnedContext || hasResults
      ? "returned"
      : resultCount === 0 || contextChars === 0 || contextBlocks === 0
        ? "empty"
        : "unknown";

  return { outcome: {
    kind,
    resultCount: resultCount ?? (hasReturnedContext ? contextBlocks : null),
    contextBlocks,
    contextTokens,
    contextChars,
    topScore,
    projectMatchCount,
    unscopedResultCount,
    crossProjectResultCount,
    returnedProject,
    truncated: boolean(root.truncated),
    reportedTokenBudget,
    estimatedAvoidedTokensLow: null,
    estimatedAvoidedTokensHigh: null,
    estimateConfidence: null,
  }, unresolvedSessionIds };
}

export function outcomeFromJson(
  value: unknown,
  lifecycle: MemoryLifecycleStage,
  requestProject: string | null,
): MemoryRequestOutcome | null {
  return extractOutcome(value, lifecycle, requestProject).outcome;
}

export function shouldInspectResponse(lifecycle: MemoryLifecycleStage): boolean {
  return lifecycle === "session_start" || lifecycle === "context_recall" ||
    lifecycle === "file_enrichment" || lifecycle === "manual_search" || lifecycle === "memory_save";
}

export function tapJsonResponseMetadata(
  source: Readable,
  lifecycle: MemoryLifecycleStage,
  project: string | null,
  onOutcome: (outcome: MemoryRequestOutcome | null, unresolvedSessionIds: string[]) => void,
): Readable {
  let total = 0;
  let collecting = true;
  let chunks: Buffer[] = [];
  const tap = new Transform({
    transform(chunk: Buffer | string, encoding, callback) {
      if (collecting) {
        const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding);
        total += bytes.length;
        if (total <= RESPONSE_METADATA_BODY_MAX) chunks.push(Buffer.from(bytes));
        else {
          collecting = false;
          chunks = [];
        }
      }
      callback(null, chunk);
    },
    flush(callback) {
      let extraction: OutcomeExtraction = { outcome: null, unresolvedSessionIds: [] };
      if (collecting) {
        try {
          extraction = extractOutcome(JSON.parse(Buffer.concat(chunks, total).toString("utf8")), lifecycle, project);
        } catch {
          extraction = { outcome: null, unresolvedSessionIds: [] };
        }
      }
      chunks = [];
      onOutcome(extraction.outcome, extraction.unresolvedSessionIds);
      callback();
    },
  });
  source.once("error", (error) => tap.destroy(error));
  source.pipe(tap);
  return tap;
}
