// Authenticated JSON calls to the agentmemory REST API.
//
// Every helper here swallows failures and returns null/false — callers treat
// "upstream down" as a normal state, never an exception path.

import { config } from "./config.js";
import { getSecret, invalidateSecret } from "./secret.js";

export async function upstreamJson<T>(
  path: string,
  init?: { method?: string; body?: unknown; timeoutMs?: number },
): Promise<T | null> {
  // At most two attempts: the second only after a 401 invalidated the cached
  // secret (covers a rotated .hmac file).
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const secret = await getSecret();
      const headers: Record<string, string> = { accept: "application/json" };
      if (secret) headers.authorization = `Bearer ${secret}`;
      let body: string | undefined;
      if (init?.body !== undefined) {
        headers["content-type"] = "application/json";
        body = JSON.stringify(init.body);
      }
      const res = await fetch(config.upstreamHttp + path, {
        method: init?.method ?? "GET",
        headers,
        body,
        // The default budget suits small JSON endpoints; bulk endpoints
        // (unpaged observations run to tens of MB) pass a larger timeoutMs.
        signal: AbortSignal.timeout(init?.timeoutMs ?? 8_000),
      });
      if (res.status === 401 && attempt === 0) {
        invalidateSecret();
        continue;
      }
      if (!res.ok) return null;
      return (await res.json()) as T;
    } catch {
      return null;
    }
  }
  return null;
}

// Liveness probe: /livez is the one route that needs no auth.
export async function upstreamOk(): Promise<boolean> {
  try {
    const res = await fetch(config.upstreamHttp + "/agentmemory/livez", {
      signal: AbortSignal.timeout(3_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}
