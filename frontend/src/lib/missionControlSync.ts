/**
 * Mission Control sync engine (framework-free).
 *
 * Merges `GET /api/runs` snapshots with `/ws/mission-control` telemetry
 * envelopes (`{event, type, timestamp, run_id, state}`), using the exact
 * backend contract in `backend/api/routes_ws.py` + `backend/api/webhooks.py`.
 *
 * Guarantees:
 * - Stale REST responses (older generation) are discarded entirely.
 * - A newer WebSocket run is never overwritten by an older REST row
 *   (per-run timestamp comparison, ties keep the WS value).
 * - Duplicate webhook deliveries / replayed envelopes are ignored.
 * - Only `SENSE_STARTED` for a previously-unknown run focuses the workspace.
 */

import type { PRRun, RunStatus } from "@/types";

export type ConnectionStatus =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "error";

export interface TelemetryEnvelope {
  event?: string;
  type?: string;
  timestamp?: string;
  run_id?: string;
  state?: Record<string, unknown> | null;
  endpoint?: string;
  client_id?: string;
  message?: string;
  payload?: unknown;
}

/** A `SENSE_STARTED` broadcast marks a GitHub webhook PR-run arrival. */
export const PR_RUN_ARRIVAL_EVENT = "SENSE_STARTED";

const FOCUSABLE_RUN_EVENTS = new Set([
  "SENSE_STARTED",
  "SENSE_COMPLETE",
  "TRIAGE_COMPLETE",
  "RUN_RESOLVED",
  "RUN_HALTED",
]);

function isAttemptFeedback(event: string): boolean {
  return event.startsWith("ATTEMPT_") && event.endsWith("_FEEDBACK");
}

interface StoredRun {
  run: PRRun;
  /** Epoch ms of the newest source that produced this row. */
  sourceTs: number;
}

function toEpochMs(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const ms = Date.parse(value);
    if (Number.isFinite(ms)) return ms;
  }
  return 0;
}

function nowMs(): number {
  return Date.now();
}

function hashEnvelope(raw: string): string {
  let h = 5381;
  for (let i = 0; i < raw.length; i += 1) {
    h = ((h << 5) + h + raw.charCodeAt(i)) | 0;
  }
  return `len:${raw.length}:h:${h}`;
}

export interface HydratedSnapshot {
  runs: PRRun[];
  activeRunId: string | null;
  focusLatencyMs: number | null;
  lastEventAt: string | null;
}

/**
 * Normalize one REST row or one WS envelope into a PRRun.
 * Returns null when the payload carries no usable run identity.
 */
export function runFromRestRow(row: Record<string, unknown>): PRRun | null {
  const id = row.id;
  if (typeof id !== "string" || !id) return null;
  return {
    id,
    pr_number: typeof row.pr_number === "number" ? row.pr_number : 0,
    repo_name: typeof row.repo_name === "string" ? row.repo_name : "",
    branch: typeof row.branch === "string" ? row.branch : "",
    commit_sha: typeof row.commit_sha === "string" ? row.commit_sha : "",
    status: (row.status as RunStatus) ?? "PENDING",
    current_step: (row.current_step as PRRun["current_step"]) ?? "1.SENSE",
    strikes: typeof row.strikes === "number" ? row.strikes : 0,
    anomalies_count:
      typeof row.anomalies_count === "number" ? row.anomalies_count : undefined,
    updated_at:
      typeof row.updated_at === "string" ? row.updated_at : undefined,
    created_at:
      typeof row.created_at === "string" ? row.created_at : undefined,
  };
}

export function runFromEnvelope(
  envelope: TelemetryEnvelope,
): { run: PRRun; sourceTs: number } | null {
  const runId = envelope.run_id;
  if (!runId || runId === "global") return null;
  const state =
    envelope.state && typeof envelope.state === "object"
      ? envelope.state
      : {};
  const get = (key: string): unknown => state[key];
  const status = (get("status") as RunStatus) ?? "RUNNING";
  const attempt = get("attempt");
  const anomalies = get("anomalies");
  return {
    run: {
      id: runId,
      pr_number: typeof get("pr_number") === "number" ? (get("pr_number") as number) : 0,
      repo_name:
        typeof get("repo_full_name") === "string"
          ? (get("repo_full_name") as string)
          : typeof get("repo_name") === "string"
            ? (get("repo_name") as string)
            : "",
      branch: typeof get("branch") === "string" ? (get("branch") as string) : "",
      commit_sha:
        typeof get("commit_sha") === "string" ? (get("commit_sha") as string) : "",
      status,
      current_step:
        (get("current_step") as PRRun["current_step"]) ?? "1.SENSE",
      strikes: typeof attempt === "number" ? attempt : 0,
      anomalies_count: Array.isArray(anomalies) ? anomalies.length : undefined,
      updated_at: envelope.timestamp,
    },
    sourceTs: toEpochMs(envelope.timestamp) || nowMs(),
  };
}

