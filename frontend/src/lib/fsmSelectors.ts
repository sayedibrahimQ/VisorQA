/**
 * FSM selectors for the Mission Control orchestration UI (SCRUM-28).
 *
 * Pure derivation helpers over {@link PRRun}. Conservative by design:
 * `current_step` alone never marks a previous node "completed". A predecessor
 * is "completed" only when the deterministic driver
 * (`backend/core/orchestrator.py::_drive_fsm`) structurally guarantees it ran:
 *
 * - SENSE completed: the run advanced past SENSE, entered the repair loop, or
 *   terminated (the driver awaits SENSE and broadcasts SENSE_COMPLETE first).
 * - TRIAGE completed: the run entered the repair loop (`strikes > 0`, or a
 *   recorded attempt), which requires TRIAGE to have been awaited.
 * - DIAGNOSE / PATCH completed: only on terminal RESOLVED runs that entered
 *   the loop (a passed verification implies the final D -> P -> V cycle ran
 *   in full). Per-attempt node outcomes are not observable from PRRun today
 *   (the event path broadcasts only ATTEMPT_n_FEEDBACK after each cycle, and
 *   mid-cycle exceptions short-circuit to VERIFY), so in-loop D/P render as
 *   neutral pending — never success-green on unconfirmed work.
 * - VERIFY completed: only on RESOLVED. Failed on terminal FAILED runs.
 * - Skipped: terminal runs only. RESOLVED with zero strikes means the driver
 *   took the no-anomalies early exit and never ran TRIAGE/DIAGNOSE/PATCH;
 *   nodes after a failed node never ran.
 *
 * On terminal FAILED runs after loop entry, DIAGNOSE/PATCH/VERIFY all render
 * "failed": per-node loop outcomes are unobservable, so the halted repair
 * loop is attributed as a unit instead of implying successful completion.
 */

import type { FSMStep, PRRun } from "@/types";

export type NodeStatus = "pending" | "active" | "completed" | "failed" | "skipped";

export interface FSMNodeMeta {
  key: FSMStep;
  step: number;
  name: string;
  model: string;
}

export const FSM_NODES: FSMNodeMeta[] = [
  { key: "1.SENSE", step: 1, name: "Sense", model: "SAM 3.1" },
  { key: "2.TRIAGE", step: 2, name: "Triage", model: "Muse Spark" },
  { key: "3.DIAGNOSE", step: 3, name: "Diagnose", model: "Muse Wonder" },
  { key: "4.PATCH", step: 4, name: "Patch", model: "Muse Code + HMR" },
  { key: "5.VERIFY", step: 5, name: "Verify & Commit", model: "SAM 3.1 + GitHub" },
];

export const MAX_STRIKES = 3;

const STEP_INDEX: Record<FSMStep, number> = {
  "1.SENSE": 0,
  "2.TRIAGE": 1,
  "3.DIAGNOSE": 2,
  "4.PATCH": 3,
  "5.VERIFY": 4,
};

export function stepIndex(step: FSMStep | string | undefined): number {
  if (typeof step === "string" && step in STEP_INDEX) {
    return STEP_INDEX[step as FSMStep];
  }
  return 0;
}

export function clampStrikes(strikes: unknown): number {
  if (typeof strikes !== "number" || !Number.isFinite(strikes)) return 0;
  return Math.min(MAX_STRIKES, Math.max(0, Math.floor(strikes)));
}

function hasAttempts(run: PRRun): boolean {
  return Array.isArray(run.attempts) && run.attempts.length > 0;
}

/** Loop entry is confirmed by a strike counter or any recorded attempt. */
function loopEntered(run: PRRun): boolean {
  return clampStrikes(run.strikes) > 0 || hasAttempts(run);
}

export interface FSMNodeState extends FSMNodeMeta {
  status: NodeStatus;
  latencyMs: number | null;
}

function latencyFor(run: PRRun, key: FSMStep): number | null {
  const raw = run.step_latency_ms?.[key];
  return typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? raw : null;
}

function withLatency(run: PRRun, key: FSMStep, status: NodeStatus): FSMNodeState {
  const meta = FSM_NODES[stepIndex(key)];
  return { ...meta, status, latencyMs: latencyFor(run, key) };
}

/**
 * Derive the five node statuses for a run. `null` (no selection) yields all
 * pending. Unknown future statuses fall back to the non-terminal path.
 */
