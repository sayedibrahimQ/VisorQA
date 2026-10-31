/**
 * Viewport artifact contracts + adapter for DualViewportStage.
 *
 * Reuses the real backend contracts (nothing invented):
 * - B_DOM boxes are viewport-relative CSS px, 1:1 with native-size
 *   screenshots (`backend/browser/schemas.py`, `device_scale_factor=1`).
 * - Overlay colors: dashed cyan `#00F0FF` boxes, crimson `#F43F5E` masks at
 *   35% opacity (`backend/browser/overlay.py`).
 * - SAM masks are per-`visor_el_id` binary bitmaps; the backend serializes
 *   no polygons/contours today, so raster masks arrive (when served) as
 *   image artifacts and are rendered via an SVG luminance mask — never
 *   approximated with rectangles.
 * - HMR/sandbox phases (`backend/sandbox/interface.py`): success is claimed
 *   only when status is exactly `observed`.
 * - Verification verdicts are display-only backend values (`passed`,
 *   `verification_status`); this module never recomputes pass/fail from
 *   metrics, so `backend/core/verify.py` stays the single metric engine.
 */

import type { Anomaly, PRRun } from "@/types";

export type ViewportName = "mobile" | "desktop";

export interface ViewportSpec {
  name: ViewportName;
  width: number;
  height: number;
  /** Human label, e.g. "375×812". */
  label: string;
}

export const VIEWPORT_SPECS: Record<ViewportName, ViewportSpec> = {
  mobile: { name: "mobile", width: 375, height: 812, label: "375×812" },
  desktop: { name: "desktop", width: 1440, height: 900, label: "1440×900" },
};

export const DOM_BOX_STROKE = "#00F0FF";
export const SAM_MASK_FILL = "#F43F5E";
export const SAM_MASK_OPACITY = 0.35;

export interface StageBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface StagePoint {
  x: number;
  y: number;
}

export type StageMask =
  | { kind: "polygon"; points: StagePoint[] }
  | { kind: "contour"; points: StagePoint[] }
  | { kind: "image"; url: string; width: number; height: number };

export type MaskState = "available" | "unavailable" | "mismatch";

export interface StageElement {
  id: string;
  box: StageBox | null;
  defectType: string | null;
  vr: number | null;
  iou: number | null;
  deltaX: number | null;
  status: string | null;
  masks: StageMask[];
  maskState: MaskState;
}

export interface ViewportVerification {
  vr: number | null;
  iou: number | null;
  deltaX: number | null;
  /** Backend verdict only; null means unverified/unknown. */
  passed: boolean | null;
  status: string | null;
}

export interface ViewportPanelData {
  viewport: ViewportName;
  beforeUrl: string | null;
  afterUrl: string | null;
  elements: StageElement[];
  verification: ViewportVerification | null;
}

export interface HMRInfo {
  /** True only when the sandbox reported status `observed`. */
  observed: boolean;
  phase: string | null;
  status: string | null;
  latencyMs: number | null;
}

export interface StageData {
  runId: string | null;
  runLabel: string | null;
  mobile: ViewportPanelData;
  desktop: ViewportPanelData;
  hmr: HMRInfo | null;
  /** Elements without a viewport tag — counted, never mixed into a panel. */
  untaggedCount: number;
}

// ---------------------------------------------------------------------------
// Validation (invalid geometry is dropped, never repaired or invented)
// ---------------------------------------------------------------------------

