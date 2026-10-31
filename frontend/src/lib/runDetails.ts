/**
 * Live run-details adapters (Workstreams 2-4).
 *
 * Maps the rich `GET /api/runs/{id}` payload (backend/core/artifacts.py)
 * onto the existing DualViewportStage + RightTelemetryDrawer view models.
 * Artifact URLs resolve against the API base; metrics/verdicts pass
 * through from the backend (threshold display only, no new verdicts).
 */

import type {
  AttemptTelemetry,
  NodeDescriptorInfo,
  RunDetails,
  ViewportSummary,
} from "@/types";
import type { HMRInfo, StageElement, ViewportPanelData } from "@/lib/viewportArtifacts";
import { VIEWPORT_SPECS } from "@/lib/viewportArtifacts";
import type {
  AttemptTrapSnapshot,
  InspectorData,
  LCATreeNode,
  TriageData,
  ViewportTrapMetrics,
} from "@/lib/telemetryDrawer";

/** Resolve a backend artifact path (e.g. /api/artifacts/...) for <img>. */
export function resolveArtifactUrl(url: string | null, apiBase: string): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  const base = apiBase.replace(/\/$/, "");
  return url.startsWith("/") ? `${base}${url}` : `${base}/${url}`;
}

export function attemptOptions(details: RunDetails | null): { attemptNumber: number; label: string }[] {
  if (!details) return [];
  return details.attempts.map((a) => ({
    attemptNumber: a.attempt_number,
    label: a.attempt_number === 0 ? "Baseline" : `Strike ${a.attempt_number}`,
  }));
}

export function latestAttemptNumber(details: RunDetails | null): number {
  if (!details || details.attempts.length === 0) return 0;
  return Math.max(...details.attempts.map((a) => a.attempt_number));
}

export function attemptByNumber(details: RunDetails | null, n: number): AttemptTelemetry | null {
  if (!details) return null;
  return details.attempts.find((a) => a.attempt_number === n) ?? null;
}

// ---------------------------------------------------------------------------
// DualViewportStage panels for one selected attempt
// ---------------------------------------------------------------------------

function elementsForAttempt(attempt: AttemptTelemetry, viewport: "mobile" | "desktop"): StageElement[] {
  const spec = VIEWPORT_SPECS[viewport];
  const maskUrl = attempt.sam_masks?.[viewport]?.mask_url ?? null;
  const metrics = attempt.element_metrics ?? [];
  const boxes = attempt.b_dom_boxes ?? {};
  const ids = new Set<string>([...Object.keys(boxes), ...metrics.map((m) => m.visor_el_id)]);
  const out: StageElement[] = [];
  for (const id of ids) {
    const metric = metrics.find((m) => m.visor_el_id === id) ?? null;
    // Element metrics are viewport-tagged in the payload; never mix panels.
    if (metric?.viewport) {
      const tag = String(metric.viewport).toLowerCase();
      const isMobile = tag.startsWith("375") || tag === "mobile";
      if ((viewport === "mobile") !== isMobile && (tag.startsWith("1440") || tag === "desktop" || isMobile)) {
        // fall through only when the tag matches this viewport
        if (viewport === "mobile" && !isMobile) continue;
        if (viewport === "desktop" && isMobile) continue;
      }
    }
    const box = boxes[id] ?? null;
    out.push({
      id,
      box: box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null,
      defectType: metric?.defect_type ?? null,
      vr: metric?.v_r ?? null,
      iou: metric?.iou ?? null,
      deltaX: metric?.delta_x ?? null,
      status: metric?.trap_fired ?? null,
      // The persisted mask is a full-viewport union PNG; attaching it to
      // each measured element renders identical pixels (no invented shape).
      masks:
        maskUrl && metric
          ? [{ kind: "image", url: maskUrl, width: spec.width, height: spec.height }]
          : [],
      maskState: maskUrl && metric ? "available" : "unavailable",
    });
  }
  return out;
}

function verificationOf(summary: ViewportSummary | undefined, status: string | null) {
  if (!summary) return null;
  return {
    vr: summary.v_r,
    iou: summary.iou,
    deltaX: summary.delta_x,
    passed: summary.passed,
    status,
  };
}

export interface StageAttemptView {
  mobile: ViewportPanelData;
  desktop: ViewportPanelData;
  hmr: HMRInfo | null;
  sandboxProvider: string | null;
  hmrLatencyMs: number | null;
}

export function stageForAttempt(
  details: RunDetails,
  attemptNumber: number,
  apiBase: string,
): StageAttemptView {
  const attempt = attemptByNumber(details, attemptNumber) ?? details.attempts[0];
  const baseline = attemptByNumber(details, 0);
  const feedbackStatus = attempt.verification_feedback?.verification_status ?? null;
  const patch = attempt.patch_telemetry;

  const panel = (viewport: "mobile" | "desktop"): ViewportPanelData => {
    const shots = attempt.screenshots?.[viewport];
    const baseShots = baseline?.screenshots?.[viewport];
    return {
      viewport,
      beforeUrl: resolveArtifactUrl(shots?.before_url ?? baseShots?.before_url ?? null, apiBase),
      afterUrl: resolveArtifactUrl(shots?.after_url ?? null, apiBase),
      elements: elementsForAttempt(attempt, viewport),
      verification: verificationOf(attempt.viewport_summary?.[viewport], feedbackStatus),
    };
  };

  return {
    mobile: panel("mobile"),
    desktop: panel("desktop"),
    hmr: patch
      ? {
          observed: patch.hmr_status === "observed" || patch.sandbox_phase === "hmr_observed",
          phase: patch.sandbox_phase,
          status: patch.hmr_status,
          latencyMs: patch.hmr_latency_ms,
        }
      : null,
    sandboxProvider: patch?.sandbox_provider ?? null,
    hmrLatencyMs: patch?.hmr_latency_ms ?? null,
  };
}

