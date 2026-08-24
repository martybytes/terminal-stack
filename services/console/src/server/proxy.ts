// Reverse proxy for the agentmemory REST listener. Untagged traffic remains
// transparent. Client-tagged paths (/_agent/claude|codex|cursor) lose that
// private prefix before forwarding and receive upstream agentId metadata on
// session/memory writes. Bodies are streamed and never captured; a bounded
// pass-through tap extracts only exact project/session identifiers.

import Fastify, { type FastifyRequest } from "fastify";
import httpProxy from "@fastify/http-proxy";
import { Readable } from "node:stream";
import { config } from "./config.js";
import { capture, normalizeRoute } from "./capture.js";
import { store } from "./observations.js";
import { requestLifecycle, isRetrievalStage, isStorageStage } from "../shared/memoryLifecycle.js";
import type { MemoryRequestOutcome } from "../shared/types.js";
import { shouldInspectResponse, tapJsonResponseMetadata } from "./responseMetadata.js";
import { memoryTokenEstimator } from "./memoryTokenEstimator.js";
import {
  createRequestMetadataState,
  isInspectableJson,
  resolvedRequestMetadata,
  tapJsonRequestMetadata,
  type RequestMetadataState,
} from "./requestMetadata.js";
import {
  attributedPath,
  injectAgentId,
  isAgentPersistenceRoute,
  type AttributedPath,
} from "./requestAgent.js";

function headerValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function fallbackOutcome(
  status: number,
  lifecycle: ReturnType<typeof requestLifecycle>,
  observed: MemoryRequestOutcome | null,
): MemoryRequestOutcome | null {
  if (status === 0 || status >= 400) {
    return {
      kind: "failed", resultCount: null, contextBlocks: null, contextTokens: null,
      contextChars: null, topScore: null, projectMatchCount: null,
      unscopedResultCount: null, crossProjectResultCount: null,
      returnedProject: observed?.returnedProject ?? null, truncated: observed?.truncated ?? null,
      reportedTokenBudget: observed?.reportedTokenBudget ?? null,
      estimatedAvoidedTokensLow: null, estimatedAvoidedTokensHigh: null, estimateConfidence: null,
    };
  }
  if (observed) return observed;
  if (isStorageStage(lifecycle)) {
    return {
      kind: "stored", resultCount: null, contextBlocks: null, contextTokens: null,
      contextChars: null, topScore: null, projectMatchCount: null,
      unscopedResultCount: null, crossProjectResultCount: null, returnedProject: null, truncated: null,
      reportedTokenBudget: null, estimatedAvoidedTokensLow: null,
      estimatedAvoidedTokensHigh: null, estimateConfidence: null,
    };
  }
  if (isRetrievalStage(lifecycle)) {
    return {
      kind: "unknown", resultCount: null, contextBlocks: null, contextTokens: null,
      contextChars: null, topScore: null, projectMatchCount: null,
      unscopedResultCount: null, crossProjectResultCount: null, returnedProject: null, truncated: null,
      reportedTokenBudget: null, estimatedAvoidedTokensLow: null,
      estimatedAvoidedTokensHigh: null, estimateConfidence: null,
    };
  }
  if (lifecycle !== "health" && lifecycle !== "admin" && lifecycle !== "other") {
    return {
      kind: "accepted", resultCount: null, contextBlocks: null, contextTokens: null,
      contextChars: null, topScore: null, projectMatchCount: null,
      unscopedResultCount: null, crossProjectResultCount: null, returnedProject: null, truncated: null,
      reportedTokenBudget: null, estimatedAvoidedTokensLow: null,
      estimatedAvoidedTokensHigh: null, estimateConfidence: null,
    };
  }
  return null;
}