function finite(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

export function toStageBox(raw: unknown): StageBox | null {
  if (!raw || typeof raw !== "object") return null;
  const { x, y, width, height } = raw as Record<string, unknown>;
  if (!finite(x) || !finite(y) || !finite(width) || !finite(height)) return null;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function toPoints(raw: unknown, min: number): StagePoint[] | null {
  if (!Array.isArray(raw) || raw.length < min) return null;
  const points: StagePoint[] = [];
  for (const p of raw) {
    if (!p || typeof p !== "object") return null;
    const { x, y } = p as Record<string, unknown>;
    if (!finite(x) || !finite(y)) return null;
    points.push({ x, y });
  }
  return points;
}

/**
 * Validate one raw mask payload. Raster images must match the viewport
 * dimensions exactly — mirroring `overlay.py`, mismatched masks are
 * reported, never stretched.
 */
export function toStageMask(raw: unknown, spec: ViewportSpec): { mask: StageMask | null; mismatch: boolean } {
  if (!raw || typeof raw !== "object") return { mask: null, mismatch: false };
  const payload = raw as Record<string, unknown>;
  if (payload.kind === "polygon") {
    const points = toPoints(payload.points, 3);
    return { mask: points ? { kind: "polygon", points } : null, mismatch: false };
  }
  if (payload.kind === "contour") {
    const points = toPoints(payload.points, 2);
    return { mask: points ? { kind: "contour", points } : null, mismatch: false };
  }
  if (payload.kind === "image") {
    const { url, width, height } = payload;
    if (typeof url !== "string" || !url || !finite(width) || !finite(height)) {
      return { mask: null, mismatch: false };
    }
    if (width !== spec.width || height !== spec.height) {
      return { mask: null, mismatch: true };
    }
    return { mask: { kind: "image", url, width, height }, mismatch: false };
  }
  return { mask: null, mismatch: false };
}

export function toMetric(raw: unknown): number | null {
  return finite(raw) ? raw : null;
}

/** Display formatting only ("0.62"); null renders the unavailable marker. */
export function formatMetric(value: number | null, digits = 2): string | null {
  if (value === null) return null;
  return value.toFixed(digits);
}

export function viewportFromTag(tag: unknown): ViewportName | null {
  if (typeof tag !== "string") return null;
  const t = tag.trim().toLowerCase();
  if (t === "mobile" || t === "375px" || t === "375") return "mobile";
  if (t === "desktop" || t === "1440px" || t === "1440") return "desktop";
  return null;
}

// ---------------------------------------------------------------------------
// Adapter: PRRun (+ embedded anomalies/attempts when present) -> StageData
// ---------------------------------------------------------------------------

function emptyPanel(viewport: ViewportName): ViewportPanelData {
  return { viewport, beforeUrl: null, afterUrl: null, elements: [], verification: null };
}

function elementFromAnomaly(a: Anomaly): StageElement {
  // sam_mask_path is a backend-local path with no serving URL contract, so
  // it cannot be rendered; masks stay unavailable until served artifacts or
  // serialized geometry exist. Never fall back to box-as-mask rectangles.
  return {
    id: a.element_id || a.id,
    box: toStageBox(a.bounding_box),
    defectType: typeof a.defect_type === "string" ? a.defect_type : null,
    vr: toMetric(a.visibility_ratio),
    iou: toMetric(a.iou_score),
    deltaX: toMetric(a.bleed_px),
    status: typeof a.status === "string" ? a.status : null,
    masks: [],
    maskState: "unavailable",
  };
}

/**
 * Build stage props from a streamed run. Everything the backend does not
 * provide today (screenshots, masks, HMR state, per-viewport verification)
 * comes back explicitly null so the UI renders unavailable placeholders.
 */
export function adaptRunToStage(run: PRRun | null): StageData {
  const mobile = emptyPanel("mobile");
  const desktop = emptyPanel("desktop");
  if (!run) {
    return { runId: null, runLabel: null, mobile, desktop, hmr: null, untaggedCount: 0 };
  }
  let untaggedCount = 0;
  for (const anomaly of run.anomalies ?? []) {
    const slot = viewportFromTag(anomaly.viewport);
    if (!slot) {
      untaggedCount += 1;
      continue;
    }
    (slot === "mobile" ? mobile : desktop).elements.push(elementFromAnomaly(anomaly));
  }
  return {
    runId: run.id,
    runLabel: `${run.repo_name} PR #${run.pr_number}`,
    mobile,
    desktop,
    hmr: null,
    untaggedCount,
  };
}
