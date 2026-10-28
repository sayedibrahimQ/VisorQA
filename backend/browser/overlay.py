"""Visual collision/occlusion mask overlay artifacts.

For each *defective* viewport, composes a diagnostic PNG:

1. original viewport screenshot (dimensions unchanged),
2. crimson ``#F43F5E`` at exactly 35% opacity over defect-relevant SAM
   mask pixels (collision/occlusion regions supplied by the caller from
   existing defect results -- defect type is never inferred from a mask),
3. dashed cyan ``#00F0FF`` ``B_DOM`` outlines drawn *above* the masks.

Blending: ``out = rint(0.35 * crimson + 0.65 * original)`` per channel
(NumPy, vectorized); non-mask pixels are byte-identical to the source.
Masks use the vision_math convention: 2D, shape ``(height, width)``,
foreground ``> 0`` (bool, 0/1, 0/255, and float masks all supported).
Fractional ``B_DOM`` geometry is preserved until rasterization
(``floor``/``ceil`` half-open, clipped to image bounds, matching
``backend.core.vision_math.rasterize_box``).

Artifacts live under ``static/artifacts/{run_id}/`` and are served by the
FastAPI ``/static`` mount, so ``url`` is a public path while ``path`` is
the local filesystem location. Healthy viewports produce a ``skipped``
record and no file. Failures produce an ``error`` record; an artifact is
only reported ``generated`` after the written PNG is re-opened and its
dimensions verified. Segmentation is never rerun here.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CYAN = (0, 240, 255)        # #00F0FF
CRIMSON = (244, 63, 94)     # #F43F5E
CRIMSON_ALPHA = 0.35
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class OverlayError(ValueError):
    """Raised for mismatched/invalid overlay inputs."""


from backend.browser.schemas import DefectRegion, OverlayArtifact

__all__ = [
    "CYAN", "CRIMSON", "CRIMSON_ALPHA", "DefectRegion", "OverlayArtifact",
    "OverlayError", "validate_run_id", "default_artifact_root",
    "render_overlay_image", "generate_viewport_overlay",
    "generate_overlays_for_result",
]


def validate_run_id(run_id: str) -> str:
    if not run_id or not _RUN_ID_RE.match(str(run_id)):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return str(run_id)


def default_artifact_root() -> Path:
    from backend.config import settings

    raw = getattr(settings, "STATIC_ARTIFACTS_DIR", "static/artifacts")
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def _normalize_mask(mask: Any, shape: tuple) -> np.ndarray:
    arr = np.asarray(mask)
    if arr.ndim != 2:
        raise OverlayError(f"mask must be 2D, got shape {arr.shape}")
    if arr.shape != shape:
        raise OverlayError(
            f"mask shape {arr.shape} != screenshot shape {shape}; "
            "refusing to stretch mismatched masks")
    if arr.dtype == bool:
        return arr
    return arr > 0


def _draw_dashed_outline(draw: ImageDraw.ImageDraw, bounds, color,
                         thickness: int, dash_length: int, gap_length: int):
    x0, y0, x1, y1 = bounds  # inclusive pixel bounds, already clipped

    def dashes(start, end):
        pos = start
        while pos <= end:
            yield pos, min(pos + dash_length - 1, end)
            pos += dash_length + gap_length

    for t in range(thickness):
        xa, ya, xb, yb = x0 + t, y0 + t, x1 - t, y1 - t
        if xa > xb or ya > yb:
            break
        for s, e in dashes(xa, xb):
            draw.line([(s, ya), (e, ya)], fill=color)
            draw.line([(s, yb), (e, yb)], fill=color)
        for s, e in dashes(ya, yb):
            draw.line([(xa, s), (xa, e)], fill=color)
            draw.line([(xb, s), (xb, e)], fill=color)


def render_overlay_image(
    screenshot: Image.Image,
    regions: Sequence[DefectRegion],
    masks: Sequence[Any],
    dash_length: int = 8,
    gap_length: int = 5,
    thickness: int = 2,
    annotate_labels: bool = True,
) -> Image.Image:
    """Composite masks then dashed B_DOM outlines onto a copy (RGB)."""
    if len(regions) != len(masks):
        raise OverlayError("regions and masks must be parallel sequences")
    base = screenshot.convert("RGB")
    width, height = base.size
    arr = np.asarray(base).astype(np.float64)

    combined = np.zeros((height, width), dtype=bool)
    for mask in masks:
        if mask is not None:
            combined |= _normalize_mask(mask, (height, width))
    if combined.any():
        crimson = np.array(CRIMSON, dtype=np.float64)
        blended = np.rint(CRIMSON_ALPHA * crimson
                          + (1.0 - CRIMSON_ALPHA) * arr)
        arr = np.where(combined[..., None], blended, arr)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default() if annotate_labels else None
    for region in regions:
        if not region.box:
            continue
        b = region.box
        # Fractional geometry preserved until this rasterization step.
        x0 = max(0, math.floor(float(b["x"])))
        y0 = max(0, math.floor(float(b["y"])))
        x1 = min(width - 1, math.ceil(float(b["x"]) + float(b["width"])) - 1)
        y1 = min(height - 1, math.ceil(float(b["y"]) + float(b["height"])) - 1)
        if x1 < x0 or y1 < y0:
            continue  # fully outside image bounds
        _draw_dashed_outline(draw, (x0, y0, x1, y1), CYAN,
                             max(1, thickness), max(1, dash_length),
                             max(0, gap_length))
        if annotate_labels and region.element_id:
            label = str(region.element_id)
            # Only annotate when the label plausibly stays readable.
            if (x1 - x0) >= len(label) * 6 and y0 >= 10:
                draw.text((x0 + 2, y0 - 10), label, fill=CYAN, font=font)
    return out


def generate_viewport_overlay(
    run_id: str,
    viewport: str,
    screenshot_path: Optional[str],
    regions: Sequence[DefectRegion],
    masks: Sequence[Any],
    artifact_root: Optional[Path] = None,
    **render_kwargs: Any,
) -> OverlayArtifact:
    """Generate one viewport overlay; never raises for missing inputs."""
    run_id = validate_run_id(run_id)
    artifact = OverlayArtifact(
        run_id=run_id, viewport=viewport,
        defect_element_ids=[r.element_id for r in regions if r.element_id],
        defect_types=sorted({r.defect_type for r in regions
                             if r.defect_type}),
    )
    if not regions:
        return artifact  # healthy viewport: skipped, no file
    if not screenshot_path or not Path(screenshot_path).exists():
        artifact.status = "error"
        artifact.error = f"screenshot missing: {screenshot_path}"
        return artifact
    try:
        with Image.open(screenshot_path) as shot:
            shot.load()
            image = render_overlay_image(shot, regions, masks,
                                         **render_kwargs)
        root = Path(artifact_root) if artifact_root else default_artifact_root()
        run_dir = root / run_id
        # Defense in depth: resolved dir must stay inside the root.
        if run_dir.resolve().parent != root.resolve() and \
                root.resolve() not in run_dir.resolve().parents:
            raise OverlayError("artifact path escapes artifact root")
        run_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{viewport}_collision_overlay.png"
        out_path = run_dir / filename
        image.save(out_path, format="PNG")
        # Never report success for an artifact not actually written.
        with Image.open(out_path) as check:
            check.load()
            if check.format != "PNG" or check.size != image.size:
                raise OverlayError("written artifact failed verification")
            artifact.width, artifact.height = check.size
        artifact.status = "generated"
        artifact.path = str(out_path)
        artifact.url = f"/static/artifacts/{run_id}/{filename}"
        return artifact
    except Exception as exc:
        artifact.status = "error"
        artifact.error = f"{type(exc).__name__}: {exc}"[:300]
        artifact.path = artifact.url = None
        return artifact


def generate_overlays_for_result(
    result: Any,
    regions_by_viewport: Dict[str, Sequence[DefectRegion]],
    masks_by_viewport: Dict[str, Sequence[Any]],
    artifact_root: Optional[Path] = None,
    **render_kwargs: Any,
) -> Any:
    """Populate ``result.overlays`` from existing viewport screenshots.

    ``result`` is a ``DualViewportResult``; screenshots and geometry are
    reused, segmentation is not rerun. Viewports absent from
    ``regions_by_viewport`` are recorded as healthy/skipped.
    """
    overlays: List[OverlayArtifact] = []
    for vp in result.viewports:
        regions = regions_by_viewport.get(vp.name, [])
        masks = masks_by_viewport.get(vp.name, [])
        overlays.append(generate_viewport_overlay(
            result.run_id, vp.name, vp.screenshot_path, regions, masks,
            artifact_root=artifact_root, **render_kwargs))
    result.overlays = overlays
    return result
