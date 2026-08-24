import type { ProjectSummary } from "../../shared/types";

export const REORDER_OPTIONS = [15_000, 30_000, 60_000, 300_000, "manual"] as const;
export type ReorderInterval = (typeof REORDER_OPTIONS)[number];
export const DEFAULT_REORDER_INTERVAL: ReorderInterval = 60_000;

export function parseReorderInterval(value: string | null): ReorderInterval {
  if (value === "manual") return value;
  const parsed = Number(value);
  return REORDER_OPTIONS.includes(parsed as ReorderInterval)
    ? (parsed as ReorderInterval)
    : DEFAULT_REORDER_INTERVAL;
}

export function sortProjectNames(projects: ProjectSummary[]): string[] {
  return [...projects]
    .sort(
      (a, b) =>
        (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0) ||
        a.project.localeCompare(b.project),
    )
    .map((project) => project.project);
}
