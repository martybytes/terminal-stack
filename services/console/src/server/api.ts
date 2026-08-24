// UI listener: JSON API, health endpoint, static SPA, and the /ws upgrade
// hook (attached by the caller once the server is listening).
//
// /healthz always answers 200 — the console itself being up is the thing
// being probed; upstream state is reported in the body, not the status code.

import Fastify from "fastify";
import fastifyStatic from "@fastify/static";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { config } from "./config.js";
import { upstreamOk } from "./upstream.js";
import { capture } from "./capture.js";
import { llmTelemetry } from "./llmTelemetry.js";
import { store } from "./observations.js";
import { history } from "./history.js";
import { operations } from "./operations.js";
import { billing, BillingCooldownError } from "./billing.js";
import { enrichSessions, memoryEffectiveness } from "./memoryEffectiveness.js";
import { memoryTokenEstimator } from "./memoryTokenEstimator.js";
import { parseReportQuery, reportCsv, type ReportQueryInput } from "./reports.js";
import type { DashboardSnapshot, ReportSection } from "../shared/types.js";

function intParam(v: string | undefined): number | undefined {
  if (v === undefined || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? Math.floor(n) : undefined;
}

function numParam(v: string | undefined): number | undefined {
  if (v === undefined || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export async function startUi(opts: {
  buildSnapshot: () => DashboardSnapshot;
  hubAttach: (server: import("node:http").Server) => void;
}): Promise<void> {
  const app = Fastify({ logger: false, bodyLimit: 64 * 1024 });

  app.get("/healthz", async () => ({
    ok: true,
    upstreamOk: await upstreamOk(),
    history: history.status(),
    version: "0.1.0",
  }));

  app.get("/api/dashboard", async () => opts.buildSnapshot());

  app.get<{ Querystring: { limit?: string } }>("/api/requests", async (request) => {
    const limit = intParam(request.query.limit) ?? 200;
    return capture.recent(Math.min(config.ringSize, Math.max(1, limit)));
  });

  app.get("/api/sessions", async () => enrichSessions(await store.sessions(), capture.recent(config.ringSize)));

  app.get("/api/projects", async () => {
    const [sessions, inventory] = await Promise.all([store.sessions(), store.memoryInventory()]);
    memoryTokenEstimator.seed(sessions);
    const now = Date.now();
    const derivedByProject: Record<string, { queued: number; running: number; failed: number; oldestWaitMs: number | null }> = {};
    for (const job of llmTelemetry.snapshot().jobs) {
      const project = job.project?.trim();
      if (!project || (job.status !== "queued" && job.status !== "running" && job.status !== "failed")) continue;
      const counts = derivedByProject[project] ??= { queued: 0, running: 0, failed: 0, oldestWaitMs: null };
      counts[job.status]++;
      if (job.status === "queued") counts.oldestWaitMs = Math.max(counts.oldestWaitMs ?? 0, now - job.queuedAt);
    }
    return capture.projects(sessions, inventory.byProject, inventory.qualityByProject, derivedByProject);
  });

  app.get("/api/memory-effectiveness", async () => {
    const [sessions, inventory] = await Promise.all([store.sessions(), store.memoryInventory()]);
    memoryTokenEstimator.seed(sessions);
    return memoryEffectiveness(capture.recent(config.ringSize), inventory);
  });

  app.get("/api/memory-effectiveness/history", async (_request, reply) => {
    try {
      return await history.contextAvoidedHistory();
    } catch (error) {
      return reply.code(503).send({ error: "history unavailable", detail: error instanceof Error ? error.message : String(error) });
    }
  });

  app.get("/api/llm", async () => {
    const snapshot = llmTelemetry.snapshot();
    try {
      const persisted = await history.costSnapshot();
      return {
        ...snapshot,
        cost: {
          ...snapshot.cost,
          estimatedTodayNanos: snapshot.config.costApplicability === "local"
            ? 0
            : Math.max(snapshot.cost.estimatedTodayNanos, persisted.estimatedTodayNanos),
          billedMonthToDateNanos: snapshot.cost.billedMonthToDateNanos ?? persisted.billedMonthToDateNanos,
        },
      };
    } catch {
      return snapshot;
    }
  });

  app.get("/api/operations", async () => operations.snapshot());

  const hasActionHeader = (headers: Record<string, unknown>): boolean => headers["x-agent007memory-action"] === "1";
  const operationReply = async (reply: import("fastify").FastifyReply, run: () => Promise<unknown>): Promise<unknown> => {
    try { return await run(); }
    catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      const badRequest = detail.includes("Select") || detail.includes("Choose") || detail.includes("preview") || detail.includes("confirmation") || detail.includes("header") || detail.includes("already queued");
      return reply.code(badRequest ? 409 : 502).send({ error: badRequest ? "operation not accepted" : "upstream operation failed", detail });
    }
  };
  app.post<{ Params: { action: "maintenance" | "recovery" }; Body: Record<string, unknown> }>("/api/operations/:action/preview", async (request, reply) => {
    if (!hasActionHeader(request.headers)) return reply.code(403).send({ error: "operation confirmation header required" });
    if (request.params.action !== "maintenance" && request.params.action !== "recovery") return reply.code(404).send({ error: "unknown operation" });
    return operationReply(reply, () => operations.preview(request.params.action, request.body ?? {}));
  });
  app.post<{ Params: { action: "maintenance" | "recovery" }; Body: { confirmationToken?: string } }>("/api/operations/:action/run", async (request, reply) => {
    if (!hasActionHeader(request.headers)) return reply.code(403).send({ error: "operation confirmation header required" });
    if (request.params.action !== "maintenance" && request.params.action !== "recovery") return reply.code(404).send({ error: "unknown operation" });
    return operationReply(reply, () => operations.run(request.params.action, request.body?.confirmationToken));
  });
  app.post<{ Body: Record<string, unknown> }>("/api/operations/summarize", async (request, reply) => {
    if (!hasActionHeader(request.headers)) return reply.code(403).send({ error: "operation confirmation header required" });
    return operationReply(reply, () => operations.summarize(request.body ?? {}));
  });
  app.post("/api/operations/graph-snapshot/rebuild", async (request, reply) => {
    if (!hasActionHeader(request.headers)) return reply.code(403).send({ error: "operation confirmation header required" });
    return operationReply(reply, () => operations.rebuildGraphSnapshot());
  });
  app.post("/api/operations/billing/sync", async (request, reply) => {
    if (!hasActionHeader(request.headers)) return reply.code(403).send({ error: "operation confirmation header required" });
    if (llmTelemetry.snapshot().config.costApplicability === "local") {
      return reply.code(409).send({ error: "billing refresh is disabled for local inference", detail: llmTelemetry.snapshot().config.costReason });
    }
    try {
      await billing.sync();
      return { success: true, billing: billing.snapshot() };
    } catch (error) {
      if (error instanceof BillingCooldownError) {
        return reply.code(429).send({
          error: "billing refresh cooling down",
          detail: error.message,
          nextAllowedAt: error.nextAllowedAt,
          billing: billing.snapshot(),
        });
      }
      return operationReply(reply, async () => { throw error; });
    }
  });

  app.get("/api/reports/meta", async (_request, reply) => {
    try {
      return await history.meta();
    } catch (error) {
      return reply.code(503).send({ error: "history unavailable", detail: error instanceof Error ? error.message : String(error) });
    }
  });

  const reportSections = new Set<ReportSection>(["summary", "projects", "memory", "llm", "system"]);
  app.get<{ Params: { section: string }; Querystring: ReportQueryInput }>(
    "/api/reports/:section",
    async (request, reply) => {
      if (!reportSections.has(request.params.section as ReportSection)) {
        return reply.code(404).send({ error: "unknown report section" });
      }
      try {
        const query = parseReportQuery(request.params.section as ReportSection, request.query);
        return await history.report(query);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const status = message.includes("range") || message.includes("from and to") ? 400 : 503;
        return reply.code(status).send({ error: status === 400 ? "invalid report query" : "history unavailable", detail: message });
      }
    },
  );

  app.get<{ Params: { section: string }; Querystring: ReportQueryInput }>(
    "/api/reports/:section.csv",
    async (request, reply) => {
      if (!reportSections.has(request.params.section as ReportSection)) {
        return reply.code(404).send({ error: "unknown report section" });
      }
      try {
        const section = request.params.section as ReportSection;
        const query = parseReportQuery(section, request.query);
        const current = await history.report(query) as Parameters<typeof reportCsv>[1];
        let previous: Parameters<typeof reportCsv>[2] = null;
        const hasPrevious =
          section === "summary" ? "previous" in current && current.previous !== null
            : section === "projects" ? "rows" in current && current.rows.some((row) => "previousRequests" in row && row.previousRequests !== null)
              : section === "memory" ? "previous" in current && current.previous !== null
                : section === "llm" ? "rows" in current && current.rows.some((row) => "previousCalls" in row && row.previousCalls !== null)
                  : "previousRestartCount" in current && current.previousRestartCount !== null;
        if (query.compare && hasPrevious) {
          const duration = query.to - query.from;
          previous = await history.report({
            ...query,
            from: query.from - duration,
            to: query.from,
            compare: false,
          }) as Parameters<typeof reportCsv>[2];
        }
        const filename = `agent007memory-${section}-${new Date(query.from).toISOString().slice(0, 10)}.csv`;
        return reply
          .header("content-type", "text/csv; charset=utf-8")
          .header("content-disposition", `attachment; filename="${filename}"`)
          .send(reportCsv(section, current, previous));
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const status = message.includes("range") || message.includes("from and to") ? 400 : 503;
        return reply.code(status).send({ error: status === 400 ? "invalid report query" : "history unavailable", detail: message });
      }
    },
  );

  app.get<{
    Querystring: {
      sessionId?: string;
      sort?: string;
      page?: string;
      size?: string;
      types?: string;
      minImportance?: string;
    };
  }>("/api/timeline", async (request) => {
    const { sessionId, sort, page, size, types, minImportance } = request.query;
    return store.timeline({
      sessionId: sessionId || undefined,
      sort: sort === "oldest" ? "oldest" : sort === "newest" ? "newest" : undefined,
      page: intParam(page),
      size: intParam(size),
      types: types
        ? types
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean)
        : undefined,
      minImportance: numParam(minImportance),
    });
  });

  app.get<{ Querystring: { query?: string; page?: string; size?: string; type?: string; project?: string } }>(
    "/api/memories",
    async (request) => {
      const { query, page, size, type, project } = request.query;
      return store.memories({
        query: query || undefined,
        page: intParam(page),
        size: intParam(size),
        type: type || undefined,
        project: project || undefined,
      });
    },
  );

  // Static SPA. Compiled server lives in dist/server/, so ../web is dist/web.
  // In dev (tsx from src/server) that resolves to src/web, which has no
  // index.html — vite serves the SPA there, so we skip static entirely.
  const webRoot = fileURLToPath(new URL("../web", import.meta.url));
  const hasStatic = existsSync(join(webRoot, "index.html"));
  if (hasStatic) {
    await app.register(fastifyStatic, { root: webRoot });
    // SPA fallback: any unknown GET outside /api serves the app shell.
    app.setNotFoundHandler((request, reply) => {
      if (request.method === "GET" && !request.url.startsWith("/api")) {
        return reply.sendFile("index.html");
      }
      return reply.code(404).send({ error: "not found" });
    });
  }

  await app.ready();
  await app.listen({ port: config.uiPort, host: config.host });
  opts.hubAttach(app.server);
}
