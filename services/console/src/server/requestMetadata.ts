// Exact project attribution for proxied requests.
//
// Request bodies can contain memory contents, so this module never adds a
// body (or a body fragment) to a capture record. For small JSON requests it
// taps the existing proxy stream, forwards every byte unchanged, and keeps a
// bounded in-memory copy only until it can extract the project/session scalar
// fields. Oversized, compressed, malformed, or non-JSON bodies are ignored.

import { Transform, type Readable } from "node:stream";

export const REQUEST_METADATA_BODY_MAX = 64 * 1024;
const METADATA_VALUE_MAX = 512;

export interface RequestMetadata {
  project: string | null;
  sessionId: string | null;
  operation: string | null;
  tokenBudget: number | null;
}

export interface RequestMetadataState {
  queryProject: string | null;
  querySessionId: string | null;
  bodyProject: string | null;
  bodySessionId: string | null;
  queryOperation: string | null;
  bodyOperation: string | null;
  queryTokenBudget: number | null;
  bodyTokenBudget: number | null;
}

const EMPTY: RequestMetadata = { project: null, sessionId: null, operation: null, tokenBudget: null };

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function metadataString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const clean = value.trim();
  return clean.length > 0 && clean.length <= METADATA_VALUE_MAX ? clean : null;
}

function metadataBudget(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : typeof value === "string" && value.trim() ? Number(value) : NaN;
  return Number.isFinite(parsed) && parsed > 0 && parsed <= 1_000_000 ? Math.floor(parsed) : null;
}

function metadataFromRecord(value: unknown): RequestMetadata {
  const record = asRecord(value);
  if (!record) return EMPTY;
  const args = asRecord(record.arguments);
  return {
    project: metadataString(record.project) ?? metadataString(args?.project),
    sessionId:
      metadataString(record.sessionId) ??
      metadataString(record.session_id) ??
      metadataString(args?.sessionId) ??
      metadataString(args?.session_id),
    operation: metadataString(record.name) ?? metadataString(record.operation),
    tokenBudget:
      metadataBudget(record.tokenBudget) ?? metadataBudget(record.token_budget) ??
      metadataBudget(record.budget) ?? metadataBudget(args?.tokenBudget) ??
      metadataBudget(args?.token_budget) ?? metadataBudget(args?.budget),
  };
}

export function createRequestMetadataState(path: string): RequestMetadataState {
  let project: string | null = null;
  let sessionId: string | null = null;
  let operation: string | null = null;
  let tokenBudget: number | null = null;
  try {
    const query = new URL(path, "http://proxy.invalid").searchParams;
    project = metadataString(query.get("project"));
    sessionId = metadataString(query.get("sessionId")) ?? metadataString(query.get("session_id"));
    operation = metadataString(query.get("operation")) ?? metadataString(query.get("name"));
    tokenBudget = metadataBudget(query.get("tokenBudget")) ?? metadataBudget(query.get("token_budget")) ?? metadataBudget(query.get("budget"));
  } catch {
    // Invalid URLs are still proxyable; they simply cannot be attributed.
  }
  return {
    queryProject: project,
    querySessionId: sessionId,
    bodyProject: null,
    bodySessionId: null,
    queryOperation: operation,
    bodyOperation: null,
    queryTokenBudget: tokenBudget,
    bodyTokenBudget: null,
  };
}

export function resolvedRequestMetadata(state: RequestMetadataState): RequestMetadata {
  return {
    // The operation payload is authoritative when both locations are present.
    project: state.bodyProject ?? state.queryProject,
    sessionId: state.bodySessionId ?? state.querySessionId,
    operation: state.bodyOperation ?? state.queryOperation,
    tokenBudget: state.bodyTokenBudget ?? state.queryTokenBudget,
  };
}

function isJsonContentType(contentType: string | undefined): boolean {
  if (!contentType) return false;
  const type = contentType.split(";", 1)[0].trim().toLowerCase();
  return type === "application/json" || (type.startsWith("application/") && type.endsWith("+json"));
}

function isIdentityEncoding(contentEncoding: string | undefined): boolean {
  if (!contentEncoding) return true;
  return contentEncoding.trim().toLowerCase() === "identity";
}

export function isInspectableJson(headers: {
  contentType?: string;
  contentEncoding?: string;
}): boolean {
  return isJsonContentType(headers.contentType) && isIdentityEncoding(headers.contentEncoding);
}

export function tapJsonRequestMetadata(
  source: Readable,
  state: RequestMetadataState,
  headers: {
    contentType?: string;
    contentEncoding?: string;
    contentLength?: string;
  },
  onResolved?: () => void,
): Readable {
  if (!isInspectableJson(headers)) {
    onResolved?.();
    return source;
  }

  const declaredLength = headers.contentLength === undefined ? null : Number(headers.contentLength);
  if (declaredLength !== null && Number.isFinite(declaredLength) && declaredLength > REQUEST_METADATA_BODY_MAX) {
    onResolved?.();
    return source;
  }

  let total = 0;
  let collecting = true;
  let chunks: Buffer[] = [];

  const tap = new Transform({
    transform(chunk: Buffer | string, encoding, callback) {
      if (collecting) {
        const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding);
        total += bytes.length;
        if (total <= REQUEST_METADATA_BODY_MAX) {
          chunks.push(Buffer.from(bytes));
        } else {
          collecting = false;
          chunks = [];
        }
      }
      callback(null, chunk);
    },
    flush(callback) {
      if (collecting) {
        try {
          const metadata = metadataFromRecord(JSON.parse(Buffer.concat(chunks, total).toString("utf8")));
          state.bodyProject = metadata.project;
          state.bodySessionId = metadata.sessionId;
          state.bodyOperation = metadata.operation;
          state.bodyTokenBudget = metadata.tokenBudget;
        } catch {
          // Attribution failure must never affect transparent proxying.
        }
      }
      chunks = [];
      onResolved?.();
      callback();
    },
  });

  source.once("error", (error) => tap.destroy(error));
  source.pipe(tap);
  return tap;
}
