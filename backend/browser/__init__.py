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
from backend.browser.schemas import (
    ComputedCSSSignature,
    ElementGeometry,
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
]
