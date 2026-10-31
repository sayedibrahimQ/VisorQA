"""Deterministic seed runs for Mission Control (Workstream 1).

Populates the artifact registry with three canonical PR runs — complete
with real PNG screenshots (before/after), binary SAM masks, collision
overlays (rendered by ``backend.browser.overlay``), B_DOM boxes, LCA
triage metadata, RepairSpec JSON, and unified diffs — but only when the
registry is empty. Fully deterministic: fixed geometry and colors, no
randomness, no network, no credentials. Live runs persist through the
same registry via ``persist_run_telemetry``, so seeded and live data
share one schema.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List

import numpy as np
from PIL import Image, ImageDraw

from backend.core.artifacts import ArtifactStore, build_run_payload

REPO = "sayedibrahimQ/VisorQA"


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _screenshot(width: int, height: int, *, healed: bool, seed_tag: int) -> Image.Image:
    """Tiny deterministic storefront render (defect vs healed layout)."""
    img = Image.new("RGB", (width, height), (10, 10, 12))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 48], fill=(24, 24, 30))
    d.text((12, 18), f"storefront checkout · seed {seed_tag}", fill=(161, 161, 170))
    banner_h = 64 if not healed else 28
    d.rectangle([8, 56, width - 8, 56 + banner_h], fill=(190, 40, 70))
    d.text((16, 64), "PROMO BANNER", fill=(255, 255, 255))
    btn_y = 56 + banner_h + 24 if healed else 96
    d.rectangle([8, btn_y, width - 8, btn_y + 48], outline=(0, 240, 255), width=2)
    d.text((16, btn_y + 16), "CONFIRM & PAY", fill=(0, 240, 255))
    d.rectangle([8, btn_y + 64, width - 8, height - 16], outline=(45, 51, 64), width=1)
    return img


def _mask_array(width: int, height: int, box: Dict[str, float], visible_ratio: float) -> np.ndarray:
    """Binary SAM-style mask: the visible fraction of the element box."""
    mask = np.zeros((height, width), dtype=np.uint8)
    x0, y0 = int(box["x"]), int(box["y"])
    visible_w = max(1, int(box["width"] * visible_ratio))
    x1 = min(width, x0 + visible_w)
    y1 = min(height, y0 + int(box["height"]))
    mask[y0:y1, x0:x1] = 1
    return mask


def _mask_png(mask: np.ndarray) -> bytes:
    return _png_bytes(Image.fromarray((mask * 255).astype(np.uint8), mode="L"))


_MOBILE_BOX = {"x": 12.0, "y": 80.0, "width": 350.0, "height": 60.0}
_DESKTOP_BOX = {"x": 100.0, "y": 200.0, "width": 640.0, "height": 90.0}

_REPAIR_SPEC = {
    "root_cause": "Fixed promo banner overlaps the checkout button (position: fixed over flow content)",
    "affected_selectors": [".promo-banner", "#confirm-pay"],
    "target_file": "src/components/CheckoutPage.tsx",
    "css_strategy": "Change .promo-banner from position: fixed to position: sticky so it reserves flow space",
    "desktop_preservation_constraints": ["Keep 1440px banner height and typography unchanged"],
    "forbidden_hacks": ["!important", "z-index: 9999", "hiding defective content (display: none / visibility: hidden)"],
}

_DIFF = (
    "--- a/src/components/CheckoutPage.tsx\n"
    "+++ b/src/components/CheckoutPage.tsx\n"
    "@@ -14,3 +14,3 @@\n"
    "- <div className=\"fixed top-0 inset-x-0 z-50 promo-banner\">\n"
    "+ <div className=\"sticky top-0 inset-x-0 z-10 promo-banner\">\n"
    "   <span>Free Worldwide Shipping on Orders Over $50</span>\n"
    " </div>\n"
)

_TRIAGE_SPEC = {
    "lca_element_id": "visor-el-04",
    "lca_dom": {"tag": "form", "react_hint": "CheckoutForm", "data-visor-el-id": "visor-el-04"},
    "triage_summary": "LCA CheckoutForm is the lowest common ancestor of visor-el-04 and visor-el-09; redirected away from protected shared UI.",
    "triage_status": "resolved",
    "triage_confidence": 0.87,
    "triage_rejected_targets": [
        {"path": "src/components/ui/Button.tsx", "reason": "protected_shared_ui"},
    ],
    "hierarchy": [{
        "ancestor_chain": [
            {"tag": "html"}, {"tag": "body"}, {"tag": "main"},
            {"tag": "div", "react_hint": "CheckoutPage"},
            {"tag": "form", "react_hint": "CheckoutForm", "data-visor-el-id": "visor-el-04"},
        ],
    }],
    **_REPAIR_SPEC,
}


def _anomalies() -> List[Dict[str, Any]]:
    return [
        {"id": "seed-anom-04", "element_id": "visor-el-04", "defect_type": "OCCLUSION",
         "visibility_ratio": 0.62, "iou_score": 0.0, "bleed_px": 0.0,
         "bounding_box": dict(_MOBILE_BOX), "viewport": "375px", "attempt_num": 0,
         "status": "DETECTED"},
        {"id": "seed-anom-04d", "element_id": "visor-el-04", "defect_type": "OCCLUSION",
         "visibility_ratio": 0.91, "iou_score": 0.0, "bleed_px": 0.0,
         "bounding_box": dict(_DESKTOP_BOX), "viewport": "1440px", "attempt_num": 0,
         "status": "DETECTED"},
    ]


def _seed_one(store: ArtifactStore, *, run_id: str, pr_number: int, branch: str,
              status: str, attempts_raw: List[Dict[str, Any]], tag: int,
              resolved: bool) -> Dict[str, Any]:
    from backend.browser.overlay import render_overlay_image
    from backend.browser.schemas import DefectRegion

    entries: List[Dict[str, Any]] = []
    for viewport, (w, h), box, vr in (
        ("mobile", (375, 812), _MOBILE_BOX, 0.62),
        ("desktop", (1440, 900), _DESKTOP_BOX, 0.91),
    ):
        before = _screenshot(w, h, healed=False, seed_tag=tag)
        mask = _mask_array(w, h, box, vr)
        overlay = render_overlay_image(
            before,
            [DefectRegion(element_id="visor-el-04", defect_type="OCCLUSION", box=box)],
            [mask.astype(bool)],
        )
        saved = store.save_bytes(run_id, 0, viewport, "screenshot_before.png", _png_bytes(before))
        entries.append({**saved, "kind": "screenshot_before"})
        saved = store.save_bytes(run_id, 0, viewport, "sam_mask.png", _mask_png(mask))
        entries.append({**saved, "kind": "sam_mask"})
        saved = store.save_bytes(run_id, 0, viewport, "overlay.png", _png_bytes(overlay))
        entries.append({**saved, "kind": "overlay"})
        if attempts_raw:
            after = _screenshot(w, h, healed=resolved, seed_tag=tag)
            last = max(int(a.get("attempt_number", 1)) for a in attempts_raw)
            saved = store.save_bytes(run_id, last, viewport, "screenshot_after.png",
                                     _png_bytes(after))
            entries.append({**saved, "kind": "screenshot_after"})

    record: Dict[str, Any] = {
        "id": run_id, "pr_number": pr_number, "repo_name": REPO, "repo_full_name": REPO,
        "branch": branch, "commit_sha": f"seed{tag:04d}cafe",
        "status": status, "current_step": "5.VERIFY" if status != "RUNNING" else "4.PATCH",
        "max_attempts": 3,
        "target_files": ["src/components/CheckoutPage.tsx"],
        "repair_spec": dict(_TRIAGE_SPEC),
        "best_patch": _DIFF if resolved else None,
        "current_patch": None if resolved else _DIFF,
        "is_resolved": resolved,
        "verification_status": "verification_passed" if resolved else (
            "verification_failed" if status == "FAILED" else ""),
        "sandbox": {"backend": "local", "last_patch_phase": "hmr_observed" if attempts_raw else "none",
                    "last_hmr_status": "observed" if attempts_raw else "",
                    "server_state": "running",
                    "patch_timings": {"total_patch_to_hmr_ms": 812.0}},
        "github_publication_status": "review_comment_posted" if resolved else "not_attempted",
        "github_commit_pushed": resolved, "github_commit_sha": "healed123" if resolved else None,
        "github_review_comment_posted": resolved, "github_error": None,
        "anomalies": _anomalies(),
        "attempts_raw": attempts_raw,
        "artifacts": entries,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload = build_run_payload(record, record["anomalies"], attempts_raw, entries)
    record["attempts"] = payload["attempts"]
    for telemetry in payload["attempts"]:
        num = int(telemetry["attempt_number"])
        for viewport in ("mobile", "desktop"):
            store.save_json(run_id, num, viewport, "telemetry.json",
                            {"attempt_number": num, "viewport": viewport,
                             "viewport_summary": telemetry["viewport_summary"][viewport],
                             "verification_feedback": telemetry["verification_feedback"]})
    store.save_run_record(record)
    return record


def seed_canonical_runs(store: ArtifactStore | None = None) -> List[Dict[str, Any]]:
    """Create the three canonical runs (resolved / fallback / running)."""
    store = store or ArtifactStore()
    passed_metrics = {
        "mobile": {"v_r": 0.99, "iou": 0.0, "delta_x": 0.0, "valid": True, "passed": True},
        "desktop": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0, "valid": True, "passed": True},
    }
    failed_metrics = {
        "mobile": {"v_r": 0.62, "iou": 0.0, "delta_x": 0.0, "valid": True, "passed": False},
        "desktop": {"v_r": 0.91, "iou": 0.0, "delta_x": 0.0, "valid": True, "passed": False},
    }
    runs = [
        _seed_one(
            store, run_id="run-seed-101", pr_number=101, branch="fix/checkout-banner",
            status="RESOLVED", tag=101, resolved=True,
            attempts_raw=[{"attempt_number": 1, "repair_spec": dict(_REPAIR_SPEC),
                           "unified_diff": _DIFF, "passed": True,
                           "verification_status": "verification_passed",
                           "viewport_metrics": passed_metrics}],
        ),
        _seed_one(
            store, run_id="run-seed-102", pr_number=102, branch="fix/cart-drawer-overlap",
            status="FAILED", tag=102, resolved=False,
            attempts_raw=[
                {"attempt_number": n, "repair_spec": dict(_REPAIR_SPEC),
                 "unified_diff": _DIFF, "passed": False,
                 "verification_status": "verification_failed",
                 "viewport_metrics": failed_metrics}
                for n in (1, 2, 3)
            ],
        ),
        _seed_one(
            store, run_id="run-seed-103", pr_number=103, branch="feat/promo-grid",
            status="RUNNING", tag=103, resolved=False,
            attempts_raw=[{"attempt_number": 1, "repair_spec": dict(_REPAIR_SPEC),
                           "unified_diff": _DIFF, "passed": False,
                           "verification_status": "verification_failed",
                           "viewport_metrics": failed_metrics}],
        ),
    ]
    return runs


def seed_if_empty(store: ArtifactStore | None = None) -> int:
    """Seed canonical runs only when the registry holds no runs."""
    store = store or ArtifactStore()
    if store.list_run_records():
        return 0
    return len(seed_canonical_runs(store))
