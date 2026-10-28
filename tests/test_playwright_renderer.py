"""Tests for PlaywrightDualViewportRenderer (dual-viewport SENSE extraction).

Uses a local fixture server only; no external network.
"""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.browser.renderer import (
    MAX_ELEMENTS,
    MIN_TARGET_ELEMENTS,
    PlaywrightDualViewportRenderer,
    _EXTRACT_JS,
    _INJECT_JS,
    _build_geometry,
    compute_center,
    png_dimensions,
    validate_preview_url,
)
from backend.core.state import DOMBoundingBox

FIXTURES = Path(__file__).parent / "fixtures"
RICH = (FIXTURES / "rich_page.html").read_text(encoding="utf-8")
SPARSE = "<html><body><button>One</button><button>Two</button>" \
         "<a href='/x'>Link</a></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        if self.path == "/slow":
            time.sleep(5)
            body = RICH.encode()
        elif self.path == "/sparse":
            body = SPARSE.encode()
        else:
            body = RICH.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def rendered(server_url, tmp_path_factory):
    out = tmp_path_factory.mktemp("artifacts")
    result = asyncio.run(
        PlaywrightDualViewportRenderer(
            navigation_timeout_ms=15000, stabilization_ms=50
        ).render_all(f"{server_url}/rich", out)
    )
    return result


# --- pure helpers -----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "", "not-a-url", "ftp://example.com/x", "javascript:alert(1)",
    "file:///etc/passwd", "http://", "https://user:secret@example.com/x",
])
def test_validate_preview_url_rejects(bad):
    with pytest.raises(ValueError):
        validate_preview_url(bad)


def test_validate_preview_url_accepts():
    assert validate_preview_url("http://127.0.0.1:8000/p") == \
        "http://127.0.0.1:8000/p"
    assert validate_preview_url("https://preview.example.com/pr") \
        .startswith("https://")


def test_compute_center():
    cx, cy = compute_center(DOMBoundingBox(x=10.5, y=20.0, width=101.0, height=51.0))
    assert cx == pytest.approx(61.0) and cy == pytest.approx(45.5)


def test_png_dimensions_rejects_non_png():
    with pytest.raises(ValueError):
        png_dimensions(b"not a png at all........")


def test_build_geometry_detached_and_center():
    injected = [{"visor_el_id": "visor-el-01", "category": "button",
                 "tag": "button", "label": "Hi"},
                {"visor_el_id": "visor-el-02", "category": "button",
                 "tag": "button", "label": "Gone"}]
    raw = [{"visor_el_id": "visor-el-01", "status": "ok",
            "B_DOM": {"x": 0.0, "y": 0.0, "width": 100.0, "height": 40.0},
            "in_viewport": True, "partially_visible": False},
           {"visor_el_id": "visor-el-02", "status": "detached", "B_DOM": None}]
    els = _build_geometry(injected, raw, "mobile")
    assert els[0].c_x == 50.0 and els[0].c_y == 20.0
    assert els[1].status.value == "detached" and els[1].b_dom is None
    assert els[1].c_x is None


# --- rendered run -------------------------------------------------------------

def test_both_viewports_succeed(rendered):
    assert rendered.success is True, rendered.errors
    assert {v.name for v in rendered.viewports} == {"mobile", "desktop"}


def test_exact_png_dimensions(rendered, tmp_path):
    for name, (w, h) in {"mobile": (375, 812), "desktop": (1440, 900)}.items():
        vp = rendered.viewport(name)
        shot = Path(vp.screenshot_path)
        assert shot.name == f"{name}.png" and shot.exists()
        assert png_dimensions(shot.read_bytes()) == (w, h)
        assert (vp.screenshot_width, vp.screenshot_height) == (w, h)
        assert (vp.width, vp.height) == (w, h)


def test_unique_ids_and_geometry_linkage(rendered):
    for vp in rendered.viewports:
        ids = [e.visor_el_id for e in vp.elements]
        assert len(ids) == len(set(ids)), "IDs must be unique"
        assert ids.count("visor-el-01") == 1  # collision safely handled
        assert vp.element_count == len(vp.elements)
        for e in vp.elements:
            assert e.viewport == vp.name
            if e.b_dom is not None and e.status.value != "detached":
                assert e.c_x == pytest.approx(e.b_dom.x + e.b_dom.width / 2)
                assert e.c_y == pytest.approx(e.b_dom.y + e.b_dom.height / 2)


