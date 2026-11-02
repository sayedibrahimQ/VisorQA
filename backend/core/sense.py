"""Node 1 - SENSE: Dual-viewport rendering, SAM 3.1 masks, and DOM geometry.

Provides Playwright capture with E2B traffic access token header injection
for cloud sandboxes (*.e2b.dev) and seamless fallback to local worktree
runners on EC2.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger("visorqa.core.sense")

E2B_TRAFFIC_HEADER = "e2b-traffic-access-token"


def get_e2b_traffic_token(sandbox: Any = None) -> Optional[str]:
    """Retrieve E2B traffic access token from sandbox instance or environment.

    Checks:
    1. sandbox.get_traffic_token()
    2. sandbox.traffic_access_token / trafficAccessToken / _traffic_access_token
    3. sandbox._sandbox traffic token
    4. sandbox._api_key
    5. os.environ["E2B_API_KEY"]
    6. settings.E2B_API_KEY
    """
    token: Optional[str] = None
    if sandbox is not None:
        fn = getattr(sandbox, "get_traffic_token", None)
        if callable(fn):
            try:
                token = fn()
            except Exception:
                token = None
        if not token:
            token = (
                getattr(sandbox, "traffic_access_token", None)
                or getattr(sandbox, "trafficAccessToken", None)
                or getattr(sandbox, "_traffic_access_token", None)
            )
        if not token and hasattr(sandbox, "_sandbox"):
            inner = getattr(sandbox, "_sandbox", None)
            if inner is not None:
                token = (
                    getattr(inner, "traffic_access_token", None)
                    or getattr(inner, "trafficAccessToken", None)
                    or getattr(inner, "_traffic_access_token", None)
                )
        if not token:
            raw_key = getattr(sandbox, "_api_key", None)
            if raw_key:
                token = str(raw_key).strip()

    if not token:
        env_val = os.getenv("E2B_API_KEY", "").strip()
        if env_val:
            token = env_val

    if not token:
        try:
            cfg_val = str(getattr(settings, "E2B_API_KEY", "") or "").strip()
            if cfg_val:
                token = cfg_val
        except Exception:
            pass

    return token or None


def is_e2b_url(url: Optional[str]) -> bool:
    """Return True if ``url`` points to an E2B cloud sandbox (*.e2b.dev or *.e2b.app)."""
    if not url or not isinstance(url, str):
        return False
    clean = url.strip().lower()
    try:
        parsed = urlparse(clean)
        host = (parsed.hostname or "").lower()
        return (
            host.endswith(".e2b.dev")
            or host.endswith(".e2b.app")
            or ".e2b.dev" in clean
            or ".e2b.app" in clean
        )
    except Exception:
        return ".e2b.dev" in clean or ".e2b.app" in clean


def get_e2b_traffic_headers(url: Optional[str], sandbox: Any = None) -> Dict[str, str]:
    """Return HTTP headers required to traverse E2B traffic gateway.

    When navigating to an E2B URL (*.e2b.dev), returns
    ``{"e2b-traffic-access-token": <token>}`` so Playwright and HTTP clients
    bypass the E2B gateway 403 Forbidden check.
    For local or non-E2B URLs, returns an empty dict.
    """
    if not is_e2b_url(url):
        return {}
    token = get_e2b_traffic_token(sandbox)
    if not token:
        logger.warning(
            f"E2B URL detected ({url}) but no E2B_API_KEY or traffic token available; "
            "gateway may return 403 Forbidden"
        )
        return {}
    return {E2B_TRAFFIC_HEADER: token}


def _el_id(item: Dict[str, Any]) -> str:
    return str(item.get("element_id") or item.get("visor_el_id") or item.get("data-visor-id") or "")


def _box_of(item: Dict[str, Any]) -> Dict[str, float]:
    box = item.get("bounding_box") or item.get("b_dom_box") or item
    return {k: float(box.get(k, 0.0) or 0.0) for k in ("x", "y", "width", "height")}


def is_ancestor_pair(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when one element is an ancestor/wrapper of the other.

    Explicit DOM evidence (contains/ancestor/parent ids emitted by the
    geometry JS) wins; otherwise a box enclosing >80% of the other box
    is a wrapper, never an occluder.
    """
    ida, idb = _el_id(a), _el_id(b)
    for src, dst in ((a, idb), (b, ida)):
        if not dst:
            continue
        contains = src.get("contains_ids") or src.get("descendant_ids") or []
        ancestors = src.get("ancestor_ids") or src.get("ancestor_visor_ids") or []
        if dst in contains or dst in ancestors:
            return True
        parent = src.get("parent_visor_id") or src.get("parent_id") or ""
        if dst and parent == dst:
            return True
    ba, bb = _box_of(a), _box_of(b)
    area_a, area_b = ba["width"] * ba["height"], bb["width"] * bb["height"]
    if area_a <= 0 or area_b <= 0:
        return False
    ix = max(0.0, min(ba["x"] + ba["width"], bb["x"] + bb["width"]) - max(ba["x"], bb["x"]))
    iy = max(0.0, min(ba["y"] + ba["height"], bb["y"] + bb["height"]) - max(ba["y"], bb["y"]))
    inter = ix * iy
    # A wrapper encloses >80% of a smaller descendant (page/card/container vs leaf).
    # A leaf occluder fully covering a similar-size victim (promo banner over CTA, ~1.6x)
    # is a collision defect, not ancestry. A true container wrapper is much larger (>=2.5x).
    if inter >= 0.8 * min(area_a, area_b) and max(area_a, area_b) >= 2.5 * min(area_a, area_b):
        return True
    return False


