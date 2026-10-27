import numpy as np
from backend.core.vision_math import (
    calculate_visibility_ratio,
    calculate_iou,
    detect_bleed_overflow,
)

def test_visibility_ratio_perfect_fit():
    # DOM box 10x10, SAM mask 10x10 -> V_r = 1.0
    dom_mask = np.ones((10, 10), dtype=np.uint8)
    sam_mask = np.ones((10, 10), dtype=np.uint8)
    vr = calculate_visibility_ratio(sam_mask, dom_mask)
    assert vr == 1.0

def test_visibility_ratio_occlusion():
    # DOM box 10x10 (100 px), SAM mask only covers 60 px -> V_r = 0.60 < 0.85 (occlusion)
    dom_mask = np.ones((10, 10), dtype=np.uint8)
    sam_mask = np.zeros((10, 10), dtype=np.uint8)
    sam_mask[0:6, :] = 1
    vr = calculate_visibility_ratio(sam_mask, dom_mask)
    assert vr == 0.60
    assert vr < 0.85

def test_visibility_ratio_empty_dom():
    dom_mask = np.zeros((10, 10), dtype=np.uint8)
    sam_mask = np.ones((10, 10), dtype=np.uint8)
    assert calculate_visibility_ratio(sam_mask, dom_mask) == 1.0

def test_iou_collision():
    # Mask A: [0:10, 0:10] (100 px)
    # Mask B: [5:15, 0:10] (100 px)
    # Intersection: [5:10, 0:10] (50 px)
    # Union: [0:15, 0:10] (150 px) -> IoU = 50 / 150 = 0.3333 > 0.05 (Collision)
    mask_a = np.zeros((20, 20), dtype=np.uint8)
    mask_a[0:10, 0:10] = 1
    mask_b = np.zeros((20, 20), dtype=np.uint8)
    mask_b[5:15, 0:10] = 1

    iou = calculate_iou(mask_a, mask_b)
    assert round(iou, 2) == 0.33
    assert iou > 0.05

def test_iou_no_overlap():
    mask_a = np.zeros((20, 20), dtype=np.uint8)
    mask_a[0:5, 0:5] = 1
    mask_b = np.zeros((20, 20), dtype=np.uint8)
    mask_b[10:15, 10:15] = 1
    assert calculate_iou(mask_a, mask_b) == 0.0

def test_detect_bleed_overflow():
    viewport = (812, 375)  # Height, Width
    normal_mask = np.zeros((800, 370), dtype=np.uint8)
    bleeding_mask = np.zeros((800, 400), dtype=np.uint8)

    assert detect_bleed_overflow(normal_mask, viewport) is False
    assert detect_bleed_overflow(bleeding_mask, viewport) is True
