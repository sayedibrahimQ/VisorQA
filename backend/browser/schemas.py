"""Pydantic schemas for dual-viewport DOM geometry extraction.

Coordinate semantics
--------------------
``B_DOM`` values come from ``Element.getBoundingClientRect()`` inside the
page. They are viewport-relative CSS pixels (origin at the top-left of the
visible viewport, scroll offset already applied by the browser). They are
*not* document-relative and *not* device pixels: with
``device_scale_factor=1`` one CSS pixel maps to one screenshot pixel, so
``B_DOM`` boxes overlay directly onto ``mobile.png`` / ``desktop.png``.
Floating-point precision from ``getBoundingClientRect()`` is preserved.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.core.state import DOMBoundingBox


class ElementCategory(str, Enum):
    MODAL_DIALOG = "modal_dialog"
    MENU_POPOVER = "menu_popover"
    STICKY_FIXED = "sticky_fixed"
    NAVIGATION = "navigation"
    BUTTON = "button"
    LINK = "link"
    FORM_INPUT = "form_input"
    CARD = "card"


class ElementStatus(str, Enum):
    OK = "ok"
    PARTIALLY_OFF_VIEWPORT = "partially_off_viewport"
    OFF_VIEWPORT = "off_viewport"
    HIDDEN = "hidden"
    ZERO_SIZE = "zero_size"
    DETACHED = "detached"


class ElementGeometry(BaseModel):
    """One identified element linked to its ``data-visor-el-id``."""

    model_config = ConfigDict(populate_by_name=True)

    visor_el_id: str = Field(validation_alias="visor_el_id", serialization_alias="visor_el_id")
    category: str = ""
    tag: str = ""
    label: str = ""
    # B_DOM kept under its SRS spelling in JSON output.
    b_dom: Optional[DOMBoundingBox] = Field(
        default=None, validation_alias="B_DOM", serialization_alias="B_DOM"
    )
    c_x: Optional[float] = None
    c_y: Optional[float] = None
    viewport: str = ""
    status: ElementStatus = ElementStatus.OK
    in_viewport: bool = False
    partially_visible: bool = False


class ComputedCSSSignature(BaseModel):
    """Computed layout signature from ``getComputedStyle()`` (strings)."""

    model_config = ConfigDict(populate_by_name=True)

    position: str = ""
    z_index: str = Field(default="", validation_alias="z-index", serialization_alias="z-index")
    display: str = ""
    flex_direction: str = Field(default="", validation_alias="flex-direction", serialization_alias="flex-direction")
    flex_wrap: str = Field(default="", validation_alias="flex-wrap", serialization_alias="flex-wrap")
    overflow: str = ""
    overflow_x: str = Field(default="", validation_alias="overflow-x", serialization_alias="overflow-x")
    overflow_y: str = Field(default="", validation_alias="overflow-y", serialization_alias="overflow-y")
    width: str = ""
    max_width: str = Field(default="", validation_alias="max-width", serialization_alias="max-width")


class NodeDescriptor(BaseModel):
    """Bounded, serializable descriptor for an element or LCA container."""

    model_config = ConfigDict(populate_by_name=True)

    tag: str = ""
    element_id: str = Field(default="", validation_alias="id", serialization_alias="id")
    classes: List[str] = Field(default_factory=list)
    visor_el_id: Optional[str] = Field(
        default=None, validation_alias="data-visor-el-id",
        serialization_alias="data-visor-el-id")
    role: Optional[str] = None
    aria_label: Optional[str] = Field(
        default=None, validation_alias="aria-label", serialization_alias="aria-label")
    data_testid: Optional[str] = Field(
        default=None, validation_alias="data-testid", serialization_alias="data-testid")
    text_hint: str = ""
    react_hint: Optional[str] = None
    # "explicit_marker" | "heuristic" | None
    react_hint_source: Optional[str] = None


class RelationshipType(str, Enum):
    ELEMENT_ANCESTRY = "element_ancestry"
    ADJACENT_SIBLING_PAIR = "adjacent_sibling_pair"
    SELECTED_PAIR = "selected_pair"


class HierarchyRecord(BaseModel):
    """LCA / ancestry record linked to geometry via ``data-visor-el-id``."""

    model_config = ConfigDict(populate_by_name=True)

    relationship: str = RelationshipType.ELEMENT_ANCESTRY.value
    viewport: str = ""
    element_ids: List[str] = Field(default_factory=list)
    element: Optional[NodeDescriptor] = None
    sibling: Optional[NodeDescriptor] = None
    ancestor_chain: List[NodeDescriptor] = Field(default_factory=list)
    chain_truncated: bool = False
    lca: Optional[NodeDescriptor] = None
    lca_found: bool = False
    # found | identical | detached | not_found | no_common_ancestor | missing_id
    lca_status: str = "not_found"
    lca_css_signature: Optional[ComputedCSSSignature] = None
    element_css_signatures: Dict[str, ComputedCSSSignature] = Field(default_factory=dict)
    notes: Optional[str] = None


class ViewportRenderResult(BaseModel):
    name: str  # "mobile" | "desktop"
    width: int
    height: int
    screenshot_path: Optional[str] = None
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    elements: List[ElementGeometry] = Field(default_factory=list)
    hierarchy: List[HierarchyRecord] = Field(default_factory=list)
    element_count: int = 0
    target_range_met: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class DualViewportResult(BaseModel):
    run_id: str
    preview_url: str  # sanitized (no credentials / query secrets)
    output_dir: str
    geometry_path: Optional[str] = None
    viewports: List[ViewportRenderResult] = Field(default_factory=list)
    success: bool = False
    errors: List[str] = Field(default_factory=list)

    def viewport(self, name: str) -> Optional[ViewportRenderResult]:
        for v in self.viewports:
            if v.name == name:
                return v
        return None
