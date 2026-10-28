"""Tests for visual collision mask overlay artifacts.

Deterministic synthetic images/masks only; no live SAM or network.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.browser.overlay import (
    CRIMSON,
    CYAN,
    DefectRegion,
    OverlayError,
    generate_overlays_for_result,
    generate_viewport_overlay,
    render_overlay_image,
    validate_run_id,
)
from backend.browser.schemas import DualViewportResult, ViewportRenderResult

BASE = (100, 100, 100)


def make_shot(path: Path, size=(100, 80), color=BASE) -> Path:
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def region(eid="visor-el-01", box=None, dtype="OCCLUSION"):
    return DefectRegion(element_id=eid, defect_type=dtype,
                        box=box or {"x": 10, "y": 10, "width": 40,
                                    "height": 30})


def bool_mask(shape=(80, 100), fill=slice(15, 25)):
    m = np.zeros(shape, dtype=bool)
    m[fill, 15:25] = True
    return m


def render(size=(100, 80), masks=None, regions=None, **kw):
    kw.setdefault("annotate_labels", False)
    shot = Image.new("RGB", size, BASE)
    return render_overlay_image(shot, regions or [region()],
                                masks if masks is not None else [bool_mask()],
                                **kw)


# 1. Exact cyan on dashed outline ------------------------------------------------
def test_cyan_dashed_outline_pixels():
    out = render(thickness=1, dash_length=6, gap_length=4)
    px = out.load()
    assert px[10, 10] == CYAN and px[15, 10] == CYAN  # first dash (top edge)
    assert px[16, 10] == BASE and px[19, 10] == BASE  # gap unchanged
    assert px[20, 10] == CYAN  # second dash


# 2. Crimson blending at exactly 35% ------------------------------------------------
def test_crimson_alpha_blending_known_pixel():
    out = render()
    expected = tuple(
        int(round(0.35 * c + 0.65 * b)) for c, b in zip(CRIMSON, BASE))
    assert expected == (150, 87, 98)
    assert out.load()[20, 20] == expected


# 3. Unchanged pixels outside overlays -------------------------------------------------
def test_pixels_outside_overlays_unchanged():
    out = render()
    assert out.load()[90, 70] == BASE
    assert out.load()[0, 0] == BASE


# 4. Compositing order: boxes above masks -----------------------------------------------
def test_compositing_order_box_above_mask():
    # Mask covers the box's top edge; outline pixel must be cyan, not blend.
    m = np.zeros((80, 100), dtype=bool)
    m[10, 10:50] = True
    out = render(masks=[m], thickness=1)
    assert out.load()[12, 10] == CYAN


# 5. Mobile and desktop dimensions ---------------------------------------------------------
@pytest.mark.parametrize("name,size", [("mobile", (375, 812)),
                                       ("desktop", (1440, 900))])
def test_viewport_dimensions(tmp_path, name, size):
    shot = make_shot(tmp_path / f"{name}.png", size=size)
    mask = np.zeros((size[1], size[0]), dtype=bool)
    mask[10:20, 10:20] = True
    art = generate_viewport_overlay(
        "run123", name, str(shot), [region()], [mask],
        artifact_root=tmp_path / "static" / "artifacts",
        annotate_labels=False)
    assert art.status == "generated"
    assert (art.width, art.height) == size
    with Image.open(art.path) as img:
        assert img.size == size and img.format == "PNG"
    assert art.url == f"/static/artifacts/run123/{name}_collision_overlay.png"


# 6. Boolean and supported mask formats -------------------------------------------------------
@pytest.mark.parametrize("make", [
    lambda m: m,
    lambda m: m.astype(np.uint8),
    lambda m: (m * 255).astype(np.uint8),
    lambda m: m.astype(np.float64),
])
def test_mask_formats_equivalent(make):
    m = bool_mask()
    out = render(masks=[make(m)])
    expected = tuple(int(round(0.35 * c + 0.65 * b))
                     for c, b in zip(CRIMSON, BASE))
    assert out.load()[20, 20] == expected


# 7. Empty masks and missing geometry ------------------------------------------------------------
def test_empty_masks_and_missing_geometry(tmp_path):
    shot = make_shot(tmp_path / "s.png")
    empty = np.zeros((80, 100), dtype=bool)
    art = generate_viewport_overlay(
        "run1", "mobile", str(shot), [region()], [empty],
        artifact_root=tmp_path / "a", annotate_labels=False)
    assert art.status == "generated"  # box still drawn, no crash

    healthy = generate_viewport_overlay(
        "run1", "mobile", str(shot), [], [], artifact_root=tmp_path / "a")
    assert healthy.status == "skipped" and healthy.path is None

    missing = generate_viewport_overlay(
        "run1", "mobile", str(tmp_path / "nope.png"), [region()], [empty],
        artifact_root=tmp_path / "a")
    assert missing.status == "error" and missing.path is None
    assert missing.url is None  # never report an unwritten artifact


def test_healthy_viewport_writes_no_file(tmp_path):
    shot = make_shot(tmp_path / "s.png")
    art = generate_viewport_overlay(
        "healthy1", "desktop", str(shot), [], [],
        artifact_root=tmp_path / "a")
    assert art.status == "skipped"
    assert not (tmp_path / "a" / "healthy1").exists()


# 8. Mismatched dimensions ----------------------------------------------------------------------------
def test_mismatched_mask_dimensions(tmp_path):
    shot = make_shot(tmp_path / "s.png")  # 100x80
    bad = np.zeros((10, 10), dtype=bool)
    with pytest.raises(OverlayError):
        render_overlay_image(Image.open(shot), [region()], [bad],
                             annotate_labels=False)
    art = generate_viewport_overlay(
        "run1", "mobile", str(shot), [region()], [bad],
        artifact_root=tmp_path / "a")
    assert art.status == "error" and "refusing to stretch" in art.error
    assert art.path is None


# 9. Clipping at image boundaries ---------------------------------------------------------------------------
def test_box_clipping_at_boundaries():
    out = render(regions=[region(box={"x": -10.5, "y": -5.2, "width": 30,
                                      "height": 20})],
                 masks=[np.zeros((80, 100), bool)], thickness=1)
    assert out.size == (100, 80)
    assert out.load()[0, 0] == CYAN  # clipped corner outline at the edge
    out2 = render(regions=[region(box={"x": 500, "y": 500, "width": 30,
                                       "height": 20})],
                  masks=[np.zeros((80, 100), bool)])
    assert out2.load()[50, 40] == BASE  # fully outside: no drawing, no crash


# 10. Invalid run IDs / path traversal ------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "..", "../evil", "a/b", "a\\b",
                                 "a b", ".hidden", "x" * 65])
def test_invalid_run_ids_rejected(bad):
    with pytest.raises(ValueError):
        validate_run_id(bad)
    with pytest.raises(ValueError):
        generate_viewport_overlay(bad, "mobile", None, [region()], [])


def test_valid_run_ids_accepted():
    assert validate_run_id("abc-123_X") == "abc-123_X"


# 11. Concurrent isolation and naming --------------------------------------------------------------------------------------
def test_concurrent_run_isolation(tmp_path):
    shot = make_shot(tmp_path / "s.png")
    mask = bool_mask()

    def gen(run_id):
        return generate_viewport_overlay(
            run_id, "mobile", str(shot), [region()], [mask],
            artifact_root=tmp_path / "a", annotate_labels=False)

    with ThreadPoolExecutor(max_workers=4) as pool:
        arts = list(pool.map(gen, [f"run-{i}" for i in range(4)]))
    paths = {a.path for a in arts}
    assert len(paths) == 4 and all(a.status == "generated" for a in arts)
    assert all(Path(p).exists() for p in paths)
    assert all(Path(p).name == "mobile_collision_overlay.png" for p in paths)


# 12. PNG validity + integration with existing result schema ---------------------------------------------------------------
def test_integration_with_dual_viewport_result(tmp_path):
    shot = make_shot(tmp_path / "mobile.png", size=(375, 812))
    result = DualViewportResult(
        run_id="runXYZ", preview_url="http://127.0.0.1/x",
        output_dir=str(tmp_path),
        viewports=[ViewportRenderResult(
            name="mobile", width=375, height=812,
            screenshot_path=str(shot)),
            ViewportRenderResult(name="desktop", width=1440, height=900)],
    )
    mask = np.zeros((812, 375), dtype=bool)
    mask[15:25, 15:25] = True
    out = generate_overlays_for_result(
        result, {"mobile": [region(dtype="COLLISION")]}, {"mobile": [mask]},
        artifact_root=tmp_path / "static" / "artifacts",
        annotate_labels=False)
    assert out is result and len(result.overlays) == 2
    mobile, desktop = result.overlays
    assert mobile.status == "generated"
    assert mobile.url == "/static/artifacts/runXYZ/mobile_collision_overlay.png"
    assert mobile.defect_types == ["COLLISION"]
    assert desktop.status == "skipped"  # healthy viewport: no overlay
    dumped = result.model_dump()
    assert dumped["overlays"][0]["artifact_type"] == "collision_overlay"
    with Image.open(mobile.path) as img:
        assert img.format == "PNG" and img.mode == "RGB"
        img.load()  # passes to multimodal consumers without conversion


def test_static_url_served_by_app(tmp_path):
    # Artifact written under the repo static root is reachable at /static/...
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.browser.overlay import default_artifact_root

    shot = make_shot(tmp_path / "s.png")
    art = generate_viewport_overlay(
        "httprun1", "mobile", str(shot), [region()], [bool_mask()],
        annotate_labels=False)  # default root == served static/artifacts
    assert art.status == "generated"
    assert Path(art.path) == default_artifact_root() / "httprun1" / \
        "mobile_collision_overlay.png"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(art.url)
            assert resp.status_code == 200
            assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        import shutil
        shutil.rmtree(Path(art.path).parent, ignore_errors=True)
