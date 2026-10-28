"""
VisorQA Domain Logic - Mathematical Discrepancy Engine (NumPy)

Deterministic, vectorized pixel-discrepancy evaluation for one viewport:
visibility ratio (V_r), sibling-collision IoU, horizontal viewport bleed
(Delta_x), and a composite viewport health score.

Coordinate & rasterization conventions
--------------------------------------
* ``B_DOM`` is ``(x, y, width, height)`` in viewport-relative CSS pixels
  (origin top-left), as produced by ``getBoundingClientRect()`` in the
  browser pipeline (see ``backend.browser.schemas``). Float precision is
  preserved for bleed; rasterization uses the rule below.
* A segmentation mask ``M_SAM`` is a 2D array of shape
  ``(viewport_height, viewport_width)``: axis 0 is the pixel row (y),
  axis 1 the pixel column (x). Any dtype is accepted; pixels ``> 0``
  (or ``True``) are foreground.
* Rasterization is half-open: a box covers pixel columns
  ``[floor(x), ceil(x + width))`` and rows ``[floor(y), ceil(y + height))``,
  clipped to viewport bounds. ``Area(B_DOM)`` is the resulting clipped
  raster pixel count, so integer-aligned boxes give exact areas.
* ``V_r = Area(M_SAM ∩ B_DOM_raster) / Area(B_DOM_raster)``. The numerator
  is clipped to the box (and hence the viewport). The alternative
  un-clipped definition ``Area(M_SAM) / Area(B_DOM)`` (whole-mask area,
  counting mask pixels outside the box) is *not* used: it can exceed the
  visible coverage and conflates occlusion with mask spill.
* Threshold decisions use exact float64 comparisons (no hidden epsilon):
  V_r defect iff ``V_r < 0.85``; IoU defect iff ``IoU > 0.05``; bleed
  defect iff ``Delta_x > 2.0``. Metric values are returned unrounded.
* ``Delta_x = max(0, (x + width) - viewport_width)`` (right-side bleed
  only, per spec). Left-side overflow is exposed separately as
  ``delta_x_left = max(0, -x)`` and never changes the Delta_x verdict.

Invalid-data policy
-------------------
Structured evaluators never raise for bad per-element data and never count
it as passing. They return ``status="invalid"`` with an ``invalid_reason``
(``missing_mask``, ``invalid_mask``, ``mask_shape_mismatch``,
``invalid_box``, ``zero_area_box``, ``box_outside_viewport``,
``missing_element``). Low-level scalar helpers raise ``ValueError`` for
shape mismatches instead, matching their historic contract.

Composite health score
----------------------
The FSM's legacy ``compute_health_score`` (orchestrator:
``mean(V_r) - max(IoU) - 0.01 * max(bleed)``) is unchanged for best-patch
bookkeeping; it can leave [0, 1] and has no invalid-data accounting.
``compute_viewport_health`` here implements the transparent default from
the task: ``score = passing_valid_checks / valid_checks`` over visibility
(per element), collision (per configured pair), and bleed (per valid
element) checks. It is a pass fraction, not a perceptually calibrated
metric, and uses no invented weights. With no valid checks the score is
``None`` with status ``insufficient_data`` (JSON ``null``, consistent
with the project's optional-metric fields) rather than a claimed 1.0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from backend.config import settings

VR_THRESHOLD: float = float(settings.V_R_THRESHOLD)  # 0.85
IOU_THRESHOLD: float = float(settings.IOU_THRESHOLD)  # 0.05
BLEED_THRESHOLD_PX: float = 2.0


# ---------------------------------------------------------------------------
# Structured results
# ---------------------------------------------------------------------------

class VisibilityResult(BaseModel):
    element_id: str
    viewport: str = ""
    v_r: Optional[float] = None
    threshold: float = VR_THRESHOLD
    status: str = "invalid"  # pass | defect | invalid
    valid: bool = False
    invalid_reason: Optional[str] = None
    intersection_area: int = 0
    b_dom_area: int = 0

    @property
    def is_defect(self) -> bool:
        return self.status == "defect"


class CollisionResult(BaseModel):
    element_id: str
    sibling_id: str
    viewport: str = ""
    iou: Optional[float] = None
    threshold: float = IOU_THRESHOLD
    status: str = "invalid"  # pass | defect | invalid
    valid: bool = False
    invalid_reason: Optional[str] = None
    intersection_area: int = 0
    union_area: int = 0

    @property
    def is_defect(self) -> bool:
        return self.status == "defect"


class BleedResult(BaseModel):
    element_id: str
    viewport: str = ""
    delta_x: Optional[float] = None
    delta_x_left: Optional[float] = None  # separate optional metric
    threshold: float = BLEED_THRESHOLD_PX
    status: str = "invalid"  # pass | defect | invalid
    valid: bool = False
    invalid_reason: Optional[str] = None

    @property
    def is_defect(self) -> bool:
        return self.status == "defect"


class ViewportHealth(BaseModel):
    viewport: str = ""
    # None == insufficient data (serialized as JSON null, never faked 1.0)
    score: Optional[float] = None
    status: str = "insufficient_data"  # ok | insufficient_data
    valid_checks: int = 0
    invalid_checks: int = 0
    defect_checks: int = 0
    passing_checks: int = 0


class ViewportEvaluation(BaseModel):
    viewport: str = ""
    width: int = 0
    height: int = 0
    visibility: List[VisibilityResult] = Field(default_factory=list)
    collisions: List[CollisionResult] = Field(default_factory=list)
    bleed: List[BleedResult] = Field(default_factory=list)
    health: ViewportHealth = Field(default_factory=ViewportHealth)


@dataclass
class ElementMaskInput:
    """One element's geometry + mask. ``mask=None`` means missing."""

    element_id: str
    box: Any  # mapping, BoxSpec-like object, or (x, y, width, height)
    mask: Optional[np.ndarray] = None


