/**
 * Telemetry drawer adapter (MathTrapScorecard / LCATriageTree /
 * ArchitectCoderInspector inputs).
 *
 * Maps the real backend contracts onto drawer view models. Display-only:
 * thresholds are evaluated on raw values exactly as `backend/core/verify.py`
 * states them (V_r >= 0.98, IoU == 0, Delta_x <= 2px; defect bands 0.85 /
 * 0.05 / 2px from config), and no overall verdict is computed here — the
 * backend `verification_status` / `passed` values are passed through.
 * Mirrors BR-2 protected globs and `is_protected_path` semantics from
 * `backend/core/triage.py` (display labeling only).
 */

import type {
  NodeDescriptorInfo,
  PRRun,
  RepairSpecPayload,
  SelfHealingAttempt,
  TriageRejectedTarget,
  ViewportMetrics,
} from "@/types";

// ---------------------------------------------------------------------------
// Math traps
// ---------------------------------------------------------------------------

export type TrapState = "pass" | "fail" | "warning" | "pending" | "unavailable";
export type TrapKind = "vr" | "iou" | "deltaX";

export const TRAP_THRESHOLDS = {
  vrDefectBelow: 0.85,
  vrPassAtLeast: 0.98,
  iouDefectAbove: 0.05,
  iouPassExactly: 0.0,
  deltaFailAbovePx: 2,
  deltaPassAtMostPx: 2,
} as const;

/**
 * Evaluate one trap on the raw (never pre-rounded) value.
 * `awaiting` distinguishes "not measured yet" (pending) from bad data
 * (unavailable); both render without a Pass claim.
 */
export function trapState(kind: TrapKind, value: number | null, awaiting: boolean): TrapState {
  if (value === null || !Number.isFinite(value)) return awaiting ? "pending" : "unavailable";
  switch (kind) {
    case "vr":
      if (value >= TRAP_THRESHOLDS.vrPassAtLeast) return "pass";
      if (value >= TRAP_THRESHOLDS.vrDefectBelow) return "warning";
      return "fail";
    case "iou":
      if (value === TRAP_THRESHOLDS.iouPassExactly) return "pass";
      if (value <= TRAP_THRESHOLDS.iouDefectAbove) return "warning";
      return "fail";
    case "deltaX":
      return value <= TRAP_THRESHOLDS.deltaPassAtMostPx ? "pass" : "fail";
  }
}

export interface ViewportTrapMetrics {
  vr: number | null;
  iou: number | null;
  deltaX: number | null;
  /** Verification outcome for this viewport, backend-reported only. */
  passed: boolean | null;
  failureReasons: string[];
}

export interface AttemptTrapSnapshot {
  attemptNumber: number;
  label: string;
  mobile: ViewportTrapMetrics | null;
  desktop: ViewportTrapMetrics | null;
  /** Backend-authoritative verdict for the attempt (never recomputed). */
  backendVerdict: string | null;
  backendPassed: boolean | null;
}

export interface ScorecardData {
  current: AttemptTrapSnapshot | null;
  best: AttemptTrapSnapshot | null;
}

function finiteOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function viewportMetricsOf(attempt: SelfHealingAttempt | undefined, viewport: "mobile" | "desktop"): ViewportTrapMetrics | null {
  const raw: ViewportMetrics | undefined = attempt?.viewport_metrics?.[viewport];
  if (!raw || typeof raw !== "object") return null;
  return {
    vr: finiteOrNull(raw.v_r),
    iou: finiteOrNull(raw.iou),
    deltaX: finiteOrNull(raw.delta_x),
    passed: typeof raw.passed === "boolean" ? raw.passed : null,
    failureReasons: Array.isArray(raw.failure_reasons) ? raw.failure_reasons.map(String) : [],
  };
}

function snapshotOf(attempt: SelfHealingAttempt, label: string): AttemptTrapSnapshot {
  return {
    attemptNumber: attempt.attempt_number,
    label,
    mobile: viewportMetricsOf(attempt, "mobile"),
    desktop: viewportMetricsOf(attempt, "desktop"),
    backendVerdict:
      typeof attempt.verification_status === "string" && attempt.verification_status
        ? attempt.verification_status
        : null,
    backendPassed: typeof attempt.passed === "boolean" ? attempt.passed : null,
  };
}

