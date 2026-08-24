import { readFileSync } from "node:fs";
import type { BillingStatusSnapshot, LlmCostSnapshot } from "../shared/types.js";
import { config } from "./config.js";
import { history } from "./history.js";
import { PRICING_CATALOG_EFFECTIVE } from "./llmCost.js";
import type {
  BillingScopeRecord,
  BillingSyncStateRecord,
  ProviderCostDayRecord,
} from "./historyProtocol.js";

const DAY_MS = 86_400_000;
const COSTS_URL = "https://api.openai.com/v1/organization/costs";

interface CostPage {
  data?: Array<{
    start_time?: number;
    results?: Array<{
      project_id?: string | null;
      amount?: { value?: number; currency?: string };
    }>;
  }>;
  has_more?: boolean;
  next_page?: string | null;
}

interface PageResult {
  payload: CostPage;
  nextAllowedAt: number;
}

function startOfUtcDay(ts: number): number {
  const date = new Date(ts);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

export function parseRateLimitDurationMs(value: string | null): number {
  if (!value) return 0;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric >= 0) return numeric * 1_000;
  let total = 0;
  const pattern = /(\d+(?:\.\d+)?)(ms|s|m|h)/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value))) {
    const amount = Number(match[1]);
    const unit = match[2].toLowerCase();
    total += amount * (unit === "ms" ? 1 : unit === "s" ? 1_000 : unit === "m" ? 60_000 : 3_600_000);
  }
  return total;
}

export function conservativeBillingNextAllowedAt(response: Response, now: number): number {
  const retryAfter = response.headers.get("retry-after");
  let retryAfterMs = parseRateLimitDurationMs(retryAfter);
  if (retryAfter && retryAfterMs === 0) {
    const date = Date.parse(retryAfter);
    if (Number.isFinite(date)) retryAfterMs = Math.max(0, date - now);
  }
  const resetMs = parseRateLimitDurationMs(response.headers.get("x-ratelimit-reset-requests"));
  return Math.max(now + config.billingSyncMs, now + retryAfterMs * 2, now + resetMs * 2);
}

export function buildProjectCostsUrl(startMs: number, endMs: number, projectId: string, page: string | null): URL {
  const url = new URL(COSTS_URL);
  url.searchParams.set("start_time", String(Math.floor(startMs / 1_000)));
  url.searchParams.set("end_time", String(Math.floor(endMs / 1_000)));
  url.searchParams.set("bucket_width", "1d");
  url.searchParams.set("limit", "180");
  url.searchParams.append("group_by", "project_id");
  url.searchParams.append("project_ids", projectId);
  if (page) url.searchParams.set("page", page);
  return url;
}

class BillingRequestError extends Error {
  constructor(message: string, readonly nextAllowedAt: number) {
    super(message);
  }
}

export class BillingCooldownError extends Error {
  constructor(readonly nextAllowedAt: number) {
    super(`Billing refresh is available ${new Date(nextAllowedAt).toLocaleString()}.`);
  }
}