class BoxSpec(BaseModel):
    x: float
    y: float
    width: float
    height: float


# ---------------------------------------------------------------------------
# Validation / coercion helpers
# ---------------------------------------------------------------------------

def _coerce_box(box: Any) -> Optional[BoxSpec]:
    try:
        if box is None:
            return None
        if isinstance(box, BoxSpec):
            data = box.model_dump()
        elif isinstance(box, dict):
            data = {k: box[k] for k in ("x", "y", "width", "height")}
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            data = dict(zip(("x", "y", "width", "height"), box))
        else:  # duck-typed DOMBoundingBox / ElementGeometry.b_dom
            data = {k: getattr(box, k) for k in ("x", "y", "width", "height")}
        spec = BoxSpec(**{k: float(v) for k, v in data.items()})
        if not all(math.isfinite(v) for v in spec.model_dump().values()):
            return None
        return spec
    except Exception:
        return None


def _box_invalid_reason(spec: BoxSpec) -> Optional[str]:
    if spec.width < 0 or spec.height < 0:
        return "invalid_box"
    if spec.width == 0 or spec.height == 0:
        return "zero_area_box"
    return None


def _as_bool_mask(mask: Any) -> Optional[np.ndarray]:
    if mask is None:
        return None
    try:
        arr = np.asarray(mask)
    except Exception:
        return None
    if arr.ndim != 2:
        return None
    if arr.dtype == bool:
        return arr
    try:
        return arr > 0
    except Exception:
        return None


def rasterize_box(
    box: Any, viewport_width: int, viewport_height: int
) -> np.ndarray:
    """Rasterize ``B_DOM`` to a boolean mask (half-open, clipped)."""
    spec = _coerce_box(box)
    mask = np.zeros((int(viewport_height), int(viewport_width)), dtype=bool)
    if spec is None or _box_invalid_reason(spec):
        return mask
    x0 = max(0, math.floor(spec.x))
    y0 = max(0, math.floor(spec.y))
    x1 = min(int(viewport_width), math.ceil(spec.x + spec.width))
    y1 = min(int(viewport_height), math.ceil(spec.y + spec.height))
    if x1 > x0 and y1 > y0:
        mask[y0:y1, x0:x1] = True
    return mask


def _clipped_area(spec: BoxSpec, vw: int, vh: int) -> int:
    x0 = max(0, math.floor(spec.x))
    y0 = max(0, math.floor(spec.y))
    x1 = min(vw, math.ceil(spec.x + spec.width))
    y1 = min(vh, math.ceil(spec.y + spec.height))
    return max(0, x1 - x0) * max(0, y1 - y0)


# ---------------------------------------------------------------------------
# Legacy scalar helpers (historic contracts preserved)
# ---------------------------------------------------------------------------

def calculate_visibility_ratio(sam_mask: np.ndarray, dom_box_mask: np.ndarray) -> float:
    """Legacy: V_r from two same-shape masks; empty DOM box returns 1.0."""
    sam = _as_bool_mask(sam_mask)
    dom = _as_bool_mask(dom_box_mask)
    if sam is None or dom is None or sam.shape != dom.shape:
        raise ValueError("masks must be 2D arrays with identical shapes")
    dom_area = int(np.count_nonzero(dom))
    if dom_area == 0:
        return 1.0
    inter = int(np.count_nonzero(sam & dom))
    return round(float(np.clip(inter / dom_area, 0.0, 1.0)), 4)


