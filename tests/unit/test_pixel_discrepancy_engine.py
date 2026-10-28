"""Deterministic tests for the NumPy pixel discrepancy engine.

Conventions under test: masks are (H, W) with row=y, col=x; B_DOM is
(x, y, width, height) CSS px, rasterized half-open and clipped.
"""
import numpy as np
import pytest

from backend.core.vision_math import (
    ElementMaskInput,
    calculate_iou,
    calculate_visibility_ratio,
    compute_viewport_health,
    evaluate_bleed,
    evaluate_iou_pair,
    evaluate_viewport,
    evaluate_visibility,
    rasterize_box,
    sibling_pairs_from_hierarchy,
)

VW, VH = 100, 80  # viewport width, height


def mask_with(n_rows_filled=0, shape=(VH, VW)):
    m = np.zeros(shape, dtype=np.uint8)
    if n_rows_filled:
        m[:n_rows_filled, :] = 1
    return m


# 1. Perfect alignment ---------------------------------------------------------
def test_vr_perfect_alignment():
    box = {"x": 10, "y": 10, "width": 20, "height": 10}
    sam = rasterize_box(box, VW, VH).astype(np.uint8)
    r = evaluate_visibility("el-1", sam, box, VW, VH, "mobile")
    assert r.valid and r.v_r == 1.0 and r.status == "pass"
    assert r.b_dom_area == 200 and r.intersection_area == 200


# 2. Just below / at / above 0.85 ----------------------------------------------
@pytest.mark.parametrize("covered,expected,status", [
    (169, 0.845, "defect"), (170, 0.85, "pass"), (171, 0.855, "pass"),
])
def test_vr_threshold_boundary(covered, expected, status):
    box = {"x": 0, "y": 0, "width": 20, "height": 10}  # 200 px
    sam = np.zeros((VH, VW), dtype=np.uint8)
    coords = np.argwhere(rasterize_box(box, VW, VH))
    for r, c in coords[:covered]:
        sam[r, c] = 1
    r = evaluate_visibility("el-1", sam, box, VW, VH)
    assert r.v_r == pytest.approx(expected) and r.status == status
    assert r.is_defect is (status == "defect")


# 3. Empty masks and zero-area boxes --------------------------------------------
def test_empty_mask_and_zero_area_box():
    box = {"x": 0, "y": 0, "width": 10, "height": 10}
    r = evaluate_visibility("el-1", np.zeros((VH, VW), np.uint8), box, VW, VH)
    assert r.valid and r.v_r == 0.0 and r.status == "defect"  # empty != pass

    zero = evaluate_visibility("el-2", np.ones((VH, VW), np.uint8),
                               {"x": 0, "y": 0, "width": 0, "height": 10},
                               VW, VH)
    assert not zero.valid and zero.invalid_reason == "zero_area_box"
    assert zero.v_r is None

    bleed = evaluate_bleed("el-2", {"x": 0, "y": 0, "width": 0, "height": 5}, VW)
    assert not bleed.valid and bleed.invalid_reason == "zero_area_box"


# 4. Identical, disjoint, partial sibling masks ----------------------------------
def test_iou_identical_disjoint_partial():
    a = mask_with(4)
    assert evaluate_iou_pair("a", "b", a, a.copy()).iou == 1.0
    assert evaluate_iou_pair("a", "b", a, a.copy()).status == "defect"

    disjoint = np.zeros((VH, VW), np.uint8)
    disjoint[10:14, :] = 1
    r = evaluate_iou_pair("a", "b", a, disjoint)
    assert r.iou == 0.0 and r.status == "pass"

    partial_b = np.zeros((VH, VW), np.uint8)
    partial_b[2:6, :] = 1  # overlap 2 rows, union 6 rows
    r = evaluate_iou_pair("a", "b", a, partial_b)
    assert r.iou == pytest.approx(200 / 600) and r.status == "defect"

    both_empty = evaluate_iou_pair(
        "a", "b", np.zeros((VH, VW), np.uint8), np.zeros((VH, VW), np.uint8))
    assert both_empty.valid and both_empty.iou == 0.0
    assert both_empty.status == "pass"  # empty union defined, not div-by-zero


