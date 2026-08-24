// Thin fetch wrapper for the console's own /api endpoints (same-origin).
// Every failure mode — network error, non-2xx, invalid JSON — collapses to
// null so callers render an empty/offline state instead of throwing.

export async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(path, { headers: { accept: "application/json" } });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function apiPost<T>(path: string, body: unknown = {}): Promise<{ data: T | null; error: string | null }> {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/json", "x-agent007memory-action": "1" },
      body: JSON.stringify(body),
    });
    const payload = await res.json().catch(() => null) as T | { detail?: string; error?: string } | null;
    if (!res.ok) {
      const message = payload && typeof payload === "object" && "detail" in payload ? payload.detail : null;
      return { data: null, error: typeof message === "string" ? message : `Request failed (${res.status})` };
    }
    return { data: payload as T, error: null };
  } catch (error) {
    return { data: null, error: error instanceof Error ? error.message : "Request failed" };
  }
}
