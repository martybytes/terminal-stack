import { parentPort, workerData } from "node:worker_threads";
import { HistoryDatabase } from "./historyDatabase.js";
import type {
  HistoryWorkerCommand,
  HistoryWorkerData,
  HistoryWorkerResponse,
} from "./historyProtocol.js";

if (!parentPort) throw new Error("history worker requires a parent port");

const data = workerData as HistoryWorkerData;
const database = new HistoryDatabase(data.dbPath, data.retentionDays, data.runId, data.startedAt);
const pruneTimer = setInterval(() => database.prune(Date.now()), 6 * 60 * 60_000);
pruneTimer.unref();

function respond(message: HistoryWorkerResponse): void {
  parentPort!.postMessage(message);
}

parentPort.on("message", (command: HistoryWorkerCommand) => {
  try {
    if (command.type === "ingest") {
      database.ingest(command.batch);
      respond({ type: "response", id: command.id, ok: true, result: null });
      return;
    }
    if (command.type === "meta") {
      respond({
        type: "response",
        id: command.id,
        ok: true,
        result: database.meta(data.retentionDays),
      });
      return;
    }
    if (command.type === "context-avoided-history") {
      respond({ type: "response", id: command.id, ok: true, result: database.contextAvoidedHistory(command.now) });
      return;
    }
    if (command.type === "report") {
      respond({ type: "response", id: command.id, ok: true, result: database.report(command.query) });
      return;
    }
    if (command.type === "cost-snapshot") {
      respond({ type: "response", id: command.id, ok: true, result: database.costSnapshot(command.now) });
      return;
    }
    if (command.type === "provider-costs") {
      database.recordProviderCosts(command.rows);
      respond({ type: "response", id: command.id, ok: true, result: null });
      return;
    }
    if (command.type === "billing-scope") {
      database.setBillingScope(command.scope);
      respond({ type: "response", id: command.id, ok: true, result: null });
      return;
    }
    if (command.type === "billing-state-get") {
      respond({ type: "response", id: command.id, ok: true, result: database.billingState(command.scope) });
      return;
    }
    if (command.type === "billing-state-set") {
      database.setBillingState(command.state);
      respond({ type: "response", id: command.id, ok: true, result: null });
      return;
    }
    clearInterval(pruneTimer);
    database.close(command.endedAt);
    respond({ type: "response", id: command.id, ok: true, result: null });
  } catch (error) {
    respond({
      type: "response",
      id: command.id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

respond({ type: "ready" });
