// Reliable client attribution for proxied AgentMemory traffic.
//
// Clients use a tagged base URL such as http://localhost:3111/_agent/codex.
// The proxy removes that private prefix before forwarding and records the
// exact client tag. For the two upstream write APIs that already accept an
// agentId, a streaming transform adds the field without retaining body data.

import { Transform, type Readable } from "node:stream";
import { KNOWN_AGENTS, type KnownAgent } from "../shared/types.js";

const AGENT_PREFIX = "/_agent/";
const PERSISTENCE_ROUTES = new Set([
  "/agentmemory/session/start",
  "/agentmemory/remember",
]);

export interface AttributedPath {
  agent: KnownAgent | null;
  path: string;
}

export function attributedPath(path: string): AttributedPath {
  for (const agent of KNOWN_AGENTS) {
    const prefix = `${AGENT_PREFIX}${agent}`;
    if (path === prefix) return { agent, path: "/" };
    if (path.startsWith(`${prefix}/`)) return { agent, path: path.slice(prefix.length) };
    if (path.startsWith(`${prefix}?`)) return { agent, path: `/${path.slice(prefix.length)}` };
  }
  return { agent: null, path };
}

export function isAgentPersistenceRoute(path: string): boolean {
  const query = path.indexOf("?");
  return PERSISTENCE_ROUTES.has(query === -1 ? path : path.slice(0, query));
}

function isWhitespace(byte: number): boolean {
  return byte === 0x20 || byte === 0x09 || byte === 0x0a || byte === 0x0d;
}

/**
 * Add an agentId property to a top-level JSON object while keeping the body
 * streaming. Only leading JSON syntax is inspected; memory contents are never
 * buffered or captured. Non-object payloads pass through unchanged.
 */
export function injectAgentId(source: Readable, agent: KnownAgent): Readable {
  const field = Buffer.from(`"agentId":${JSON.stringify(agent)}`);
  let state: "before-object" | "after-open" | "done" = "before-object";

  const transform = new Transform({
    transform(chunk: Buffer | string, encoding, callback) {
      let bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding);
      const output: Buffer[] = [];

      while (bytes.length > 0 && state !== "done") {
        let index = 0;
        while (index < bytes.length && isWhitespace(bytes[index])) index++;

        if (index === bytes.length) {
          output.push(bytes);
          bytes = Buffer.alloc(0);
          break;
        }

        if (state === "before-object") {
          if (bytes[index] !== 0x7b) {
            state = "done";
            break;
          }
          output.push(bytes.subarray(0, index + 1));
          bytes = bytes.subarray(index + 1);
          state = "after-open";
          continue;
        }

        // Preserve whitespace after "{" and insert before the first value.
        output.push(bytes.subarray(0, index));
        output.push(field);
        if (bytes[index] !== 0x7d) output.push(Buffer.from(","));
        bytes = bytes.subarray(index);
        state = "done";
      }

      if (bytes.length > 0) output.push(bytes);
      callback(null, output.length === 1 ? output[0] : Buffer.concat(output));
    },
    flush(callback) {
      // A body ending immediately after "{" was already malformed. Do not
      // synthesize a closing brace or otherwise hide the upstream 4xx.
      callback();
    },
  });

  source.once("error", (error) => transform.destroy(error));
  source.pipe(transform);
  return transform;
}
