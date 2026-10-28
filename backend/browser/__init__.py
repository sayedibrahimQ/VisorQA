"""VisorQA browser rendering package (SENSE node support)."""
from backend.browser.renderer import (
    PlaywrightDualViewportRenderer,
    extract_hierarchy,
    render_dual_viewport,
    validate_preview_url,
    compute_center,
    png_dimensions,
    VIEWPORTS,
    MIN_TARGET_ELEMENTS,
    MAX_ELEMENTS,
)
from backend.browser.overlay import (
    generate_overlays_for_result,
    generate_viewport_overlay,
    render_overlay_image,
)
from backend.browser.schemas import (
    ComputedCSSSignature,
    DefectRegion,
    ElementGeometry,
    OverlayArtifact,
    HierarchyRecord,
    NodeDescriptor,
    RelationshipType,
    ViewportRenderResult,
    DualViewportResult,
    ElementCategory,
)

__all__ = [
    "PlaywrightDualViewportRenderer",
    "render_dual_viewport",
    "validate_preview_url",
    "compute_center",
    "png_dimensions",
    "VIEWPORTS",
    "MIN_TARGET_ELEMENTS",
    "MAX_ELEMENTS",
    "ElementGeometry",
    "ViewportRenderResult",
    "DualViewportResult",
    "ElementCategory",
    "ComputedCSSSignature",
    "HierarchyRecord",
    "NodeDescriptor",
    "RelationshipType",
    "extract_hierarchy",
    "DefectRegion",
    "OverlayArtifact",
    "render_overlay_image",
    "generate_viewport_overlay",
    "generate_overlays_for_result",
]
