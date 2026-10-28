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
from typing import List, Optional

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


class ViewportRenderResult(BaseModel):
    name: str  # "mobile" | "desktop"
    width: int
    height: int
    screenshot_path: Optional[str] = None
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    elements: List[ElementGeometry] = Field(default_factory=list)
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