def calculate_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Legacy: IoU of two same-shape masks; empty union returns 0.0."""
    a = _as_bool_mask(mask_a)
    b = _as_bool_mask(mask_b)
    if a is None or b is None or a.shape != b.shape:
        raise ValueError("masks must be 2D arrays with identical shapes")
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 0.0
    inter = int(np.count_nonzero(a & b))
    return round(float(np.clip(inter / union, 0.0, 1.0)), 4)


def detect_bleed_overflow(mask: np.ndarray, viewport_shape: Tuple[int, int]) -> bool:
    """Legacy: True when the mask's shape exceeds ``(height, width)``."""
    h, w = viewport_shape
    mask_h, mask_w = mask.shape
    return mask_w > w or mask_h > h


# ---------------------------------------------------------------------------
# Structured evaluators
# ---------------------------------------------------------------------------

def evaluate_visibility(
    element_id: str,
    mask: Optional[np.ndarray],
    box: Any,
    viewport_width: int,
    viewport_height: int,
    viewport: str = "",
    threshold: float = VR_THRESHOLD,
) -> VisibilityResult:
    """V_r for one element; invalid data is reported, never passed."""
    res = VisibilityResult(element_id=element_id, viewport=viewport,
                           threshold=float(threshold))
    spec = _coerce_box(box)
    if spec is None:
        res.invalid_reason = "invalid_box"
        return res
    reason = _box_invalid_reason(spec)
    if reason:
        res.invalid_reason = reason
        return res
    area = _clipped_area(spec, int(viewport_width), int(viewport_height))
    if area == 0:
        res.invalid_reason = "box_outside_viewport"
        return res
    res.b_dom_area = area
    if mask is None:
        res.invalid_reason = "missing_mask"
        return res
    sam = _as_bool_mask(mask)
    if sam is None:
        res.invalid_reason = "invalid_mask"
        return res
    if sam.shape != (int(viewport_height), int(viewport_width)):
        res.invalid_reason = "mask_shape_mismatch"
        return res
    dom = rasterize_box(spec, int(viewport_width), int(viewport_height))
    inter = int(np.count_nonzero(sam & dom))  # vectorized pixel work
    res.intersection_area = inter
    res.v_r = float(inter / area)
    res.valid = True
    res.status = "defect" if res.v_r < float(threshold) else "pass"
    return res


def evaluate_iou_pair(
    element_id: str,
    sibling_id: str,
    mask_a: Optional[np.ndarray],
    mask_b: Optional[np.ndarray],
    viewport: str = "",
    threshold: float = IOU_THRESHOLD,
) -> CollisionResult:
    """IoU for one configured sibling pair."""
    res = CollisionResult(element_id=element_id, sibling_id=sibling_id,
                          viewport=viewport, threshold=float(threshold))
    if mask_a is None or mask_b is None:
        res.invalid_reason = "missing_mask"
        return res
    a = _as_bool_mask(mask_a)
    b = _as_bool_mask(mask_b)
    if a is None or b is None:
        res.invalid_reason = "invalid_mask"
        return res
    if a.shape != b.shape:
        res.invalid_reason = "mask_shape_mismatch"
        return res
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    res.intersection_area = inter
    res.union_area = union
    # Empty union (both masks empty): defined IoU 0.0, a valid pass.
    res.iou = float(inter / union) if union else 0.0
    res.valid = True
    res.status = "defect" if res.iou > float(threshold) else "pass"
    return res


def evaluate_bleed(
    element_id: str,
    box: Any,
    viewport_width: int,
    viewport: str = "",
    threshold: float = BLEED_THRESHOLD_PX,
) -> BleedResult:
    """Delta_x = max(0, x + width - viewport_width); float preserved."""
    res = BleedResult(element_id=element_id, viewport=viewport,
                      threshold=float(threshold))
    spec = _coerce_box(box)
    if spec is None or spec.width < 0 or spec.height < 0:
        res.invalid_reason = "invalid_box"
        return res
    if spec.width == 0 or spec.height == 0:
        res.invalid_reason = "zero_area_box"
        return res
    res.delta_x = float(max(0.0, (spec.x + spec.width) - float(viewport_width)))
    res.delta_x_left = float(max(0.0, -spec.x))
    res.valid = True
    res.status = "defect" if res.delta_x > float(threshold) else "pass"
    return res


