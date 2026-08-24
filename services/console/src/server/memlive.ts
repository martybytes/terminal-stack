// WebSocket client for agentmemory's mem-live viewer stream.
//
// The upstream message shape is not a stable contract, so parsing is
// deliberately permissive: pull whatever fields exist, classify anything
// whose type/name mentions "compressed" as kind "compressed", and silently
// skip messages we cannot make sense of. Never throw.

import { WebSocket } from "ws";
import { config } from "./config.js";
import { getSecret } from "./secret.js";
import type { ObservationEvent } from "../shared/types.js";

const EXCERPT_MAX = 280;
const MAX_BACKOFF_MS = 30_000;

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function firstString(...vals: unknown[]): string | null {
  for (const v of vals) {
    if (typeof v === "string" && v.length > 0) return v;
  }
  return null;
}

function firstNumber(...vals: unknown[]): number | null {
  for (const v of vals) {
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

function toEpochMs(...vals: unknown[]): number {
  for (const v of vals) {
    if (typeof v === "number" && Number.isFinite(v) && v > 0) {
      return v > 1e12 ? v : v * 1000; // epoch seconds vs epoch ms
    }
    if (typeof v === "string") {
      const parsed = Date.parse(v);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return Date.now();
}

function toEvent(msg: unknown): ObservationEvent | null {
  const rec = asRecord(msg);
  if (!rec) return null;

  // The generic stream wraps payloads as {type:"stream", event:{type, event_type, data}}.
  const env = asRecord(rec.event) ?? rec;
  const data =
    asRecord(env.data) ?? asRecord(env.payload) ?? asRecord(rec.data) ?? asRecord(rec.payload) ?? env;
  const obs = asRecord(data.observation) ?? asRecord(env.observation) ?? data;

  const typeBlob = [rec.event_type, rec.type, env.event_type, env.type, env.name, data.event_type, data.event, data.type]
    .filter((v): v is string => typeof v === "string")
    .join(" ")
    .toLowerCase();
  const kind: "raw" | "compressed" = typeBlob.includes("compressed") ? "compressed" : "raw";

  const excerptRaw = firstString(obs.excerpt, obs.narrative, obs.subtitle, obs.content, obs.text);

  const event: ObservationEvent = {
    ts: toEpochMs(obs.timestamp, data.timestamp, rec.timestamp, rec.ts),
    kind,
    sessionId: firstString(obs.sessionId, obs.session_id, data.sessionId, data.session_id, rec.sessionId, rec.session_id),
    agent: firstString(obs.agentId, obs.agent_id, data.agentId, data.agent_id),
    type: firstString(obs.type, obs.observationType, obs.observation_type),
    title: firstString(obs.title, data.title, rec.title),
    excerpt: excerptRaw === null ? null : excerptRaw.slice(0, EXCERPT_MAX),
    importance: firstNumber(obs.importance, data.importance),
  };

  // Join-acks / sync frames carry none of these — not observations, skip.
  if (!event.sessionId && !event.title && !event.type && !event.excerpt) return null;
  return event;
}

export function startMemLive(handlers: {
  onEvent(e: ObservationEvent): void;
  onState(connected: boolean): void;
}): void {
  // Two connection styles, mirroring the stock viewer: a DIRECT per-stream
  // path (ws://host:3112/stream/mem-live/viewer) on newer engines, and the
  // GENERIC root socket plus an explicit join frame on engines where the
  // direct path 404s (iii 0.11.x does — verified live). Try direct first;
  // after DIRECT_FAILURE_THRESHOLD failures stick to generic.
  const DIRECT_URL = config.upstreamWs + "/stream/mem-live/viewer";
  const GENERIC_URL = config.upstreamWs + "/";
  const DIRECT_FAILURE_THRESHOLD = 2;
  let directFailures = 0;
  let delayMs = 1_000;

  const useDirect = (): boolean => directFailures < DIRECT_FAILURE_THRESHOLD;

  const scheduleReconnect = (): void => {
    const jitter = Math.floor(Math.random() * 500);
    const wait = Math.min(delayMs, MAX_BACKOFF_MS) + jitter;
    delayMs = Math.min(delayMs * 2, MAX_BACKOFF_MS);
    setTimeout(connect, wait);
  };

  const connect = (): void => {
    void (async () => {
      // The stream may require the same bearer as the REST API; sending it
      // is harmless when it does not.
      const secret = await getSecret();
      const direct = useDirect();
      const url = direct ? DIRECT_URL : GENERIC_URL;
      const ws = secret
        ? new WebSocket(url, { headers: { authorization: `Bearer ${secret}` } })
        : new WebSocket(url);

      attachHandlers(ws, direct);
    })().catch(() => {
      // new WebSocket() throws synchronously on a malformed UPSTREAM_WS and
      // getSecret() can reject; without this catch the void'd rejection is
      // fatal on modern Node and takes the whole console (proxy included)
      // down. No handlers were attached yet, so no "close" will fire — this
      // is the only place that keeps the reconnect loop alive.
      try {
        handlers.onState(false);
      } catch {
        // ignore
      }
      scheduleReconnect();
    });
  };

  const attachHandlers = (ws: WebSocket, direct: boolean): void => {
    let opened = false;

    ws.on("open", () => {
      opened = true;
      delayMs = 1_000; // reset backoff on a successful connection
      if (direct) directFailures = 0;
      if (!direct) {
        // The generic socket delivers nothing until we join the stream group
        // (same frame the stock viewer sends).
        try {
          ws.send(
            JSON.stringify({
              type: "join",
              data: {
                subscriptionId: `console-${Date.now()}`,
                streamName: "mem-live",
                groupId: "viewer",
              },
            }),
          );
        } catch {
          // send failures surface as a close; the reconnect handles it
        }
      }
      try {
        handlers.onState(true);
      } catch {
        // handler errors never take the client down
      }
    });

    // The direct path 404s on engines without per-stream routes; ws emits
    // that as "unexpected-response" (no open, no close), so drive the
    // fallback + reconnect from here.
    ws.on("unexpected-response", (_req, res) => {
      if (direct) directFailures += 1;
      try {
        res.destroy();
      } catch {
        // ignore
      }
      try {
        handlers.onState(false);
      } catch {
        // ignore
      }
      scheduleReconnect();
    });

    ws.on("message", (data) => {
      try {
        const parsed: unknown = JSON.parse(data.toString());
        const event = toEvent(parsed);
        if (event) handlers.onEvent(event);
      } catch {
        // Non-JSON or unexpected shape: skip it.
      }
    });

    ws.on("error", () => {
      // Swallow; "close" always follows and drives the reconnect.
    });

    ws.on("close", () => {
      if (direct && !opened) directFailures += 1;
      try {
        handlers.onState(false);
      } catch {
        // ignore
      }
      scheduleReconnect();
    });
  };

  connect();
}
