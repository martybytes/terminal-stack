// Bearer secret for the console's OWN upstream calls.
//
// Resolution order: config.secretFile (contents trimmed) wins over
// config.secretEnv; null when neither yields a value. The resolved value is
// cached until invalidateSecret() — upstream.ts invalidates on a 401 so a
// rotated .hmac file is picked up without a restart.

import { readFile } from "node:fs/promises";
import { config } from "./config.js";

// undefined = not resolved yet; null = resolved to "no secret available".
let cached: string | null | undefined;

export async function getSecret(): Promise<string | null> {
  if (cached !== undefined) return cached;
  if (config.secretFile) {
    try {
      const raw = await readFile(config.secretFile, "utf8");
      const trimmed = raw.trim();
      if (trimmed.length > 0) {
        cached = trimmed;
        return cached;
      }
    } catch {
      // Unreadable file: fall through to the env fallback.
    }
  }
  cached = config.secretEnv && config.secretEnv.length > 0 ? config.secretEnv : null;
  return cached;
}

export function invalidateSecret(): void {
  cached = undefined;
}