export async function startProxy(): Promise<void> {
  const app = Fastify({ logger: false });

  // Requests whose upstream fetch failed outright (refused / timed out):
  // recorded with status 0 so the UI can tell "upstream unreachable" apart
  // from a genuine upstream 5xx.
  const unreachable = new WeakSet<object>();
  const startTimes = new WeakMap<object, number>();
  const requestMetadata = new WeakMap<object, RequestMetadataState>();
  const requestPaths = new WeakMap<object, AttributedPath>();
  const requestBytes = new WeakMap<object, number>();
  const resolvedProjects = new WeakMap<object, string | null>();
  const responseOutcomes = new WeakMap<object, Promise<MemoryRequestOutcome | null>>();

  const resolveProject = (request: FastifyRequest): Promise<void> => {
    if (resolvedProjects.has(request)) return Promise.resolve();
    const pending = (async () => {
      const metadata = requestMetadata.get(request);
      const exact = metadata ? resolvedRequestMetadata(metadata) : { project: null, sessionId: null, operation: null, tokenBudget: null };
      const project = exact.project ?? (exact.sessionId ? await store.projectForSession(exact.sessionId) : null);
      resolvedProjects.set(request, project);
    })();
    return pending;
  };

  app.addHook("onRequest", async (request) => {
    startTimes.set(request, Date.now());
    const attributed = attributedPath(request.url);
    requestPaths.set(request, attributed);
    requestMetadata.set(request, createRequestMetadataState(attributed.path));
    requestBytes.set(request, Number(request.headers["content-length"] ?? -1));
  });

  app.addHook("onResponse", async (request, reply) => {
    const started = startTimes.get(request);
    const elapsed = reply.elapsedTime;
    const durMs =
      Number.isFinite(elapsed) && elapsed > 0
        ? elapsed
        : started !== undefined
          ? Date.now() - started
          : 0;
    const resLen = reply.getHeader("content-length");
    const attributed = requestPaths.get(request) ?? attributedPath(request.url);
    const metadata = requestMetadata.get(request);
    const exact = metadata
      ? resolvedRequestMetadata(metadata)
      : { project: null, sessionId: null, operation: null, tokenBudget: null };
    if (exact.project && exact.sessionId) {
      store.noteSessionProject(exact.sessionId, exact.project);
    }
    if (attributed.agent && exact.sessionId) {
      store.noteSessionAgent(exact.sessionId, attributed.agent);
    }
    await resolveProject(request);
    const project = resolvedProjects.get(request) ?? exact.project ?? (exact.sessionId ? await store.projectForSession(exact.sessionId) : null);
    const agent = attributed.agent ?? (exact.sessionId ? await store.agentForSession(exact.sessionId) : null);
    const lifecycle = requestLifecycle({ method: request.method, path: attributed.path, operation: exact.operation });
    const status = unreachable.has(request) ? 0 : reply.statusCode;
    const reqBytes = requestBytes.get(request) ?? -1;
    const observedOutcome = fallbackOutcome(status, lifecycle, await (responseOutcomes.get(request) ?? Promise.resolve(null)));
    const outcome = memoryTokenEstimator.decorate({ lifecycle, project, status, reqBytes, outcome: observedOutcome });
    capture.record({
      ts: started ?? Date.now(),
      method: request.method,
      path: attributed.path,
      route: normalizeRoute(attributed.path),
      operation: exact.operation,
      project,
      sessionId: exact.sessionId,
      agent,
      lifecycle,
      requestedTokenBudget: exact.tokenBudget,
      outcome,
      status,
      durMs,
      reqBytes,
      resBytes: Number(resLen ?? -1),
    });
  });

  await app.register(httpProxy, {
    upstream: config.upstreamHttp,
    prefix: "/",
    websocket: false,
    preRewrite: (url) => attributedPath(url).path,
    preHandler: (request, _reply, done) => {
      try {
        const attributed = requestPaths.get(request) ?? attributedPath(request.url);
        requestPaths.set(request, attributed);
        const metadata = requestMetadata.get(request) ?? createRequestMetadataState(attributed.path);
        requestMetadata.set(request, metadata);
        if (request.body instanceof Readable) {
          const bodyHeaders = {
            contentType: headerValue(request.headers["content-type"]),
            contentEncoding: headerValue(request.headers["content-encoding"]),
            contentLength: headerValue(request.headers["content-length"]),
          };
          let body = tapJsonRequestMetadata(request.body, metadata, bodyHeaders, () => {
            void resolveProject(request);
          });
          if (
            attributed.agent &&
            request.method === "POST" &&
            isAgentPersistenceRoute(attributed.path) &&
            isInspectableJson(bodyHeaders)
          ) {
            body = injectAgentId(body, attributed.agent);
            // The streaming transform adds bytes. Let undici frame the body
            // rather than forwarding the caller's now-stale content length.
            delete request.headers["content-length"];
          }
          request.body = body;
        } else {
          void resolveProject(request);
        }
      } catch {
        // Metadata attribution is best-effort and must never block proxying.
      }
      done();
    },
    // Keep-alive undici agent; generous timeouts because upstream functions
    // (mem::compress and friends) legitimately run up to 180 s.
    undici: {
      connections: 128,
      pipelining: 1,
      keepAliveTimeout: 60_000,
      headersTimeout: 190_000,
      bodyTimeout: 190_000,
    },
    replyOptions: {
      onResponse: (request, reply, response) => {
        const attributed = requestPaths.get(request) ?? attributedPath(request.url);
        const metadata = requestMetadata.get(request);
        const exact = metadata
          ? resolvedRequestMetadata(metadata)
          : { project: null, sessionId: null, operation: null, tokenBudget: null };
        const lifecycle = requestLifecycle({ method: request.method, path: attributed.path, operation: exact.operation });
        if (!shouldInspectResponse(lifecycle)) return reply.send(response.stream);
        const requestProject = resolvedProjects.get(request) ?? exact.project;
        const stream = tapJsonResponseMetadata(response.stream, lifecycle, requestProject, (outcome, unresolvedSessionIds) => {
          responseOutcomes.set(request, (async () => {
            if (!outcome || !requestProject || unresolvedSessionIds.length === 0) return outcome;
            const projects = await Promise.all(unresolvedSessionIds.map((sessionId) => store.projectForSession(sessionId)));
            let matches = outcome.projectMatchCount ?? 0;
            let unscoped = outcome.unscopedResultCount ?? 0;
            let cross = outcome.crossProjectResultCount ?? 0;
            for (const project of projects) {
              if (project === null) continue;
              unscoped = Math.max(0, unscoped - 1);
              if (project === requestProject) matches++;
              else cross++;
            }
            return { ...outcome, projectMatchCount: matches, unscopedResultCount: unscoped, crossProjectResultCount: cross };
          })());
        });
        return reply.send(stream);
      },
      onError: (reply, err) => {
        unreachable.add(reply.request);
        try {
          const detail =
            err && typeof err === "object" && "error" in err && err.error instanceof Error
              ? err.error.message
              : "upstream request failed";
          void reply.code(502).send({ error: "upstream unreachable", detail });
        } catch {
          // Headers may already have been flushed mid-stream; nothing to do.
        }
      },
    },
  });

  await app.listen({ port: config.proxyPort, host: config.host });
}