// ---------------------------------------------------------------------------
// RightTelemetryDrawer bindings
// ---------------------------------------------------------------------------

function trapMetrics(summary: ViewportSummary | undefined): ViewportTrapMetrics | null {
  if (!summary) return null;
  return {
    vr: summary.v_r,
    iou: summary.iou,
    deltaX: summary.delta_x,
    passed: summary.passed,
    failureReasons: summary.failure_reasons ?? [],
  };
}

export function scorecardForAttempt(
  details: RunDetails,
  attemptNumber: number,
): { current: AttemptTrapSnapshot; baseline: AttemptTrapSnapshot | null } {
  const attempt = attemptByNumber(details, attemptNumber) ?? details.attempts[0];
  const toSnapshot = (a: AttemptTelemetry, label: string): AttemptTrapSnapshot => ({
    attemptNumber: a.attempt_number,
    label,
    mobile: trapMetrics(a.viewport_summary?.mobile),
    desktop: trapMetrics(a.viewport_summary?.desktop),
    backendVerdict: a.verification_feedback?.verification_status ?? null,
    backendPassed: a.verification_feedback?.dual_viewport_passed ?? null,
  });
  const current = toSnapshot(
    attempt,
    attempt.attempt_number === 0 ? "Attempt 0 · baseline" : `Attempt ${attempt.attempt_number} · selected strike`,
  );
  const baselineAttempt = attemptByNumber(details, 0);
  const baseline =
    baselineAttempt && attempt.attempt_number !== 0
      ? toSnapshot(baselineAttempt, "Attempt 0 · baseline (before)")
      : null;
  return { current, baseline };
}

function chainFromHierarchy(hierarchy: unknown, lcaId: string | null): LCATreeNode[] {
  if (!Array.isArray(hierarchy)) return [];
  for (const rec of hierarchy) {
    if (!rec || typeof rec !== "object") continue;
    const chain = (rec as Record<string, unknown>).ancestor_chain;
    if (!Array.isArray(chain) || chain.length === 0) continue;
    let root: LCATreeNode | null = null;
    let parent: LCATreeNode | null = null;
    chain.forEach((raw, i) => {
      if (!raw || typeof raw !== "object") return;
      const d = raw as NodeDescriptorInfo;
      const vid = d["data-visor-el-id"] ?? d.visor_el_id ?? null;
      const node: LCATreeNode = {
        key: `${vid ?? d.react_hint ?? d.tag ?? "el"}-${i}`,
        label: d.react_hint || d.tag || "element",
        visorElId: vid,
        isLCA: lcaId !== null && vid === lcaId,
        children: [],
      };
      if (!root) root = node;
      if (parent) parent.children = [node];
      parent = node;
    });
    if (root) return [root];
  }
  return [];
}

export function triageForRun(details: RunDetails): TriageData {
  const meta = details.triage_metadata;
  const lcaId = meta?.lca_element_id ?? null;
  let chain = chainFromHierarchy(meta?.hierarchy, lcaId);
  if (chain.length === 0 && meta?.lca_dom && typeof meta.lca_dom === "object") {
    const dom = meta.lca_dom as NodeDescriptorInfo;
    if (dom.tag || dom["data-visor-el-id"] || dom.visor_el_id) {
      chain = chainFromHierarchy([{ ancestor_chain: [dom] }], lcaId);
    }
  }
  return {
    lcaElementId: lcaId,
    lcaChain: chain,
    lcaReason: meta?.triage_summary ?? null,
    triageStatus: meta?.triage_status ?? null,
    confidence: meta?.triage_confidence ?? null,
    targets: meta?.target_files ?? [],
    rejected: meta?.rejected_targets ?? [],
    filteredIntentional: [],
    tokenReductionRatio: meta?.token_reduction_ratio ?? null,
    candidateFiles: meta?.candidate_files ?? [],
  };
}

const BUILD_MAP: Record<string, InspectorData["build"]> = {
  success: "success",
  failed: "failed",
  running: "running",
  pending: "pending",
  unavailable: "unavailable",
};

export function inspectorForAttempt(details: RunDetails, attemptNumber: number): InspectorData {
  const attempt = attemptByNumber(details, attemptNumber) ?? details.attempts[0];
  const patch = attempt.patch_telemetry;
  const feedback = attempt.verification_feedback;
  return {
    repairSpec: attempt.repair_spec ?? null,
    repairSpecSource: attempt.repair_spec
      ? `Attempt ${attempt.attempt_number} · Node 3 RepairSpec`
      : null,
    diff: attempt.unified_diff ?? patch?.unified_diff ?? null,
    diffSource: patch ? `Attempt ${attempt.attempt_number} · Node 4` : null,
    diffApplied: patch ? patch.applied_cleanly : null,
    build: BUILD_MAP[patch?.build_status ?? "unavailable"] ?? "unavailable",
    buildDetail: patch
      ? `Sandbox ${patch.sandbox_provider ?? "—"} · phase ${patch.sandbox_phase ?? "—"}`
      : null,
    integrity: patch
      ? {
          diffSha256: patch.diff_sha256,
          preSha256: patch.target_pre_sha256,
          postSha256: patch.target_post_sha256,
        }
      : null,
    guardrails: patch
      ? {
          br2UiLocked: patch.guardrails?.br2_ui_locked ?? null,
          br3DesktopPreserved: patch.guardrails?.br3_desktop_preserved ?? null,
          br4NoHacks: patch.guardrails?.br4_no_hacks ?? null,
        }
      : null,
    decision: feedback?.strike_decision ?? null,
  };
}