export function getNodeStates(run: PRRun | null): FSMNodeState[] {
  if (!run) {
    return FSM_NODES.map((meta) => ({ ...meta, status: "pending", latencyMs: null }));
  }
  // String-typed: the backend also emits QUEUED/FALLBACK beyond RunStatus.
  const status: string = typeof run.status === "string" ? run.status : "PENDING";
  const current = stepIndex(run.current_step);
  const entered = loopEntered(run);

  if (status === "RESOLVED") {
    if (!entered) {
      // No-anomalies early exit: TRIAGE/DIAGNOSE/PATCH never ran.
      return [
        withLatency(run, "1.SENSE", "completed"),
        withLatency(run, "2.TRIAGE", "skipped"),
        withLatency(run, "3.DIAGNOSE", "skipped"),
        withLatency(run, "4.PATCH", "skipped"),
        withLatency(run, "5.VERIFY", "completed"),
      ];
    }
    return FSM_NODES.map((meta) => ({ ...meta, status: "completed", latencyMs: latencyFor(run, meta.key) }));
  }

  if (status === "FAILED") {
    if (entered) {
      // Halted repair loop: attribute failure to the D -> P -> V loop as a
      // unit; SENSE/TRIAGE outputs were necessarily produced to enter it.
      return [
        withLatency(run, "1.SENSE", "completed"),
        withLatency(run, "2.TRIAGE", "completed"),
        withLatency(run, "3.DIAGNOSE", "failed"),
        withLatency(run, "4.PATCH", "failed"),
        withLatency(run, "5.VERIFY", "failed"),
      ];
    }
    // Failed before the loop: only the failed node is certain; successors
    // never ran; predecessors need structural confirmation.
    return FSM_NODES.map((meta, i) => {
      let nodeStatus: NodeStatus;
      if (i === current) nodeStatus = "failed";
      else if (i > current) nodeStatus = "skipped";
      else if (i === 0) nodeStatus = "completed"; // advanced past SENSE
      else nodeStatus = "pending"; // completion unconfirmed
      return { ...meta, status: nodeStatus, latencyMs: latencyFor(run, meta.key) };
    });
  }

  // Non-terminal (PENDING / QUEUED / RUNNING / FALLBACK / unknown).
  const started = status !== "PENDING" && status !== "QUEUED";
  return FSM_NODES.map((meta, i) => {
    let nodeStatus: NodeStatus;
    if (!started) {
      nodeStatus = "pending";
    } else if (i === current) {
      nodeStatus = "active";
    } else if (i > current) {
      nodeStatus = "pending";
    } else if (i === 0) {
      nodeStatus = "completed"; // advanced past SENSE
    } else if (i === 1) {
      // TRIAGE completion needs loop entry (strikes or a recorded attempt);
      // a bare current_step of VERIFY with zero strikes proves nothing.
      nodeStatus = entered ? "completed" : "pending";
    } else {
      // DIAGNOSE / PATCH: per-attempt outcomes are unobservable from PRRun.
      nodeStatus = "pending";
    }
    return { ...meta, status: nodeStatus, latencyMs: latencyFor(run, meta.key) };
  });
}

// ---------------------------------------------------------------------------
// Three-strike loop
// ---------------------------------------------------------------------------

export type AttemptPhase = "idle" | "in_progress" | "resolved" | "terminal";

export interface AttemptState {
  current: number;
  max: number;
  phase: AttemptPhase;
}

export function getAttemptState(run: PRRun | null): AttemptState {
  if (!run) return { current: 0, max: MAX_STRIKES, phase: "idle" };
  const status = typeof run.status === "string" ? run.status : "PENDING";
  const fromAttempts = hasAttempts(run) ? (run.attempts as unknown[]).length : 0;
  const current = Math.min(MAX_STRIKES, Math.max(clampStrikes(run.strikes), Math.min(MAX_STRIKES, fromAttempts)));
  if (status === "RESOLVED") return { current, max: MAX_STRIKES, phase: "resolved" };
  if (status === "FAILED") return { current, max: MAX_STRIKES, phase: "terminal" };
  if (current > 0) return { current, max: MAX_STRIKES, phase: "in_progress" };
  return { current: 0, max: MAX_STRIKES, phase: "idle" };
}

// ---------------------------------------------------------------------------
// Run list
// ---------------------------------------------------------------------------

export type RunTone = "neutral" | "info" | "success" | "danger" | "warning";

export interface RunStatusMeta {
  label: string;
  tone: RunTone;
  historical: boolean;
}

export function getRunStatusMeta(status: unknown): RunStatusMeta {
  switch (status) {
    case "RUNNING":
      return { label: "Running", tone: "info", historical: false };
    case "PENDING":
      return { label: "Pending", tone: "neutral", historical: false };
    case "QUEUED":
      return { label: "Waiting", tone: "neutral", historical: false };
    case "FALLBACK":
      return { label: "Fallback", tone: "warning", historical: false };
    case "RESOLVED":
      return { label: "Resolved", tone: "success", historical: true };
    case "FAILED":
      return { label: "Failed", tone: "danger", historical: true };
    default:
      return { label: typeof status === "string" && status ? status : "Unknown", tone: "neutral", historical: false };
  }
}

export function isHistoricalRun(run: PRRun): boolean {
  return getRunStatusMeta(run.status).historical;
}

export function partitionRuns(runs: PRRun[]): { active: PRRun[]; historical: PRRun[] } {
  const active: PRRun[] = [];
  const historical: PRRun[] = [];
  for (const run of runs) {
    (isHistoricalRun(run) ? historical : active).push(run);
  }
  return { active, historical };
}

/** Current pipeline stage label for sidebar rows. */
export function stageLabel(step: FSMStep | string | undefined): string {
  const meta = FSM_NODES[stepIndex(step)];
  return meta ? `${meta.step} · ${meta.name}` : "—";
}

// ---------------------------------------------------------------------------
// Latency
// ---------------------------------------------------------------------------

/**
 * Format a measured latency. Returns null when there is no real measurement
 * so callers render the neutral placeholder instead of a fabricated value.
 */
export function formatLatency(ms: unknown): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  return `${Math.round(ms)} ms`;
}
