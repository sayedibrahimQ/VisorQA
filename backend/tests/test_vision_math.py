"""Deterministic Unit Tests: Vision Math Equations (Equations 1, 2, 3)

Runs in <1 second without external network or API calls.
"""
import numpy as np
import pytest

from backend.core.vision_math import (
    VR_THRESHOLD,
    IOU_THRESHOLD,
    BLEED_THRESHOLD_PX,
    calculate_visibility_ratio,
    calculate_iou,
    detect_bleed_overflow,
    evaluate_visibility,
    evaluate_iou_pair,
    evaluate_bleed,
)
from backend.core.state import DOMBoundingBox


def test_equation_1_occlusion_ratio():
    """Equation 1: Occlusion Detection.
    Synthetic binary mask M_SAM (45x100) vs B_DOM (100x100).
    Yields V_r = 0.45 < 0.85 and flags OCCLUSION defect.
    """
    # 1. Scalar legacy calculation
    dom_mask = np.ones((100, 100), dtype=np.uint8)
    sam_mask = np.zeros((100, 100), dtype=np.uint8)
    sam_mask[:45, :] = 1  # 45 rows of 100 columns = 4500 pixels

    vr = calculate_visibility_ratio(sam_mask, dom_mask)
    assert pytest.approx(vr, 0.001) == 0.45
    assert vr < VR_THRESHOLD, f"V_r ({vr}) should be strictly < threshold ({VR_THRESHOLD})"

    # 2. Structured evaluation
    box = DOMBoundingBox(x=0, y=0, width=100, height=100)
    full_mask = np.zeros((200, 200), dtype=np.uint8)
    full_mask[:45, :100] = 1

    res = evaluate_visibility("visor-el-occluded", full_mask, box, viewport_width=200, viewport_height=200)
    assert res.valid is True
    assert pytest.approx(res.v_r, 0.001) == 0.45
    assert res.is_defect is True
    assert res.status == "defect"


def test_equation_2_collision_iou():
    """Equation 2: Layout Collision via Intersection-over-Union (IoU).
    Two overlapping sibling masks with IoU > 0.05 flag COLLISION defect.
    """
    # Mask A: 100x100 at (0, 0) -> area 10,000
    # Mask B: 100x100 at (80, 0) -> overlaps by 20x100 = 2,000 px
    # Union: 10,000 + 10,000 - 2,000 = 18,000 px
    # IoU = 2,000 / 18,000 = 0.1111 > 0.05
    mask_a = np.zeros((150, 200), dtype=np.uint8)
    mask_b = np.zeros((150, 200), dtype=np.uint8)
    mask_a[:100, :100] = 1
    mask_b[:100, 80:180] = 1

    iou = calculate_iou(mask_a, mask_b)
    assert pytest.approx(iou, 0.01) == 0.11
    assert iou > IOU_THRESHOLD, f"IoU ({iou}) should exceed threshold ({IOU_THRESHOLD})"

    # Structured pair evaluation
    res = evaluate_iou_pair("el-a", "el-b", mask_a, mask_b, viewport="desktop")
    assert res.valid is True
    assert res.is_defect is True
    assert res.status == "defect"
    assert res.iou > IOU_THRESHOLD


def test_equation_3_viewport_bleed():
    """Equation 3: Viewport Bleed (Horizontal Overflow).
    X_max = 412px on 375px mobile viewport yields bleed_px = 37px > 2px,
    flagging BLEED defect.
    """
    viewport_width = 375
    # Element starts at x=0 with width=412 (X_max = 412px)
    box = DOMBoundingBox(x=0.0, y=10.0, width=412.0, height=50.0)

    res = evaluate_bleed("visor-el-bleeding", box, viewport_width=viewport_width)
    assert res.valid is True
    assert res.delta_x == 37.0  # 412 - 375 = 37px
    assert res.delta_x > BLEED_THRESHOLD_PX
    assert res.is_defect is True
    assert res.status == "defect"

    # Also test detect_bleed_overflow mask helper
    bleeding_mask = np.zeros((812, 412), dtype=np.uint8)
    assert detect_bleed_overflow(bleeding_mask, viewport_shape=(812, 375)) is True