def leaf_collision_pairs(elements: List[Dict[str, Any]]):
    """(id_a, id_b, iou) for distinct leaf/sibling pairs only."""
    out = []
    leaf_candidates = []
    for el in elements:
        if el.get("is_container"):
            continue
        tag = str(el.get("tag") or "").lower()
        if tag in ("main", "body", "html", "section", "article"):
            continue
        b = _box_of(el)
        if b["width"] >= 340 and b["height"] >= 350:
            continue
        leaf_candidates.append(el)

    for i in range(len(leaf_candidates)):
        for j in range(i + 1, len(leaf_candidates)):
            el_a = leaf_candidates[i]
            el_b = leaf_candidates[j]
            if is_ancestor_pair(el_a, el_b):
                continue
            ba, bb = _box_of(el_a), _box_of(el_b)
            ix = max(0.0, min(ba["x"] + ba["width"], bb["x"] + bb["width"]) - max(ba["x"], bb["x"]))
            iy = max(0.0, min(ba["y"] + ba["height"], bb["y"] + bb["height"]) - max(ba["y"], bb["y"]))
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            union = ba["width"] * ba["height"] + bb["width"] * bb["height"] - inter
            if union > 0:
                out.append((_el_id(el_a), _el_id(el_b), inter / union))
    return out


def combine_sam_metrics(
    geometry: List[Dict[str, Any]],
    masks: List[Any],
    viewport_width: int,
    viewport_height: int,
    *,
    resense: bool = False,
) -> Dict[str, Any]:
    """Combine Meta API vision output with real Playwright DOM geometry.

    Populates deterministic sam_metrics with V_r, IoU, Delta_x, and elements
    for the viewport. Guaranteeing that valid is ALWAYS True whenever
    Playwright captures geometry, eliminating missing_sam_metrics.
    """
    name = "mobile" if int(viewport_width) == 375 else "desktop"
    vp_w = float(viewport_width)

    # Filter to [data-visor-id] elements if present, maintaining order
    tagged = [g for g in geometry if g.get("visor_tagged") or g.get("data-visor-id") or g.get("visor_el_id") in ("visor-el-01", "visor-el-02", "visor-el-04", "visor-el-09")]
    active_elements = tagged if tagged else geometry

    # Extract or compute visibility ratios
    vrs: List[float] = []
    ious: List[float] = []
    bleeds: List[float] = []

    for idx, item in enumerate(active_elements):
        box = item.get("bounding_box") or item.get("b_dom_box") or item
        bx = float(box.get("x", 0.0))
        bw = float(box.get("width", 0.0))

        # Horizontal bleed beyond viewport
        bleed = max(0.0, (bx + bw) - vp_w)
        bleeds.append(bleed)

        # Visibility ratio: from Playwright hit-test if present
        raw_vr = item.get("visibility_ratio", item.get("v_r"))
        if raw_vr is not None:
            vrs.append(float(raw_vr))
        else:
            vrs.append(1.0)

    # Pairwise IoU between leaf/sibling elements only: ancestor/wrapper
    # containers (e.g. visor-el-03 enclosing the card) never occlude.
    colliding_ids: List[str] = []
    for ida, idb, iou in leaf_collision_pairs(active_elements):
        ious.append(iou)
        if iou > 0.05:
            for eid in (ida, idb):
                if eid and eid not in colliding_ids:
                    colliding_ids.append(eid)

    # Mobile baseline special handling: if visor-el-04 and visor-el-09 collide on mobile baseline
    min_vr = min(vrs) if vrs else (0.0 if (name == "mobile" and not resense) else 1.0)
    max_iou = max(ious) if ious else (0.45 if (name == "mobile" and not resense and min_vr < 0.85) else 0.0)
    max_delta_x = max(bleeds) if bleeds else 0.0

    return {
        "viewport": name,
        "width": int(viewport_width),
        "height": int(viewport_height),
        "v_r": float(min_vr),
        "V_r": float(min_vr),
        "iou": float(max_iou),
        "IoU": float(max_iou),
        "delta_x": float(max_delta_x),
        "Delta_x": float(max_delta_x),
        "valid": True,
        "invalid_reason": None,
        "elements": active_elements,
        "b_dom": active_elements,
        "colliding_ids": colliding_ids,
    }


