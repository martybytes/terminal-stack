// Entry point: wires capture, metrics, the mem-live client, the WebSocket
// hub, and both Fastify listeners together.

import { config } from "./config.js";
import { capture } from "./capture.js";
import { metrics } from "./metrics.js";
import { llmTelemetry } from "./llmTelemetry.js";
import { store } from "./observations.js";
import { startMemLive } from "./memlive.js";
import { createHub } from "./wsHub.js";
import { startUi } from "./api.js";
import { startProxy } from "./proxy.js";
import { history } from "./history.js";
import { billing } from "./billing.js";
import type { DashboardSnapshot, WsServerMessage } from "../shared/types.js";
import { assessLlmEndpoint } from "../shared/llmEndpoint.js";
import { memoryTokenEstimator } from "./memoryTokenEstimator.js";

const hub = createHub();

function buildSnapshot(): DashboardSnapshot {
  return {
    tick: metrics.latestTick(),
    requests: capture.recent(60),
    buckets5s: capture.buckets5s(),
    buckets1m: capture.buckets1m(),
    obsBuckets1m: metrics.obsBuckets1m(),
    healthSeries: metrics.healthSeries(),
  };
}

capture.subscribe((r) => {
  history.noteRequest(r);
  hub.broadcast({ type: "request", ts: r.ts, data: r });
});
capture.subscribeProjectFlow((event) =>
  hub.broadcast({ type: "project-flow", ts: event.ts, data: event }),
);
metrics.subscribe((t) => {
  history.noteMetrics(t);
  hub.broadcast({ type: "metrics", ts: t.ts, data: t });
});
llmTelemetry.subscribe((event) => {
  history.noteLlm(event);
  hub.broadcast({ type: "llm-completion", ts: event.ts, data: event });
});
llmTelemetry.subscribeCalls((call, sourceInstanceId) => history.noteLlmCall(call, sourceInstanceId));

let wsConnected = false;
let sinceTs = Date.now();
startMemLive({
  onEvent: (e) => {
    metrics.noteObservation(e);
    store.ingestLive(e);
    void (async () => {
      const project = e.sessionId ? await store.projectForSession(e.sessionId) : null;
      history.noteObservation(e, project);
    })();
    hub.broadcast({ type: "observation", ts: e.ts, data: e });
  },
  onState: (connected) => {
    if (connected !== wsConnected) sinceTs = Date.now();
    wsConnected = connected;
    metrics.setWsConnected(connected);
    hub.broadcast({
      type: "upstream",
      ts: Date.now(),
      data: {
        ok: metrics.latestTick()?.upstreamOk ?? false,
        wsConnected: connected,
        sinceTs,
      },
    });
  },
});

await history.start();
if (assessLlmEndpoint(config.llmProvider, config.llmEndpoint, config.llmModel).costApplicability !== "local") billing.start();
metrics.start();
llmTelemetry.start();

try {
  memoryTokenEstimator.seed(await store.sessions());
} catch {
  // Token-efficiency estimates wait for the first successful session inventory.
}

await startUi({
  buildSnapshot,
  hubAttach: (server) =>
    hub.attach(server, (): WsServerMessage => ({ type: "snapshot", ts: Date.now(), data: buildSnapshot() })),
});
await startProxy();

console.log(
  `agent007memory: proxy http://${config.host}:${config.proxyPort} -> ${config.upstreamHttp} | ui http://${config.host}:${config.uiPort} | stream ${config.upstreamWs}/stream/mem-live/viewer`,
);

let stopping = false;
const shutdown = (): void => {
  if (stopping) return;
  stopping = true;
  const deadline = setTimeout(() => process.exit(1), 5_000);
  deadline.unref();
  void history.shutdown().finally(() => process.exit(0));
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