def compute_viewport_health(
    visibility: Sequence[VisibilityResult] = (),
    collisions: Sequence[CollisionResult] = (),
    bleed: Sequence[BleedResult] = (),
    viewport: str = "",
) -> ViewportHealth:
    """Pass fraction over valid checks; None when no valid checks exist."""
    groups = (list(visibility), list(collisions), list(bleed))
    valid = sum(1 for g in groups for r in g if r.valid)
    invalid = sum(1 for g in groups for r in g if not r.valid)
    defects = sum(1 for g in groups for r in g if r.valid and r.is_defect)
    passing = valid - defects
    health = ViewportHealth(viewport=viewport, valid_checks=valid,
                            invalid_checks=invalid, defect_checks=defects,
                            passing_checks=passing)
    if valid == 0:
        return health  # score stays None, status insufficient_data
    health.score = float(min(1.0, max(0.0, passing / valid)))
    health.status = "ok"
    return health


def sibling_pairs_from_hierarchy(records: Sequence[Any]) -> List[Tuple[str, str]]:
    """Configured sibling pairs from LCA ``adjacent_sibling_pair`` records."""
    pairs: List[Tuple[str, str]] = []
    for rec in records or []:
        rel = getattr(rec, "relationship", None) or (
            rec.get("relationship") if isinstance(rec, dict) else None)
        ids = getattr(rec, "element_ids", None) or (
            rec.get("element_ids") if isinstance(rec, dict) else None)
        if rel == "adjacent_sibling_pair" and ids and len(ids) == 2:
            pair = (str(ids[0]), str(ids[1]))
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def evaluate_viewport(
    elements: Sequence[Any],
    masks: Optional[Dict[str, Optional[np.ndarray]]] = None,
    sibling_pairs: Sequence[Tuple[str, str]] = (),
    viewport: str = "",
    width: int = 0,
    height: int = 0,
    vr_threshold: float = VR_THRESHOLD,
    iou_threshold: float = IOU_THRESHOLD,
    bleed_threshold: float = BLEED_THRESHOLD_PX,
) -> ViewportEvaluation:
    """Evaluate V_r, IoU (configured pairs only), and bleed for a viewport.

    ``elements`` may be ``ElementMaskInput``, mappings with
    ``element_id``/``visor_el_id`` + ``box``/``B_DOM``/``b_dom``, or
    browser ``ElementGeometry`` objects (duck-typed). ``masks`` maps
    element ID to ``M_SAM``; IDs absent from the map count as missing.
    Only ``sibling_pairs`` are collision-checked (never all pairs).
    """
    masks = masks or {}
    inputs: List[ElementMaskInput] = []
    for el in elements or []:
        if isinstance(el, ElementMaskInput):
            inputs.append(el)
        elif isinstance(el, dict):
            eid = str(el.get("element_id") or el.get("visor_el_id")
                      or el.get("id") or "")
            box = el.get("box") or el.get("B_DOM") or el.get("b_dom") or el
            inputs.append(ElementMaskInput(
                eid, box, el.get("mask", masks.get(eid))))
        else:  # ElementGeometry-like
            eid = str(getattr(el, "visor_el_id", "") or
                      getattr(el, "element_id", ""))
            box = getattr(el, "b_dom", None) or getattr(el, "B_DOM", None)
            inputs.append(ElementMaskInput(
                eid, box, getattr(el, "mask", masks.get(eid))))
    by_id = {e.element_id: e for e in inputs}
    visibility = [
        evaluate_visibility(e.element_id, e.mask, e.box, width, height,
                            viewport, vr_threshold) for e in inputs
    ]
    bleed = [
        evaluate_bleed(e.element_id, e.box, width, viewport, bleed_threshold)
        for e in inputs
    ]
    collisions: List[CollisionResult] = []
    for id_a, id_b in sibling_pairs or []:
        a, b = by_id.get(str(id_a)), by_id.get(str(id_b))
        if a is None or b is None:
            missing = CollisionResult(element_id=str(id_a),
                                      sibling_id=str(id_b), viewport=viewport,
                                      threshold=float(iou_threshold))
            missing.invalid_reason = "missing_element"
            collisions.append(missing)
        else:
            collisions.append(evaluate_iou_pair(
                a.element_id, b.element_id, a.mask, b.mask,
                viewport, iou_threshold))
    health = compute_viewport_health(visibility, collisions, bleed, viewport)
    return ViewportEvaluation(viewport=viewport, width=int(width),
                              height=int(height), visibility=visibility,
                              collisions=collisions, bleed=bleed,
                              health=health)