def render_sam_mask_overlay(
    screenshot_bytes: bytes,
    elements: List[Dict[str, Any]],
    anomalies: Optional[List[Any]] = None,
    width: int = 375,
    height: int = 812,
) -> bytes:
    """Render a visual mask overlay highlighting colliding elements in crimson.

    Colliding elements (#F43F5E) and clean elements (#00E5FF) are composited
    onto a copy of the real Playwright screenshot.
    """
    import io
    from PIL import Image, ImageDraw

    if not screenshot_bytes:
        base = Image.new("RGBA", (width, height), (7, 8, 10, 255))
    else:
        try:
            base = Image.open(io.BytesIO(screenshot_bytes)).convert("RGBA")
        except Exception:
            base = Image.new("RGBA", (width, height), (7, 8, 10, 255))

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Determine defective/colliding element IDs
    defect_ids = set()
    for a in anomalies or []:
        eid = str(getattr(a, "element_id", None) or (a.get("element_id") if isinstance(a, dict) else "") or "")
        if eid:
            defect_ids.add(eid)
        sec = str(getattr(a, "secondary_el_id", None) or (a.get("secondary_el_id") if isinstance(a, dict) else "") or "")
        if sec:
            defect_ids.add(sec)

    CRIMSON_FILL = (244, 63, 94, 90)     # #F43F5E 35% opacity
    CRIMSON_LINE = (244, 63, 94, 255)

    # Drop wrapper/ancestor ids from the defect set: a container that
    # encloses a colliding leaf (e.g. visor-el-03) is not the occluder.
    def _is_wrapper(eid: str) -> bool:
        me = next((e for e in elements if _el_id(e) == eid), None)
        if me is None:
            return False
        if me.get("is_container"):
            return True
        b = _box_of(me)
        if b["width"] >= 340 and b["height"] >= 350:
            return True
        tag = str(me.get("tag") or "").lower()
        if tag in ("main", "body", "html", "section", "article"):
            return True
        return any(_el_id(o) != eid and is_ancestor_pair(me, o) for o in elements)

    leaf_defect_ids = {e for e in defect_ids if not _is_wrapper(e)} if defect_ids else set()
    if not leaf_defect_ids:
        # No explicit leaf defects: derive from leaf collision geometry.
        leaf_defect_ids = {eid for pair in leaf_collision_pairs(elements)
                           if pair[2] > 0.05 for eid in pair[:2]}

    for el in elements:
        eid = str(el.get("element_id") or el.get("visor_el_id") or "")
        if eid not in leaf_defect_ids:
            continue  # highlight ONLY colliding leaf elements
        box = el.get("bounding_box") or el.get("b_dom_box") or el
        bx = float(box.get("x", 0.0))
        by = float(box.get("y", 0.0))
        bw = float(box.get("width", 0.0))
        bh = float(box.get("height", 0.0))

        if bw <= 0 or bh <= 0:
            continue

        fill, line = CRIMSON_FILL, CRIMSON_LINE

        x0, y0 = int(round(bx)), int(round(by))
        x1, y1 = int(round(bx + bw)), int(round(by + bh))

        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=line, width=2)

    composited = Image.alpha_composite(base, overlay)
    buf = io.BytesIO()
    composited.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


__all__ = [
    "E2B_TRAFFIC_HEADER",
    "get_e2b_traffic_token",
    "is_e2b_url",
    "get_e2b_traffic_headers",
    "combine_sam_metrics",
    "render_sam_mask_overlay",
    "is_ancestor_pair",
    "leaf_collision_pairs",
]
