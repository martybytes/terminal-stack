// Single browser <-> console WebSocket plus the shared live state every page
// reads through useLive(). Plain .ts on purpose — the one element we create
// (the context provider) is built with createElement, no JSX needed.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type {
  MetricsTick,
  DashboardSnapshot,
  RequestRecord,
  ObservationEvent,
  LlmCompletionEvent,
  ProjectFlowEvent,
  WsServerMessage,
} from "../../shared/types";
import { apiGet } from "./api";

export interface LiveState {
  wsConnected: boolean; // browser <-> console socket
  upstreamOk: boolean; // console <-> agentmemory (from ticks / upstream msgs)
  tick: MetricsTick | null;
  snapshot: DashboardSnapshot | null;
  requests: RequestRecord[]; // newest first, capped 500, live-updated
  observations: ObservationEvent[]; // newest first, capped 200
  projectFlows: ProjectFlowEvent[]; // newest first, short-lived visual pulses
  llmCompletions: LlmCompletionEvent[]; // newest first, completion pulses
  paused: boolean;
  setPaused(p: boolean): void; // pause = stop prepending requests (still counts ticks)
}

const REQUEST_CAP = 500;
const OBSERVATION_CAP = 200;
const PROJECT_FLOW_CAP = 500;
const LLM_COMPLETION_CAP = 200;
const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;
const SNAPSHOT_FALLBACK_MS = 3_000;
const SNAPSHOT_REFRESH_MS = 10_000;

const LiveContext = createContext<LiveState | null>(null);

function parseMessage(raw: unknown): WsServerMessage | null {
  if (typeof raw !== "string") return null;
  try {
    const msg = JSON.parse(raw) as unknown;
    if (
      msg !== null &&
      typeof msg === "object" &&
      typeof (msg as { type?: unknown }).type === "string"
    ) {
      return msg as WsServerMessage;
    }
  } catch {
    // not JSON — ignore
  }
  return null;
}