async function fetchPage(url: URL, adminKey: string): Promise<PageResult> {
  const now = Date.now();
  const response = await fetch(url, {
    headers: { authorization: `Bearer ${adminKey}`, "content-type": "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  const nextAllowedAt = conservativeBillingNextAllowedAt(response, now);
  if (response.ok) return { payload: await response.json() as CostPage, nextAllowedAt };
  if (response.status === 401 || response.status === 403) {
    throw new BillingRequestError("OpenAI billing authorization failed", nextAllowedAt);
  }
  if (response.status === 429) {
    throw new BillingRequestError("OpenAI billing rate limit reached; the documented retry window has been doubled", nextAllowedAt);
  }
  throw new BillingRequestError(`OpenAI billing request failed (${response.status})`, nextAllowedAt);
}

class BillingService {
  private status: LlmCostSnapshot["billingStatus"] = "setup_required";
  private detail = config.legacyOpenAiBillingApiKeyId
    ? "API-key billing is retired. Re-run configure-openai-billing for a dedicated OpenAI project."
    : "Add a file-mounted OpenAI Admin API key and the dedicated OpenAI project ID.";
  private billedMonthToDateNanos: number | null = null;
  private billedThrough: number | null = null;
  private timer: NodeJS.Timeout | null = null;
  private syncing: Promise<void> | null = null;
  private initializing: Promise<void> | null = null;
  private state: BillingSyncStateRecord | null = null;

  private scope(): BillingScopeRecord | null {
    if (!config.openAiBillingProjectId) return null;
    return {
      provider: "openai",
      scopeType: "project",
      scopeId: config.openAiBillingProjectId,
      scopeLabel: config.openAiBillingProjectName ?? "OpenAI project",
    };
  }

  start(): void {
    if (!config.openAiAdminKeyFile || !this.scope()) return;
    this.initializing = this.initialize().finally(() => { this.initializing = null; });
  }

  private async initialize(): Promise<void> {
    const scope = this.scope();
    if (!scope) return;
    try {
      await history.setBillingScope(scope);
      const stored = await history.billingState(scope);
      this.state = stored
        ? { ...stored, scopeLabel: scope.scopeLabel }
        : {
            ...scope,
            lastAttemptAt: null,
            lastSuccessAt: null,
            nextAllowedAt: null,
            lastError: null,
            backfillComplete: false,
          };
      const persisted = await history.costSnapshot();
      this.billedMonthToDateNanos = persisted.billedMonthToDateNanos ?? (this.state.lastSuccessAt ? 0 : null);
      if (this.state.lastSuccessAt) {
        this.billedThrough = startOfUtcDay(this.state.lastSuccessAt) - DAY_MS;
        this.status = this.state.lastError ? "error" : "ready";
        this.detail = this.state.lastError ?? this.readyDetail();
      }
      if ((this.state.nextAllowedAt ?? 0) > Date.now()) this.schedule(this.state.nextAllowedAt!);
      else await this.requestSync(false);
    } catch (error) {
      this.status = "error";
      this.detail = error instanceof Error ? error.message : "OpenAI billing initialization failed";
      this.schedule(Date.now() + config.billingSyncMs);
    }
  }

  private readAdminKey(): string {
    if (!config.openAiAdminKeyFile) throw new Error("OpenAI Admin API key file is not configured");
    const key = readFileSync(config.openAiAdminKeyFile, "utf8").trim();
    if (!key) throw new Error("OpenAI Admin API key file is empty");
    if (/[\r\n]/.test(key) || key.includes("=") || /^['\"]|['\"]$/.test(key)) {
      throw new Error("OpenAI Admin API key file must contain only the raw key");
    }
    return key;
  }

  async sync(): Promise<void> {
    if (this.initializing) await this.initializing;
    return this.requestSync(true);
  }

  private async requestSync(manual: boolean): Promise<void> {
    if (this.syncing) return this.syncing;
    const nextAllowedAt = this.state?.nextAllowedAt ?? 0;
    if (nextAllowedAt > Date.now()) {
      this.schedule(nextAllowedAt);
      if (manual) throw new BillingCooldownError(nextAllowedAt);
      return;
    }
    this.syncing = this.runSync().finally(() => { this.syncing = null; });
    return this.syncing;
  }

  private schedule(at: number): void {
    if (this.timer) clearTimeout(this.timer);
    const delay = Math.max(1_000, Math.min(2_147_000_000, at - Date.now()));
    this.timer = setTimeout(() => { void this.requestSync(false).catch(() => undefined); }, delay);
    this.timer.unref();
  }

  private readyDetail(): string {
    const label = config.openAiBillingProjectName ?? config.openAiBillingProjectId ?? "configured project";
    return `Authoritative OpenAI costs for project ${label}; complete UTC days only.`;
  }

  private async saveState(): Promise<void> {
    if (this.state) await history.setBillingState(this.state);
  }

  private async runSync(): Promise<void> {
    const scope = this.scope();
    if (!scope || !config.openAiAdminKeyFile || !this.state) return;
    const attemptedAt = Date.now();
    this.status = "syncing";
    this.detail = `Synchronizing OpenAI project ${scope.scopeLabel}.`;
    this.state = {
      ...this.state,
      scopeLabel: scope.scopeLabel,
      lastAttemptAt: attemptedAt,
      nextAllowedAt: attemptedAt + config.billingSyncMs,
      lastError: null,
    };
    await this.saveState();
    try {
      const adminKey = this.readAdminKey();
      const endMs = startOfUtcDay(attemptedAt);
      const monthStart = Date.UTC(new Date(attemptedAt).getUTCFullYear(), new Date(attemptedAt).getUTCMonth(), 1);
      const rollingStart = Math.min(monthStart, endMs - 7 * DAY_MS);
      const startMs = this.state.backfillComplete ? rollingStart : endMs - config.historyRetentionDays * DAY_MS;
      const rows = new Map<number, ProviderCostDayRecord>();
      let page: string | null = null;
      let nextAllowedAt = this.state.nextAllowedAt ?? attemptedAt + config.billingSyncMs;
      do {
        const url = buildProjectCostsUrl(startMs, endMs, scope.scopeId, page);
        const result = await fetchPage(url, adminKey);
        nextAllowedAt = Math.max(nextAllowedAt, result.nextAllowedAt);
        for (const bucket of result.payload.data ?? []) {
          if (!Number.isFinite(bucket.start_time)) continue;
          const dayMs = Number(bucket.start_time) * 1_000;
          let amountNanos = 0;
          let currency = "usd";
          for (const item of bucket.results ?? []) {
            if (item.project_id && item.project_id !== scope.scopeId) {
              throw new Error("OpenAI returned costs for a project outside the configured billing scope");
            }
            if (typeof item.amount?.value === "number" && Number.isFinite(item.amount.value)) {
              amountNanos += Math.round(item.amount.value * 1_000_000_000);
            }
            if (typeof item.amount?.currency === "string") currency = item.amount.currency.toLowerCase();
          }
          rows.set(dayMs, {
            dayMs,
            provider: scope.provider,
            scopeType: scope.scopeType,
            scopeId: scope.scopeId,
            scopeLabel: scope.scopeLabel,
            amountNanos,
            currency,
            syncedAt: attemptedAt,
            source: "organization_costs_api",
          });
        }
        page = result.payload.has_more && result.payload.next_page ? result.payload.next_page : null;
      } while (page);
      await history.recordProviderCosts([...rows.values()]);
      const persisted = await history.costSnapshot(attemptedAt);
      this.billedMonthToDateNanos = persisted.billedMonthToDateNanos ?? 0;
      this.billedThrough = endMs - DAY_MS;
      this.state = {
        ...this.state,
        lastSuccessAt: attemptedAt,
        nextAllowedAt,
        lastError: null,
        backfillComplete: true,
      };
      await this.saveState();
      this.status = "ready";
      this.detail = this.readyDetail();
      this.schedule(nextAllowedAt);
    } catch (error) {
      const nextAllowedAt = error instanceof BillingRequestError
        ? Math.max(this.state.nextAllowedAt ?? 0, error.nextAllowedAt)
        : Math.max(this.state.nextAllowedAt ?? 0, attemptedAt + config.billingSyncMs);
      const message = error instanceof Error ? error.message : "OpenAI billing synchronization failed";
      this.state = { ...this.state, nextAllowedAt, lastError: message };
      await this.saveState().catch(() => undefined);
      this.status = "error";
      this.detail = message;
      this.schedule(nextAllowedAt);
      throw error;
    }
  }

  snapshot(): BillingStatusSnapshot {
    const scope = this.scope();
    return {
      currency: "USD",
      billedMonthToDateNanos: this.billedMonthToDateNanos,
      billedThrough: this.billedThrough,
      billingStatus: this.status,
      billingDetail: this.detail,
      billingScope: scope ? { type: "project", id: scope.scopeId, name: config.openAiBillingProjectName } : null,
      lastBillingAttemptAt: this.state?.lastAttemptAt ?? null,
      lastBillingSuccessAt: this.state?.lastSuccessAt ?? null,
      nextBillingSyncAllowedAt: this.state?.nextAllowedAt ?? null,
      lastBillingSyncAt: this.state?.lastSuccessAt ?? null,
      pricingCatalogEffective: PRICING_CATALOG_EFFECTIVE,
    };
  }
}

export const billing = new BillingService();
