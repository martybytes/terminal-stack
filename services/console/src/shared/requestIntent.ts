import type { RequestRecord } from "./types.js";
import { requestLifecycle } from "./memoryLifecycle.js";

export const REQUEST_INTENTS = ["lookup", "write", "health", "admin", "other"] as const;
export type RequestIntent = (typeof REQUEST_INTENTS)[number];
export type RequestIntentCounts = Record<RequestIntent, number>;

export function emptyRequestIntents(): RequestIntentCounts {
  return { lookup: 0, write: 0, health: 0, admin: 0, other: 0 };
}

export function requestIntent(
  request: Pick<RequestRecord, "method" | "path" | "operation">,
): RequestIntent {
  const method = request.method.trim().toUpperCase();
  const lifecycle = requestLifecycle(request);
  if (lifecycle === "health") return "health";
  if (lifecycle === "admin") return "admin";
  if (lifecycle === "session_start" || lifecycle === "context_recall" || lifecycle === "file_enrichment" || lifecycle === "manual_search") return "lookup";
  if (lifecycle !== "other") return "write";
  if (method === "DELETE" || method === "PUT" || method === "PATCH") return "write";
  if (method !== "POST") return "other";
  if (request.path.split("?", 1)[0]?.replace(/\/$/, "") === "/agentmemory/mcp/call") return "other";
  return "write";
}