export function LiveProvider(props: { children: ReactNode }): JSX.Element {
  const [wsConnected, setWsConnected] = useState(false);
  const [upstreamOk, setUpstreamOk] = useState(false);
  const [tick, setTick] = useState<MetricsTick | null>(null);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [requests, setRequests] = useState<RequestRecord[]>([]);
  const [observations, setObservations] = useState<ObservationEvent[]>([]);
  const [projectFlows, setProjectFlows] = useState<ProjectFlowEvent[]>([]);
  const [llmCompletions, setLlmCompletions] = useState<LlmCompletionEvent[]>([]);
  const [paused, setPausedState] = useState(false);

  // Refs so the (stable) socket handlers see current values without rebinds.
  const pausedRef = useRef(false);
  const seededRef = useRef(false);
  // Requests arriving while paused are buffered (newest first) and folded
  // back in on resume — pause freezes the view, it never loses traffic.
  const pauseBufferRef = useRef<RequestRecord[]>([]);

  const setPaused = useCallback((p: boolean) => {
    pausedRef.current = p;
    setPausedState(p);
    if (!p) {
      const buffered = pauseBufferRef.current;
      pauseBufferRef.current = [];
      if (buffered.length > 0) {
        setRequests((prev) => {
          const seen = new Set(buffered.map((r) => r.id));
          return [...buffered, ...prev.filter((r) => !seen.has(r.id))].slice(0, REQUEST_CAP);
        });
      }
    }
  }, []);

  const applySnapshot = useCallback((snap: DashboardSnapshot) => {
    seededRef.current = true;
    setSnapshot(snap);
    if (snap.tick) {
      setTick(snap.tick);
      setUpstreamOk(snap.tick.upstreamOk);
    }
    if (pausedRef.current) {
      // Mid-pause (e.g. a reconnect snapshot): keep the frozen list on screen
      // and queue the fresh rows so resume can merge them.
      const seen = new Set(snap.requests.map((r) => r.id));
      pauseBufferRef.current = [
        ...snap.requests,
        ...pauseBufferRef.current.filter((r) => !seen.has(r.id)),
      ].slice(0, REQUEST_CAP);
    } else {
      setRequests(snap.requests.slice(0, REQUEST_CAP));
    }
  }, []);

  const handleMessage = useCallback(
    (msg: WsServerMessage) => {
      switch (msg.type) {
        case "snapshot":
          applySnapshot(msg.data);
          break;
        case "request":
          if (pausedRef.current) {
            pauseBufferRef.current = [msg.data, ...pauseBufferRef.current].slice(0, REQUEST_CAP);
          } else {
            setRequests((prev) => [msg.data, ...prev].slice(0, REQUEST_CAP));
          }
          break;
        case "observation":
          setObservations((prev) => [msg.data, ...prev].slice(0, OBSERVATION_CAP));
          break;
        case "metrics":
          setTick(msg.data);
          setUpstreamOk(msg.data.upstreamOk);
          break;
        case "project-flow":
          setProjectFlows((prev) => [msg.data, ...prev].slice(0, PROJECT_FLOW_CAP));
          break;
        case "llm-completion":
          setLlmCompletions((prev) => [msg.data, ...prev].slice(0, LLM_COMPLETION_CAP));
          break;
        case "upstream":
          setUpstreamOk(msg.data.ok);
          break;
        // Unknown message types from a newer server are dropped by the parser
        // or fall through here harmlessly.
      }
    },
    [applySnapshot],
  );

  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | null = null;
    let retryTimer: number | null = null;
    let delay = RECONNECT_MIN_MS;

    const url =
      (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws";

    const connect = () => {
      if (disposed) return;
      ws = new WebSocket(url);
      ws.onopen = () => {
        delay = RECONNECT_MIN_MS;
        setWsConnected(true);
      };
      ws.onmessage = (ev) => {
        const msg = parseMessage(ev.data);
        if (msg) handleMessage(msg);
      };
      ws.onerror = () => {
        // onclose fires next; nothing else to do.
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (disposed) return;
        const wait = delay + Math.random() * 500; // jitter so tabs don't sync
        delay = Math.min(delay * 2, RECONNECT_MAX_MS);
        retryTimer = window.setTimeout(connect, wait);
      };
    };
    connect();

    // If no snapshot arrives promptly (server busy, ws blocked), seed over HTTP.
    const fallbackTimer = window.setTimeout(() => {
      if (seededRef.current) return;
      void apiGet<DashboardSnapshot>("/api/dashboard").then((snap) => {
        if (snap && !seededRef.current) applySnapshot(snap);
      });
    }, SNAPSHOT_FALLBACK_MS);

    // The server sends a full snapshot only once per socket and live messages
    // never rebuild the bucket series, so the chart cards would freeze at
    // page-load state. Refetch periodically — updating ONLY the snapshot
    // (chart series); requests/tick keep streaming over the socket.
    const refreshTimer = window.setInterval(() => {
      if (!seededRef.current || document.hidden) return;
      void apiGet<DashboardSnapshot>("/api/dashboard").then((snap) => {
        if (snap) setSnapshot(snap);
      });
    }, SNAPSHOT_REFRESH_MS);

    return () => {
      disposed = true;
      window.clearTimeout(fallbackTimer);
      window.clearInterval(refreshTimer);
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
      }
    };
  }, [handleMessage, applySnapshot]);

  const value = useMemo<LiveState>(
    () => ({
      wsConnected,
      upstreamOk,
      tick,
      snapshot,
      requests,
      observations,
      projectFlows,
      llmCompletions,
      paused,
      setPaused,
    }),
    [
      wsConnected,
      upstreamOk,
      tick,
      snapshot,
      requests,
      observations,
      projectFlows,
      llmCompletions,
      paused,
      setPaused,
    ],
  );

  return createElement(LiveContext.Provider, { value }, props.children);
}

export function useLive(): LiveState {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive() must be used inside <LiveProvider>");
  return ctx;
}
