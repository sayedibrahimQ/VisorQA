"""Node 5 deterministic dual-viewport verification.

Resolution (both viewports, unrounded): V_r >= 0.98, IoU == 0, Delta_x <= 2px.
Missing/NaN/inf/invalid metrics are failures, never zero defects.
Score: mean(V_r_mobile, V_r_desktop) - max(IoU) - 0.01*max(Delta_x),
computed only when both viewports are complete/valid (else None, not
comparable). This mirrors legacy compute_health_score semantics while
keeping viewports separate for the verdict.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

VR_MIN = 0.98
IOU_REQUIRED = 0.0
DELTA_X_MAX = 2.0
VIEWPORTS = {"mobile": (375, 812), "desktop": (1440, 900)}
_ALIASES = {"mobile": "mobile", "375": "mobile", "375px": "mobile",
            "desktop": "desktop", "1440": "desktop", "1440px": "desktop"}


def _finite(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def viewport_name(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    return _ALIASES.get(s) or _ALIASES.get(s.replace(" ", ""))


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def normalize_viewport_metrics(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize dict/list viewport evidence to {mobile:{...}, desktop:{...}}."""
    out: Dict[str, Dict[str, Any]] = {}
    entries: List[Any] = []
    if isinstance(raw, dict):
        # keyed by viewport name/width, or a single viewport dict
        if any(k in raw for k in ("v_r", "V_r", "visibility_ratio", "iou", "IoU")):
            entries = [raw]
        else:
            entries = [{"viewport": k, **v} if isinstance(v, dict) else {"viewport": k, "value": v}
                       for k, v in raw.items()]
    elif isinstance(raw, list):
        entries = list(raw)
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = viewport_name(e.get("viewport") or e.get("name") or e.get("width"))
        if not name:
            continue
        w, h = VIEWPORTS[name]
        out[name] = {
            "viewport": name, "width": int(e.get("width") or w), "height": int(e.get("height") or h),
            "v_r": _pick(e, "v_r", "V_r", "visibility_ratio", "vr"),
            "iou": _pick(e, "iou", "IoU", "iou_score"),
            "delta_x": _pick(e, "delta_x", "Delta_x", "Delta_x_px", "delta_x_px", "bleed_px", "bleed"),
            "screenshot_ref": _pick(e, "screenshot_ref", "screenshot", "screenshot_path", "artifact", "artifact_ref"),
            "valid": e.get("valid", e.get("metrics_valid")),
            "invalid_reason": e.get("invalid_reason") or e.get("error"),
        }
    return out


def evaluate_viewport(name: str, m: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    w, h = VIEWPORTS[name]
    base: Dict[str, Any] = {"viewport": name, "width": w, "height": h, "v_r": None,
                            "iou": None, "delta_x": None, "valid": False, "passed": False,
                            "failure_reasons": [], "screenshot_ref": None}
    if not m:
        base["failure_reasons"] = [f"{name}: missing viewport metrics"]
        return base
    base["screenshot_ref"] = m.get("screenshot_ref")
    if m.get("valid") is False:
        base["failure_reasons"] = [f"{name}: invalid metrics ({m.get('invalid_reason') or 'invalid'})"]
        return base
    vr, iou, dx = _finite(m.get("v_r")), _finite(m.get("iou")), _finite(m.get("delta_x"))
    base.update({"v_r": vr, "iou": iou, "delta_x": dx})
    if vr is None or iou is None or dx is None:
        missing = [k for k, v in (("V_r", vr), ("IoU", iou), ("Delta_x", dx)) if v is None]
        base["failure_reasons"] = [f"{name}: missing/non-finite metrics: {', '.join(missing)}"]
        return base
    base["valid"] = True
    reasons = []
    if not (vr >= VR_MIN):
        reasons.append(f"{name}: V_r {vr} < {VR_MIN}")
    if not (iou == IOU_REQUIRED):
        reasons.append(f"{name}: IoU {iou} != 0")
    if not (dx <= DELTA_X_MAX):
        reasons.append(f"{name}: Delta_x {dx}px > {DELTA_X_MAX}px")
    base["failure_reasons"] = reasons
    base["passed"] = not reasons
    return base


def evaluate_dual_viewport(metrics: Any) -> Dict[str, Any]:
    """Strict dual-viewport verdict. Returns viewports, passed, score, reasons."""
    norm = normalize_viewport_metrics(metrics)
    viewports = {name: evaluate_viewport(name, norm.get(name)) for name in ("mobile", "desktop")}
    reasons = [r for v in viewports.values() for r in v["failure_reasons"]]
    valid = all(v["valid"] for v in viewports.values())
    passed = valid and all(v["passed"] for v in viewports.values())
    return {"viewports": viewports, "passed": passed, "valid": valid,
            "score": compute_dual_viewport_score(viewports) if valid else None,
            "failure_reasons": reasons,
            "screenshot_refs": {n: v["screenshot_ref"] for n, v in viewports.items() if v["screenshot_ref"]}}


def compute_dual_viewport_score(viewports: Dict[str, Dict[str, Any]]) -> Optional[float]:
    """mean(V_r) - max(IoU) - 0.01*max(Delta_x); None if incomplete/invalid."""
    try:
        m, d = viewports["mobile"], viewports["desktop"]
    except Exception:
        return None
    vals = []
    for v in (m, d):
        if not v.get("valid"):
            return None
        vr, iou, dx = _finite(v.get("v_r")), _finite(v.get("iou")), _finite(v.get("delta_x"))
        if vr is None or iou is None or dx is None:
            return None
        vals.append((vr, iou, dx))
    return float((vals[0][0] + vals[1][0]) / 2 - max(v[1] for v in vals) - 0.01 * max(v[2] for v in vals))


def metrics_from_anomalies(anomalies: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Worst-case per-viewport metrics from remaining anomalies (legacy sense path)."""
    grouped: Dict[str, List[Any]] = {"mobile": [], "desktop": []}
    for a in anomalies or []:
        name = viewport_name(getattr(a, "viewport", None))
        if name:
            grouped[name].append(a)
        else:  # unlabelled legacy anomaly: applies to both viewports
            grouped["mobile"].append(a)
            grouped["desktop"].append(a)
    out: Dict[str, Dict[str, Any]] = {}
    for name, items in grouped.items():
        if not items:
            continue
        vrs = [_finite(getattr(a, "visibility_ratio", None)) for a in items]
        ious = [_finite(getattr(a, "iou_score", None)) for a in items]
        dxs = [_finite(getattr(a, "bleed_px", None)) for a in items]
        out[name] = {"viewport": name,
                     "v_r": min([v for v in vrs if v is not None], default=None),
                     "iou": max([v for v in ious if v is not None], default=0.0),
                     "delta_x": max([v for v in dxs if v is not None], default=0.0)}
    return out
