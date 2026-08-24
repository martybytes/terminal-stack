import { randomUUID } from "node:crypto";
import type { OperationPreview, OperationsSnapshot } from "../shared/types.js";
import { llmTelemetry } from "./llmTelemetry.js";
import { store } from "./observations.js";
import { upstreamJson } from "./upstream.js";

type PreviewAction = "maintenance" | "recovery";
interface ScopeBody {
  project?: string;
  allProjects?: boolean;
  sessionId?: string;
  skipCompression?: boolean;
  skipSummary?: boolean;
  skipGraph?: boolean;
}

const previews = new Map<string, { action: PreviewAction; body: ScopeBody; expiresAt: number }>();
const recentRuns = new Map<string, number>();
const PREVIEW_TTL_MS = 5 * 60_000;
const DUPLICATE_WINDOW_MS = 15_000;

function cleanBody(body: ScopeBody, requireScope: boolean): ScopeBody {
  const project = typeof body.project === "string" ? body.project.trim().slice(0, 200) : "";
  const sessionId = typeof body.sessionId === "string" ? body.sessionId.trim().slice(0, 200) : "";
  const allProjects = body.allProjects === true;
  if (project && allProjects) throw new Error("Choose one project or all projects, not both");
  if (requireScope && !project && !allProjects) throw new Error("Select a project or explicitly choose all projects");
  return {
    ...(project ? { project } : {}),
    ...(allProjects ? { allProjects: true } : {}),
    ...(sessionId ? { sessionId } : {}),
    ...(body.skipCompression === true ? { skipCompression: true } : {}),
    ...(body.skipSummary === true ? { skipSummary: true } : {}),
    ...(body.skipGraph === true ? { skipGraph: true } : {}),
  };
}

function projectedCost(preview: OperationPreview): number {
  const calls = llmTelemetry.snapshot().calls.filter((call) => call.estimatedCostNanos !== null);
  const average = (family: string): number => {
    const rows = calls.filter((call) => call.family === family);
    return rows.length > 0 ? rows.reduce((sum, call) => sum + (call.estimatedCostNanos ?? 0), 0) / rows.length : 0;
  };
  return Math.round(
    (preview.queuedCompression ?? 0) * average("compression") +
    (preview.projectedSummaryJobs ?? 0) * average("summary") +
    (preview.projectedGraphJobs ?? 0) * average("graph") +
    (preview.queuedJobs ?? 0) * average("consolidation"),
  );
}

function issuePreview(action: PreviewAction, body: ScopeBody, preview: OperationPreview): OperationPreview {
  const now = Date.now();
  for (const [token, item] of previews) if (item.expiresAt <= now) previews.delete(token);
  const token = randomUUID();
  const expiresAt = now + PREVIEW_TTL_MS;
  previews.set(token, { action, body, expiresAt });
  return { ...preview, projectedCostNanos: projectedCost(preview), confirmationToken: token, confirmationExpiresAt: expiresAt };
}

function consumePreview(action: PreviewAction, token: string | undefined): ScopeBody {
  if (!token) throw new Error("Run requires a current preview confirmation token");
  const preview = previews.get(token);
  previews.delete(token);
  if (!preview || preview.action !== action || preview.expiresAt <= Date.now()) throw new Error("Preview expired; preview the operation again");
  return preview.body;
}

async function runOnce(key: string, run: () => Promise<unknown>): Promise<unknown> {
  const now = Date.now();
  const previous = recentRuns.get(key);
  if (previous !== undefined && now - previous < DUPLICATE_WINDOW_MS) throw new Error("This operation was already queued moments ago");
  recentRuns.set(key, now);
  try { return await run(); } catch (error) { recentRuns.delete(key); throw error; }
}

async function requiredUpstream(path: string, body: ScopeBody, timeoutMs = 30_000): Promise<Record<string, unknown>> {
  const result = await upstreamJson<Record<string, unknown>>(path, { method: "POST", body, timeoutMs });
  if (!result) throw new Error("AgentMemory did not accept the operation");
  return result;
}

export const operations = {
  async snapshot(): Promise<OperationsSnapshot> {
    const sessions = await store.sessions();
    const llm = llmTelemetry.snapshot();
    const { estimatedTodayNanos: _today, estimatedWindowNanos: _window, pricedCallsToday: _priced, unpricedCallsToday: _unpriced, ...billing } = llm.cost;
    return {
      ts: Date.now(), upstreamOk: llm.upstreamOk,
      projects: [...new Set(sessions.map((session) => session.project).filter((value): value is string => Boolean(value)))].sort(),
      sessions, activeJobs: llm.jobs.filter((job) => job.status === "queued" || job.status === "running"), queue: llm.queue, billing,
      costApplicability: llm.config.costApplicability, costReason: llm.config.costReason,
    };
  },
  async preview(action: PreviewAction, raw: ScopeBody): Promise<OperationPreview> {
    const body = cleanBody(raw, action === "maintenance");
    const path = action === "maintenance" ? "/agentmemory/llm/maintenance/preview" : "/agentmemory/llm/recovery/preview";
    const result = await requiredUpstream(path, body, 120_000) as unknown as OperationPreview;
    return issuePreview(action, body, result);
  },
  async run(action: PreviewAction, token: string | undefined): Promise<unknown> {
    const body = consumePreview(action, token);
    const path = action === "maintenance" ? "/agentmemory/llm/maintenance" : "/agentmemory/llm/requeue-pending";
    return runOnce(`${action}:${JSON.stringify(body)}`, () => requiredUpstream(path, body, 120_000));
  },
  async summarize(raw: ScopeBody): Promise<unknown> {
    const body = cleanBody(raw, false);
    if (!body.sessionId) throw new Error("Select a session to summarize");
    return runOnce(`summary:${body.sessionId}`, () => requiredUpstream("/agentmemory/llm/summarize", body, 120_000));
  },
  async rebuildGraphSnapshot(): Promise<unknown> {
    return runOnce("graph-snapshot", () => requiredUpstream("/agentmemory/graph/snapshot-rebuild", {}, 120_000));
  },
};