/**
 * Current attempt = latest recorded attempt. Best = latest passed attempt
 * (explicitly labeled, never conflated with current). Legacy single-metric
 * attempts (verified_* only) have no per-viewport split, so their
 * per-viewport metrics stay null rather than being duplicated onto both.
 */
export function getScorecard(run: PRRun | null): ScorecardData {
  const attempts = run?.attempts ?? [];
  if (attempts.length === 0) return { current: null, best: null };
  const sorted = [...attempts].sort((a, b) => a.attempt_number - b.attempt_number);
  const latest = sorted[sorted.length - 1];
  const current = snapshotOf(latest, `Attempt ${latest.attempt_number} · latest`);
  const passedAttempts = sorted.filter((a) => a.passed === true);
  const bestAttempt = passedAttempts.length > 0 ? passedAttempts[passedAttempts.length - 1] : null;
  const best =
    bestAttempt && bestAttempt.attempt_number !== latest.attempt_number
      ? snapshotOf(bestAttempt, `Attempt ${bestAttempt.attempt_number} · best (passed)`)
      : null;
  return { current, best };
}

// ---------------------------------------------------------------------------
// LCA triage (Node 2)
// ---------------------------------------------------------------------------

export interface LCATreeNode {
  key: string;
  /** DOM tag/component label, e.g. "main" or "CheckoutForm". */
  label: string;
  visorElId: string | null;
  isLCA: boolean;
  children: LCATreeNode[];
}

export interface TriageData {
  lcaElementId: string | null;
  lcaChain: LCATreeNode[];
  /** Why the LCA was selected (backend triage summary), when reported. */
  lcaReason: string | null;
  triageStatus: string | null;
  confidence: number | null;
  targets: string[];
  rejected: TriageRejectedTarget[];
  filteredIntentional: string[];
  /** Node 2 token-reduction telemetry (Workstream 4), when hydrated. */
  tokenReductionRatio?: number | null;
  candidateFiles?: string[];
}

function descriptorId(d: NodeDescriptorInfo): string | null {
  const v = d["data-visor-el-id"] ?? d.visor_el_id;
  return typeof v === "string" && v ? v : null;
}

