// WebSocket hub for the UI: one server-side fan-out point at path /ws.
//
// Attached to the UI listener's underlying http.Server so the SPA connects on
// the same origin/port it was served from. New clients get a full snapshot
// immediately; everything after that is incremental broadcasts.

import { WebSocketServer, WebSocket } from "ws";
import type { Server, IncomingMessage } from "node:http";
import type { Duplex } from "node:stream";
import type { WsServerMessage } from "../shared/types.js";

export function createHub(): {
  attach(server: Server, buildSnapshot: () => WsServerMessage): void;
  broadcast(msg: WsServerMessage): void;
  clientCount(): number;
} {
  const wss = new WebSocketServer({ noServer: true });
  const clients = new Set<WebSocket>();

  function attach(server: Server, buildSnapshot: () => WsServerMessage): void {
    server.on("upgrade", (req: IncomingMessage, socket: Duplex, head: Buffer) => {
      let pathname = "";
      try {
        pathname = new URL(req.url ?? "", "http://localhost").pathname;
      } catch {
        // fall through with empty pathname -> destroyed below
      }
      if (pathname !== "/ws") {
        socket.destroy();
        return;
      }
      wss.handleUpgrade(req, socket, head, (ws) => {
        clients.add(ws);
        ws.on("close", () => clients.delete(ws));
        ws.on("error", () => {
          clients.delete(ws);
          try {
            ws.terminate();
          } catch {
            // already gone
          }
        });
        try {
          ws.send(JSON.stringify(buildSnapshot()));
        } catch {
          // client vanished between upgrade and first send
        }
      });
    });
  }

  function broadcast(msg: WsServerMessage): void {
    if (clients.size === 0) return;
    const text = JSON.stringify(msg);
    for (const ws of clients) {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(text);
        } catch {
          // per-client failures never break the fan-out
        }
      }
    }
  }

  function clientCount(): number {
    return clients.size;
  }

  return { attach, broadcast, clientCount };
}