def test_element_count_target_range(rendered):
    for vp in rendered.viewports:
        assert MIN_TARGET_ELEMENTS <= vp.element_count <= MAX_ELEMENTS
        assert vp.target_range_met is True


def test_all_categories_present(rendered):
    cats = {e.category for e in rendered.viewport("desktop").elements}
    assert {"button", "link", "form_input", "card", "navigation",
            "sticky_fixed", "modal_dialog", "menu_popover"} <= cats
    for vp in rendered.viewports:
        for e in vp.elements:
            assert e.tag and e.category


def test_hidden_zero_offscreen_excluded_partial_flagged(rendered):
    for vp in rendered.viewports:
        labels = " ".join(e.label for e in vp.elements)
        assert "HiddenButton" not in labels
        assert "ZeroButton" not in labels
        assert "OffscreenButton" not in labels
        partial = [e for e in vp.elements if e.label == "PartialBtn"]
        assert partial and partial[0].status.value == \
            "partially_off_viewport"
        assert partial[0].partially_visible is True


def test_responsive_dom_changes(rendered):
    mobile_labels = {e.label for e in rendered.viewport("mobile").elements}
    desktop_labels = {e.label for e in rendered.viewport("desktop").elements}
    assert "Mobile menu" in mobile_labels
    assert "Mobile menu" not in desktop_labels
    assert "DesktopHelp" in desktop_labels
    assert "DesktopHelp" not in mobile_labels


def test_json_artifact_valid(rendered):
    data = json.loads(Path(rendered.geometry_path).read_text())
    assert data["success"] is True
    assert data["run_id"] == rendered.run_id
    for vp in data["viewports"]:
        assert vp["elements"], vp["name"]
        first = vp["elements"][0]
        assert "B_DOM" in first and "c_x" in first and "visor_el_id" in first


# --- sparse / failure paths ---------------------------------------------------

async def test_fewer_than_25_reports_actual(server_url, tmp_path):
    r = PlaywrightDualViewportRenderer(stabilization_ms=0)
    result = await r.render_all(f"{server_url}/sparse", tmp_path)
    assert result.success is True  # rendering worked; count is reported
    for vp in result.viewports:
        assert vp.element_count == 3
        assert vp.target_range_met is False


async def test_navigation_timeout_is_partial_failure(server_url, tmp_path):
    r = PlaywrightDualViewportRenderer(
        navigation_timeout_ms=600, stabilization_ms=0,
        network_idle_timeout_ms=200)
    result = await r.render_all(f"{server_url}/slow", tmp_path)
    assert result.success is False  # never report success on failed viewport
    assert result.errors
    assert all(v.error for v in result.viewports)
    assert Path(result.geometry_path).exists()


async def test_invalid_url_raises_before_browser(tmp_path):
    r = PlaywrightDualViewportRenderer()
    with pytest.raises(ValueError):
        await r.render_all("ftp://example.com/x", tmp_path)
    with pytest.raises(ValueError):
        await r.render_all("https://user:pw@example.com/", tmp_path)


async def test_concurrent_runs_isolated(server_url, tmp_path):
    r = PlaywrightDualViewportRenderer(stabilization_ms=0)
    a, b = await asyncio.gather(
        r.render_all(f"{server_url}/rich", tmp_path),
        r.render_all(f"{server_url}/rich", tmp_path),
    )
    assert a.success and b.success
    assert a.output_dir != b.output_dir and a.run_id != b.run_id


async def test_detached_element_classified(server_url):
    r = PlaywrightDualViewportRenderer()
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await r._launch_browser(pw)
        try:
            page = await browser.new_page(
                viewport={"width": 1440, "height": 900})
            await page.goto(f"{server_url}/rich")
            injected = await page.evaluate(
                _INJECT_JS, {"minTarget": 25, "maxElements": 40})
            assert injected
            first = injected[0]["visor_el_id"]
            await page.evaluate(
                "(id) => document.querySelector("
                "'[data-visor-el-id=\"' + id + '\"]').remove()", first)
            raw = await page.evaluate(
                _EXTRACT_JS, [i["visor_el_id"] for i in injected])
            by_id = {x["visor_el_id"]: x for x in raw}
            assert by_id[first]["status"] == "detached"
        finally:
            await browser.close()