function descriptorLabel(d: NodeDescriptorInfo): string {
  const tag = typeof d.tag === "string" && d.tag ? d.tag : "";
  const hint = typeof d.react_hint === "string" && d.react_hint ? d.react_hint : "";
  const testid = typeof d["data-testid" as keyof NodeDescriptorInfo] === "string"
    ? String(d["data-testid" as keyof NodeDescriptorInfo])
    : "";
  return hint || tag || testid || "element";
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function chainFromDescriptors(descriptors: unknown[], lcaId: string | null): LCATreeNode[] {
  // Linear ancestor list (outermost -> innermost) rendered as nested chain.
  let root: LCATreeNode | null = null;
  let parent: LCATreeNode | null = null;
  descriptors.forEach((raw, i) => {
    const rec = asRecord(raw);
    if (!rec) return;
    const d = rec as NodeDescriptorInfo;
    const vid = descriptorId(d);
    const node: LCATreeNode = {
      key: `${vid ?? descriptorLabel(d)}-${i}`,
      label: descriptorLabel(d),
      visorElId: vid,
      isLCA: lcaId !== null && vid === lcaId,
      children: [],
    };
    if (!root) root = node;
    if (parent) parent.children = [node];
    parent = node;
  });
  return root ? [root] : [];
}

/** BR-2 display mirror: protected shared UI primitives (triage.py globs). */
export function isProtectedUiPath(path: string): boolean {
  const normalized = path.replace(/\\/g, "/");
  return normalized.startsWith("src/components/ui/") || normalized.includes("/components/ui/");
}

export function getTriage(run: PRRun | null): TriageData {
  const empty: TriageData = {
    lcaElementId: null,
    lcaChain: [],
    lcaReason: null,
    triageStatus: null,
    confidence: null,
    targets: [],
    rejected: [],
    filteredIntentional: [],
  };
  const spec = asRecord(run?.repair_spec);
  if (!spec) return empty;

  const lcaId = typeof spec.lca_element_id === "string" && spec.lca_element_id ? spec.lca_element_id : null;

  // Ancestor chain: prefer hierarchy records' ancestor_chain, then an
  // explicit lca_dom.ancestor_chain. No other nesting is assumed.
  let chain: LCATreeNode[] = [];
  const hierarchyRaw = spec.hierarchy ?? spec.lca_records;
  if (Array.isArray(hierarchyRaw)) {
    for (const rec of hierarchyRaw) {
      const recObj = asRecord(rec);
      const ancestors = recObj?.ancestor_chain;
      if (Array.isArray(ancestors) && ancestors.length > 0) {
        chain = chainFromDescriptors(ancestors, lcaId);
        break;
      }
    }
  }
  if (chain.length === 0) {
    const lcaDom = asRecord(spec.lca_dom);
    const ancestors = lcaDom?.ancestor_chain;
    if (Array.isArray(ancestors) && ancestors.length > 0) {
      chain = chainFromDescriptors(ancestors, lcaId);
    } else if (lcaDom && (lcaDom.tag || lcaDom["data-visor-el-id"] || lcaDom.visor_el_id)) {
      chain = chainFromDescriptors([lcaDom], lcaId);
    }
  }

  const targetsRaw = spec.target_files;
  const targets = Array.isArray(targetsRaw)
    ? targetsRaw.filter((t): t is string => typeof t === "string" && t.length > 0)
    : [];

  const rejectedRaw = spec.triage_rejected_targets;
  const rejected: TriageRejectedTarget[] = Array.isArray(rejectedRaw)
    ? rejectedRaw
        .map((r) => asRecord(r))
        .filter((r): r is Record<string, unknown> => r !== null)
        .map((r) => ({
          path: typeof r.path === "string" ? r.path : "",
          reason: typeof r.reason === "string" ? r.reason : "unknown",
        }))
        .filter((r) => r.path.length > 0)
    : [];

  const filteredRaw = spec.filtered_intentional_element_ids;
  const filteredIntentional = Array.isArray(filteredRaw)
    ? filteredRaw.filter((t): t is string => typeof t === "string")
    : [];

  return {
    lcaElementId: lcaId,
    lcaChain: chain,
    lcaReason: typeof spec.triage_summary === "string" && spec.triage_summary ? spec.triage_summary : null,
    triageStatus: typeof spec.triage_status === "string" && spec.triage_status ? spec.triage_status : null,
    confidence: finiteOrNull(spec.triage_confidence),
    targets,
    rejected,
    filteredIntentional,
  };
}

// ---------------------------------------------------------------------------
// Architect / coder inspector (Nodes 3 + 4 + sandbox)
// ---------------------------------------------------------------------------

export type BuildState = "pending" | "running" | "success" | "failed" | "unavailable";

export interface InspectorData {
  /** RepairSpec JSON (latest attempt wins, else merged run spec diagnosis). */
  repairSpec: RepairSpecPayload | null;
  repairSpecSource: string | null;
  /** Unified diff + where it came from. */
  diff: string | null;
  diffSource: string | null;
  /** Whether the backend reports this diff applied; null = unknown. */
  diffApplied: boolean | null;
  build: BuildState;
  buildDetail: string | null;
  /** SHA-256 integrity (Workstream 4), when hydrated from patch telemetry. */
  integrity?: {
    diffSha256: string | null;
    preSha256: string | null;
    postSha256: string | null;
  } | null;
  /** BR-2/BR-3/BR-4 guardrail flags (Workstream 4), when hydrated. */
  guardrails?: {
    br2UiLocked: boolean | null;
    br3DesktopPreserved: boolean | null;
    br4NoHacks: boolean | null;
  } | null;
  /** Node 5 strike decision (Workstream 4), when hydrated. */
  decision?: string | null;
}

const APPLIED_PHASES = new Set([
  "patch_applied",
  "compilation_succeeded",
  "compilation_succeeded",
  "hmr_observed",
  "visual_verified",
]);

/**
 * Build status from the existing sandbox contract (`SandboxMetadata` +
 * `HMRStatus`). A patch existing is never enough for success; success
 * requires a compilation/HMR/visual phase from the sandbox.
 */
export function deriveBuild(run: PRRun | null): { build: BuildState; detail: string | null; applied: boolean | null } {
  const sandbox = run?.sandbox;
  const phase = typeof sandbox?.last_patch_phase === "string" ? sandbox.last_patch_phase : "";
  const hmrStatus = typeof sandbox?.last_hmr_status === "string" ? sandbox.last_hmr_status : "";
  const serverState = typeof sandbox?.server_state === "string" ? sandbox.server_state : "";

  const applied = sandbox ? APPLIED_PHASES.has(phase) : null;

  if (!sandbox && (run?.attempts?.length ?? 0) === 0 && !run?.current_patch && !run?.best_patch) {
    return { build: "unavailable", detail: "Sandbox did not report build state", applied };
  }
  if (hmrStatus === "compile_failed" || serverState === "crashed") {
    return { build: "failed", detail: `Build failed${hmrStatus ? ` · HMR ${hmrStatus}` : ""}${serverState ? ` · server ${serverState}` : ""}`, applied };
  }
  if (phase === "hmr_observed" || phase === "visual_verified" || phase === "compilation_succeeded") {
    return { build: "success", detail: `Phase ${phase}${hmrStatus ? ` · HMR ${hmrStatus}` : ""}`, applied };
  }
  if (applied || serverState === "starting" || serverState === "running") {
    return {
      build: "running",
      detail: phase ? `Phase ${phase}` : `Server ${serverState}`,
      applied,
    };
  }
  if (sandbox) {
    return { build: "pending", detail: "Patch not applied yet", applied };
  }
  return { build: "unavailable", detail: "Sandbox did not report build state", applied };
}

const SPEC_FIELDS = [
  "root_cause",
  "affected_selectors",
  "target_file",
  "css_strategy",
  "desktop_preservation_constraints",
  "forbidden_hacks",
] as const;

export function getInspector(run: PRRun | null): InspectorData {
  const attempts = [...(run?.attempts ?? [])].sort((a, b) => a.attempt_number - b.attempt_number);
  const latest = attempts[attempts.length - 1];

  let repairSpec: RepairSpecPayload | null = null;
  let repairSpecSource: string | null = null;
  for (let i = attempts.length - 1; i >= 0; i -= 1) {
    const candidate = attempts[i].repair_spec;
    if (candidate && typeof candidate === "object" && Object.keys(candidate).length > 0) {
      repairSpec = candidate;
      repairSpecSource = `Attempt ${attempts[i].attempt_number}`;
      break;
    }
  }
  if (!repairSpec) {
    const merged = asRecord(run?.repair_spec);
    if (merged) {
      const picked: RepairSpecPayload = {};
      for (const field of SPEC_FIELDS) {
        if (field in merged) picked[field] = merged[field] as never;
      }
      if (Object.keys(picked).length > 0) {
        repairSpec = picked;
        repairSpecSource = "Run repair_spec (merged)";
      }
    }
  }

  let diff: string | null = null;
  let diffSource: string | null = null;
  for (let i = attempts.length - 1; i >= 0; i -= 1) {
    const unified = attempts[i].unified_diff;
    if (typeof unified === "string" && unified) {
      diff = unified;
      diffSource = `Attempt ${attempts[i].attempt_number} unified_diff`;
      break;
    }
    const legacy = attempts[i].patch_diff;
    if (typeof legacy === "string" && legacy) {
      diff = legacy;
      diffSource = `Attempt ${attempts[i].attempt_number} patch`;
      break;
    }
  }
  if (!diff && run?.best_patch) {
    diff = run.best_patch;
    diffSource = "Best verified patch";
  }
  if (!diff && run?.current_patch) {
    diff = run.current_patch;
    diffSource = "Current patch (unverified)";
  }
  void latest;

  const { build, detail, applied } = deriveBuild(run);
  return { repairSpec, repairSpecSource, diff, diffSource, diffApplied: applied, build, buildDetail: detail };
}
