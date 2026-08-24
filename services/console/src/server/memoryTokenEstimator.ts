import type {
  MemoryEstimateConfidence,
  MemoryRequestOutcome,
  RequestRecord,
  SessionSummary,
} from "../shared/types.js";
import { retrievalMode } from "../shared/memoryEconomics.js";

interface CorpusState {
  legacyObservations: number;
  liveCaptureBytes: number;
  liveCaptureSamples: number;
}

function cleanProject(project: string | null): string | null {
  const value = project?.trim();
  return value ? value.slice(0, 512) : null;
}

function safeCount(value: number | null): number {
  return value !== null && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

export class MemoryTokenEstimator {
  private readonly projects = new Map<string, CorpusState>();
  private seeded = false;

  seed(sessions: SessionSummary[]): void {
    if (this.seeded) return;
    const totals = new Map<string, number>();
    for (const session of sessions) {
      const project = cleanProject(session.project);
      if (!project) continue;
      totals.set(project, (totals.get(project) ?? 0) + safeCount(session.observationCount));
    }
    for (const [project, observations] of totals) {
      this.projects.set(project, { legacyObservations: observations, liveCaptureBytes: 0, liveCaptureSamples: 0 });
    }
    this.seeded = true;
  }

  private state(project: string): CorpusState {
    let state = this.projects.get(project);
    if (!state) {
      state = { legacyObservations: 0, liveCaptureBytes: 0, liveCaptureSamples: 0 };
      this.projects.set(project, state);
    }
    return state;
  }

  private globalAverageBytes(): number | null {
    let bytes = 0;
    let samples = 0;
    for (const state of this.projects.values()) {
      bytes += state.liveCaptureBytes;
      samples += state.liveCaptureSamples;
    }
    return samples > 0 ? bytes / samples : null;
  }

  private estimate(project: string, contextTokens: number): {
    low: number;
    high: number;
    confidence: MemoryEstimateConfidence;
  } | null {
    const state = this.state(project);
    const projectAverage = state.liveCaptureSamples > 0 ? state.liveCaptureBytes / state.liveCaptureSamples : null;
    const averageBytes = projectAverage ?? this.globalAverageBytes();
    const legacyBytes = averageBytes === null ? 0 : state.legacyObservations * averageBytes;
    const corpusBytes = legacyBytes + state.liveCaptureBytes;
    if (corpusBytes <= 0) return null;
    const baselineLow = Math.floor(corpusBytes / 4);
    const baselineHigh = Math.ceil(corpusBytes / 3);
    return {
      low: Math.max(0, baselineLow - contextTokens),
      high: Math.max(0, baselineHigh - contextTokens),
      confidence: state.legacyObservations > 0 ? "legacy_low" : "live",
    };
  }

  decorate(input: {
    lifecycle: RequestRecord["lifecycle"];
    project: string | null;
    status: number;
    reqBytes: number;
    outcome: MemoryRequestOutcome | null;
  }): MemoryRequestOutcome | null {
    const project = cleanProject(input.project);
    let outcome = input.outcome;
    if (
      project && retrievalMode(input.lifecycle) === "automatic" && outcome?.kind === "returned" &&
      (outcome.unscopedResultCount ?? 0) === 0 && (outcome.crossProjectResultCount ?? 0) === 0
    ) {
      const reported = outcome.contextTokens ?? (outcome.contextChars === null ? null : Math.ceil(outcome.contextChars / 3));
      if (reported !== null) {
        const estimate = this.estimate(project, reported);
        if (estimate) {
          outcome = {
            ...outcome,
            estimatedAvoidedTokensLow: estimate.low,
            estimatedAvoidedTokensHigh: estimate.high,
            estimateConfidence: estimate.confidence,
          };
        }
      }
    }
    if (project && input.lifecycle === "observation_capture" && input.status > 0 && input.status < 400 && input.reqBytes >= 0) {
      const state = this.state(project);
      state.liveCaptureBytes += input.reqBytes;
      state.liveCaptureSamples++;
    }
    return outcome;
  }

  corpusObservations(project: string): number {
    const state = this.projects.get(project);
    return state ? state.legacyObservations + state.liveCaptureSamples : 0;
  }
}

export const memoryTokenEstimator = new MemoryTokenEstimator();