export class MissionControlSync {
  private runs = new Map<string, StoredRun>();
  private seenEnvelopes = new Set<string>();
  private seenArrivalRuns = new Set<string>();
  private generation = 0;
  private activeRunId: string | null = null;
  private focusLatencyMs: number | null = null;
  private lastEventAt: string | null = null;

  /** Start a REST hydration round; the returned generation tags its response. */
  beginHydration(): number {
    this.generation += 1;
    return this.generation;
  }

  get currentGeneration(): number {
    return this.generation;
  }

  /**
   * Merge a REST snapshot. Stale generations are discarded; per-run rows
   * older than the stored WebSocket value are skipped (ties keep WS).
   */
  applyHydration(rows: unknown, generation: number): boolean {
    if (generation !== this.generation || !Array.isArray(rows)) return false;
    let changed = false;
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const run = runFromRestRow(row as Record<string, unknown>);
      if (!run) continue;
      const ts = Math.max(
        toEpochMs(run.updated_at),
        toEpochMs((row as Record<string, unknown>).created_at),
      );
      const stored = this.runs.get(run.id);
      if (stored && stored.sourceTs > ts) continue; // newer WS state wins
      if (stored && stored.sourceTs === ts && ts !== 0) continue; // tie keeps WS
      this.runs.set(run.id, { run, sourceTs: ts });
      this.seenArrivalRuns.add(run.id);
      changed = true;
    }
    return changed;
  }

  /**
   * Process one raw WS frame. Returns the focused run id (if this frame
   * triggered a workspace focus) and whether any state changed.
   */
  applyMessage(
    raw: string,
    receiptTs = nowMs(),
  ): { focusedRunId: string | null; changed: boolean } {
    let envelope: TelemetryEnvelope;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { focusedRunId: null, changed: false };
      }
      envelope = parsed as TelemetryEnvelope;
    } catch {
      return { focusedRunId: null, changed: false };
    }

    const fingerprint = hashEnvelope(raw);
    if (this.seenEnvelopes.has(fingerprint)) {
      return { focusedRunId: null, changed: false };
    }
    this.seenEnvelopes.add(fingerprint);
    if (this.seenEnvelopes.size > 2000) {
      const oldest = this.seenEnvelopes.values().next().value as string;
      this.seenEnvelopes.delete(oldest);
    }

    const event = envelope.event ?? envelope.type ?? "";
    if (!event) return { focusedRunId: null, changed: false };
    if (event === "CONNECTION_ESTABLISHED" || event === "PONG") {
      return { focusedRunId: null, changed: false };
    }
    this.lastEventAt = envelope.timestamp ?? new Date(receiptTs).toISOString();

    const converted = runFromEnvelope(envelope);
    if (!converted) return { focusedRunId: null, changed: false };
    if (!FOCUSABLE_RUN_EVENTS.has(event) && !isAttemptFeedback(event)) {
      return { focusedRunId: null, changed: false }; // unrelated telemetry
    }

    const { run, sourceTs } = converted;
    const stored = this.runs.get(run.id);
    if (stored && stored.sourceTs >= sourceTs) {
      return { focusedRunId: null, changed: false }; // stale or duplicate
    }
    const isNewRun = !stored;
    this.runs.set(run.id, { run, sourceTs });

    // Workspace focus: only a fresh GitHub webhook PR-run arrival.
    let focusedRunId: string | null = null;
    if (
      event === PR_RUN_ARRIVAL_EVENT &&
      isNewRun &&
      !this.seenArrivalRuns.has(run.id)
    ) {
      this.seenArrivalRuns.add(run.id);
      this.activeRunId = run.id;
      this.focusLatencyMs = nowMs() - receiptTs;
      focusedRunId = run.id;
    }
    return { focusedRunId, changed: true };
  }

  selectRun(runId: string | null): void {
    if (runId === null || this.runs.has(runId)) {
      this.activeRunId = runId;
    }
  }

  snapshot(): HydratedSnapshot {
    const runs = [...this.runs.values()]
      .map((s) => s.run)
      .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    return {
      runs,
      activeRunId: this.activeRunId,
      focusLatencyMs: this.focusLatencyMs,
      lastEventAt: this.lastEventAt,
    };
  }
}