# 5. IoU just below, equal to, above 0.05 -----------------------------------------
@pytest.mark.parametrize("overlap,expected,status", [
    (4, 0.04, "pass"), (5, 0.05, "pass"), (6, 0.06, "defect"),
])
def test_iou_threshold_boundary(overlap, expected, status):
    a = np.zeros((1, 100), np.uint8)
    a[0, :50] = 1
    b = np.zeros((1, 100), np.uint8)
    b[0, 50 - overlap:100] = 1  # union stays 100 for all cases
    r = evaluate_iou_pair("a", "b", a, b)
    assert r.iou == pytest.approx(expected) and r.status == status


# 6. Bleed: none, exactly 2, more than 2 -------------------------------------------
@pytest.mark.parametrize("x,w,delta,status", [
    (0, 375, 0.0, "pass"), (100, 277, 2.0, "pass"), (100, 278, 3.0, "defect"),
])
def test_bleed_threshold(x, w, delta, status):
    r = evaluate_bleed("el", {"x": x, "y": 0, "width": w, "height": 10}, 375)
    assert r.valid and r.delta_x == pytest.approx(delta)
    assert r.status == status


def test_bleed_float_precision_preserved():
    r = evaluate_bleed("el", {"x": 10.5, "y": 0, "width": 100.25,
                              "height": 10}, 100)
    assert r.delta_x == pytest.approx(10.75)


# 7. Negative coordinates and boxes beyond viewport ---------------------------------
def test_negative_coords_and_out_of_viewport():
    box = {"x": -20, "y": -10, "width": 50, "height": 40}
    r = evaluate_visibility("el", np.ones((VH, VW), np.uint8), box, VW, VH)
    assert r.valid and r.v_r == 1.0 and r.b_dom_area == 30 * 30  # clipped

    bleed = evaluate_bleed("el", box, VW)
    assert bleed.delta_x == 0.0 and bleed.status == "pass"  # right-side only
    assert bleed.delta_x_left == pytest.approx(20.0)  # separate metric

    outside = evaluate_visibility(
        "el", np.ones((VH, VW), np.uint8),
        {"x": 500, "y": 0, "width": 50, "height": 10}, VW, VH)
    assert not outside.valid
    assert outside.invalid_reason == "box_outside_viewport"


# 8. Mismatched shapes and invalid inputs --------------------------------------------
def test_mismatched_and_invalid_inputs():
    box = {"x": 0, "y": 0, "width": 10, "height": 10}
    r = evaluate_visibility("el", np.zeros((10, 10), np.uint8), box, VW, VH)
    assert not r.valid and r.invalid_reason == "mask_shape_mismatch"

    r = evaluate_visibility("el", None, box, VW, VH)
    assert not r.valid and r.invalid_reason == "missing_mask"

    r = evaluate_visibility("el", np.zeros((2, 2, 2), np.uint8), box, VW, VH)
    assert not r.valid and r.invalid_reason == "invalid_mask"

    for bad_box in ({"x": 0, "y": 0, "width": -5, "height": 10},
                    {"x": float("nan"), "y": 0, "width": 5, "height": 10},
                    None, {"x": 0}):
        r = evaluate_visibility("el", np.ones((VH, VW), np.uint8),
                                bad_box, VW, VH)
        assert not r.valid and r.invalid_reason in (
            "invalid_box", "zero_area_box")

    pair = evaluate_iou_pair("a", "b", np.zeros((4, 4), np.uint8),
                             np.zeros((5, 5), np.uint8))
    assert not pair.valid and pair.invalid_reason == "mask_shape_mismatch"

    with pytest.raises(ValueError):
        calculate_iou(np.zeros((4, 4), np.uint8), np.zeros((5, 5), np.uint8))
    with pytest.raises(ValueError):
        calculate_visibility_ratio(np.zeros((4, 4), np.uint8),
                                   np.zeros((5, 5), np.uint8))


# 9. Composite scores ------------------------------------------------------------------
def _eval(elements, pairs=()):
    masks = {e.element_id: e.mask for e in elements}
    return evaluate_viewport(elements, masks, pairs, "mobile", VW, VH)


