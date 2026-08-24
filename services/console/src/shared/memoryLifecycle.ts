import type { RequestRecord } from "./types.js";

export const MEMORY_LIFECYCLE_STAGES = [
  "session_start",
  "context_recall",
  "file_enrichment",
  "manual_search",
  "observation_capture",
  "memory_save",
  "compress",
  "summarize",
  "graph_extract",
  "consolidate",
  "turn_end",
  "session_end",
  "health",
  "admin",
  "other",
] as const;

export type MemoryLifecycleStage = (typeof MEMORY_LIFECYCLE_STAGES)[number];
export type MemoryLifecycleCounts = Record<MemoryLifecycleStage, number>;

const HEALTH_ROUTES = new Set([
  "/agentmemory/config/flags",
  "/agentmemory/health",
  "/agentmemory/livez",
  "/agentmemory/llm/telemetry",
]);

const CONTEXT_ROUTES = new Set(["/agentmemory/context"]);
const ENRICH_ROUTES = new Set(["/agentmemory/enrich", "/agentmemory/file-context"]);
const SEARCH_ROUTES = new Set([
  "/agentmemory/facets/query",
  "/agentmemory/graph/query",
  "/agentmemory/insights/search",
  "/agentmemory/lessons/search",
  "/agentmemory/patterns",
  "/agentmemory/search",
  "/agentmemory/smart-search",
  "/agentmemory/timeline",
  "/agentmemory/verify",
  "/agentmemory/vision-search",
]);

const SEARCH_TOOL = /(?:^|_)(?:audit|commits?|diagnose|export|feed|file_history|frontier|get|history|list|next|patterns|profile|query|recall|relations|search|sessions|timeline|verify)(?:_|$)/;
const SAVE_TOOL = /(?:^|_)(?:append|checkpoint|create|crystallize|save|send|share|snapshot|tag|update)(?:_|$)/;
const CONSOLIDATE_TOOL = /(?:^|_)(?:consolidate|forget|heal|promote|reflect|replace|run|strengthen|sync|trigger)(?:_|$)/;

function pathname(path: string): string {
  const query = path.indexOf("?");
  return (query === -1 ? path : path.slice(0, query)).replace(/\/$/, "") || "/";
}

export function emptyMemoryLifecycleCounts(): MemoryLifecycleCounts {
  return {
    session_start: 0,
    context_recall: 0,
    file_enrichment: 0,
    manual_search: 0,
    observation_capture: 0,
    memory_save: 0,
    compress: 0,
    summarize: 0,
    graph_extract: 0,
    consolidate: 0,
    turn_end: 0,
    session_end: 0,
    health: 0,
    admin: 0,
    other: 0,
  };
}

export function requestLifecycle(
  request: Pick<RequestRecord, "method" | "path" | "operation">,
): MemoryLifecycleStage {
  const method = request.method.trim().toUpperCase();
  const route = pathname(request.path);
  const operation = request.operation?.trim().toLowerCase() ?? "";

  if (HEALTH_ROUTES.has(route)) return "health";
  if (route.startsWith("/agentmemory/admin/") || route.startsWith("/agentmemory/diagnostics/")) return "admin";
  if (route === "/agentmemory/mcp/tools" || route === "/agentmemory/viewer") return "admin";
  if (route === "/agentmemory/session/start") return "session_start";
  if (route === "/agentmemory/turn/end") return "turn_end";
  if (route === "/agentmemory/session/end") return "session_end";
  if (CONTEXT_ROUTES.has(route)) return "context_recall";
  if (ENRICH_ROUTES.has(route)) return "file_enrichment";
  if (SEARCH_ROUTES.has(route)) return "manual_search";
  if (route === "/agentmemory/observe") return "observation_capture";
  if (route === "/agentmemory/remember") return "memory_save";
  if (route === "/agentmemory/compress") return "compress";
  if (route === "/agentmemory/summarize") return "summarize";
  if (route.startsWith("/agentmemory/graph/")) return route.endsWith("/query") ? "manual_search" : "graph_extract";
  if (route.startsWith("/agentmemory/consolidat")) return "consolidate";

  if (route === "/agentmemory/mcp/call") {
    if (SEARCH_TOOL.test(operation)) return "manual_search";
    if (operation.includes("compress")) return "compress";
    if (operation.includes("summar")) return "summarize";
    if (operation.includes("graph") && !operation.includes("query")) return "graph_extract";
    if (CONSOLIDATE_TOOL.test(operation)) return "consolidate";
    if (SAVE_TOOL.test(operation)) return "memory_save";
  }

  if (method === "GET") return "manual_search";
  return "other";
}

export function isRetrievalStage(stage: MemoryLifecycleStage): boolean {
  return stage === "session_start" || stage === "context_recall" || stage === "file_enrichment" || stage === "manual_search";
}

export function isStorageStage(stage: MemoryLifecycleStage): boolean {
  return stage === "observation_capture" || stage === "memory_save";
}

export function lifecycleLabel(stage: MemoryLifecycleStage): string {
  return stage.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