def test_health_all_pass_mixed_all_defect_no_valid():
    good_box = {"x": 0, "y": 0, "width": 10, "height": 10}
    full = rasterize_box(good_box, VW, VH).astype(np.uint8)
    ev = _eval([ElementMaskInput("a", good_box, full),
                ElementMaskInput("b", {"x": 50, "y": 0, "width": 10,
                                       "height": 10},
                                 rasterize_box({"x": 50, "y": 0, "width": 10,
                                                "height": 10}, VW, VH)
                                 .astype(np.uint8))],
               pairs=[("a", "b")])
    assert ev.health.score == 1.0 and ev.health.status == "ok"
    # 2 visibility + 1 collision + 2 bleed = 5 valid checks
    assert ev.health.valid_checks == 5 and ev.health.defect_checks == 0

    mixed = _eval([ElementMaskInput("a", good_box,
                                    np.zeros((VH, VW), np.uint8)),
                   ElementMaskInput("b", good_box, full)])
    # a: V_r defect + bleed pass; b: both pass -> 3/4 passing
    assert mixed.health.score == pytest.approx(0.75)
    assert mixed.health.defect_checks == 1 and mixed.health.invalid_checks == 0

    all_bad = _eval([ElementMaskInput(
        "a", {"x": 90, "y": 0, "width": 50, "height": 10},
        np.zeros((VH, VW), np.uint8))])
    assert all_bad.health.score == 0.0  # V_r defect + bleed defect

    # Invalid box + missing mask: every visibility and bleed check invalid.
    no_valid = _eval([ElementMaskInput(
                          "a", {"x": 0, "y": 0, "width": -5, "height": 10},
                          None),
                      ElementMaskInput("b", {"x": 0, "y": 0, "width": 0,
                                             "height": 0}, None)])
    assert no_valid.health.score is None
    assert no_valid.health.status == "insufficient_data"
    assert no_valid.health.valid_checks == 0
    assert no_valid.health.invalid_checks > 0  # invalid never counts as pass

    empty = compute_viewport_health([], [], [])
    assert empty.score is None and empty.status == "insufficient_data"


# 10. Repeatability ----------------------------------------------------------------------
def test_repeatability_identical_inputs():
    box = {"x": 5, "y": 5, "width": 30, "height": 20}
    sam = rasterize_box(box, VW, VH).astype(np.uint8)
    sam[0:3, :] = 0
    els = [ElementMaskInput("a", box, sam),
           ElementMaskInput("b", box, sam.copy())]
    first = evaluate_viewport(els, sibling_pairs=[("a", "b")],
                              viewport="desktop", width=VW, height=VH)
    second = evaluate_viewport(els, sibling_pairs=[("a", "b")],
                               viewport="desktop", width=VW, height=VH)
    assert first.model_dump() == second.model_dump()
    import json
    assert json.dumps(first.model_dump(), sort_keys=True) == \
        json.dumps(second.model_dump(), sort_keys=True)
    assert 0.0 <= first.health.score <= 1.0


# Integration: browser geometry + hierarchy sibling pairs -------------------------------
def test_integration_with_browser_schemas():
    from backend.browser.schemas import (
        ElementGeometry, HierarchyRecord, NodeDescriptor)
    from backend.core.state import DOMBoundingBox

    box = DOMBoundingBox(x=0, y=0, width=20, height=10)
    els = [ElementGeometry(visor_el_id="el-a", B_DOM=box),
           ElementGeometry(visor_el_id="el-b",
                           B_DOM=DOMBoundingBox(x=30, y=0, width=20,
                                                height=10))]
    masks = {"el-a": rasterize_box(box, VW, VH).astype(np.uint8),
             "el-b": rasterize_box(els[1].b_dom, VW, VH).astype(np.uint8)}
    records = [HierarchyRecord(
        relationship="adjacent_sibling_pair", viewport="mobile",
        element_ids=["el-a", "el-b"],
        lca=NodeDescriptor(tag="div", id="wrap"))]
    pairs = sibling_pairs_from_hierarchy(records)
    assert pairs == [("el-a", "el-b")]
    ev = evaluate_viewport(els, masks, pairs, "mobile", VW, VH)
    assert ev.health.score == 1.0
    assert {v.element_id for v in ev.visibility} == {"el-a", "el-b"}

    missing_pair = evaluate_viewport(els, masks, [("el-a", "ghost")],
                                     "mobile", VW, VH)
    assert missing_pair.collisions[0].invalid_reason == "missing_element"
    assert missing_pair.health.invalid_checks == 1
