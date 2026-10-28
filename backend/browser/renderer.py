"""Async Playwright dual-viewport renderer & DOM geometry extractor.

SENSE-node support: opens a PR preview URL at mobile (375x812) and desktop
(1440x900), injects unique ``data-visor-el-id`` attributes into 25-40
eligible elements, extracts viewport-relative ``B_DOM`` boxes plus centers,
and captures exact-size viewport PNGs (``mobile.png`` / ``desktop.png``).

Usage::

    result = await render_dual_viewport("https://preview.example/pr-1")
    # or
    renderer = PlaywrightDualViewportRenderer()
    result = await renderer.render_all(url, output_dir="artifacts")

``result.success`` is True only when *both* viewports succeed.
CLI: ``python -m backend.browser.renderer <preview-url> [output-dir]``
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from backend.browser.schemas import (
    DualViewportResult,
    ElementGeometry,
    ElementStatus,
    HierarchyRecord,
    ViewportRenderResult,
)
from backend.config import settings
from backend.core.state import DOMBoundingBox

logger = logging.getLogger("visorqa.browser")

# Matches backend.core.orchestrator.VIEWPORTS: (width, height) CSS pixels.
VIEWPORTS: Dict[str, Tuple[int, int]] = {
    "mobile": (375, 812),
    "desktop": (1440, 900),
}
MIN_TARGET_ELEMENTS = 25
MAX_ELEMENTS = 40
_ID_PREFIX = "visor-el-"


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a browser)
# ---------------------------------------------------------------------------

def validate_preview_url(url: str, allowed_schemes: Optional[Sequence[str]] = None) -> str:
    """Validate ``url``; permit only configured schemes. Returns the URL.

    Rejects missing scheme/host, unsupported schemes, and embedded
    credentials (which must never reach logs or artifacts).
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("preview URL must be a non-empty string")
    schemes = [s.lower() for s in (allowed_schemes or _configured_schemes())]
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in schemes:
        raise ValueError(f"unsupported URL scheme {parsed.scheme!r}; allowed: {schemes}")
    if not parsed.hostname:
        raise ValueError("preview URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("preview URL must not embed credentials")
    return url.strip()


def _configured_schemes() -> List[str]:
    raw = getattr(settings, "BROWSER_ALLOWED_SCHEMES", "http,https")
    if isinstance(raw, (list, tuple)):
        return [str(s) for s in raw]
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def sanitize_url(url: str) -> str:
    """Strip credentials, query, and fragment for logs/artifacts."""
    try:
        p = urlparse(url)
        host = p.hostname or ""
        if p.port:
            host = f"{host}:{p.port}"
        return f"{p.scheme}://{host}{p.path or '/'}"
    except Exception:
        return "<invalid-url>"


def compute_center(box: DOMBoundingBox) -> Tuple[float, float]:
    """c_x = x + width/2, c_y = y + height/2 (float precision preserved)."""
    return (box.x + box.width / 2.0, box.y + box.height / 2.0)


def png_dimensions(data: bytes) -> Tuple[int, int]:
    """Read (width, height) from a PNG IHDR chunk without Pillow."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    width, height = struct.unpack(">II", data[16:24])
    return (width, height)


# ---------------------------------------------------------------------------
# In-page scripts
# ---------------------------------------------------------------------------

# Selection + injection. Returns [{visor_el_id, category, tag, label}].
# Priority: modal/menu > sticky/fixed > navigation > button > link >
# form_input > card. Hidden / zero-sized / fully-off-viewport elements are
# excluded; near-duplicate nested wrappers (same category nesting or
# ~identical rects) are skipped. Existing data-visor-el-id values are
# preserved and reserved so generated IDs never collide.
_INJECT_JS = r"""
({minTarget, maxElements}) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const used = new Set();
  document.querySelectorAll('[data-visor-el-id]').forEach(el => {
    const v = el.getAttribute('data-visor-el-id');
    if (v) used.add(v);
  });
  const PRIORITY = {modal_dialog:0, menu_popover:1, sticky_fixed:2,
    navigation:3, button:4, link:5, form_input:6, card:7};
  function categoryOf(el) {
    const role = (el.getAttribute('role') || '').toLowerCase();
    const tag = el.tagName.toLowerCase();
    const cs = window.getComputedStyle(el);
    if (tag === 'dialog' || role === 'dialog' || role === 'alertdialog' ||
        el.getAttribute('aria-modal') === 'true') return 'modal_dialog';
    if (role === 'menu' || role === 'menubar' || role === 'listbox' ||
        el.hasAttribute('data-popover')) return 'menu_popover';
    if (tag === 'nav' || role === 'navigation') return 'navigation';
    if ((cs.position === 'fixed' || cs.position === 'sticky') &&
        (tag === 'header' || tag === 'div' || tag === 'section' ||
         role === 'banner')) return 'sticky_fixed';
    if (tag === 'button' || role === 'button' ||
        (tag === 'input' && ['button','submit','reset'].includes(
          (el.getAttribute('type')||'').toLowerCase()))) return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (['input','select','textarea'].includes(tag) ||
        el.isContentEditable) return 'form_input';
    if (cs.position === 'fixed' || cs.position === 'sticky')
      return 'sticky_fixed';
    return 'card';
  }
  const SELECTORS = [
    'dialog[open]', '[role="dialog"]', '[role="alertdialog"]',
    '[aria-modal="true"]', '[role="menu"]', '[role="menubar"]',
    '[data-popover]', 'header', 'nav', '[role="navigation"]',
    '[role="banner"]', 'button', '[role="button"]',
    'input[type="button"]', 'input[type="submit"]', 'input[type="reset"]',
    'a[href]', 'input:not([type="hidden"])', 'select', 'textarea',
    '[contenteditable="true"]', '[class*="card" i]', '[data-card]',
    'article',
  ];
  const seen = new Set(); const candidates = [];
  document.querySelectorAll(SELECTORS.join(',')).forEach(el => {
    if (seen.has(el)) return; seen.add(el);
    candidates.push(el);
  });
  function isEligible(el) {
    if (!el.isConnected) return false;
    const cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    // Must at least partially intersect the visible viewport.
    if (r.bottom <= 0 || r.right <= 0 || r.left >= vw || r.top >= vh)
      return false;
    return true;
  }
  const docOrder = new Map();
  document.querySelectorAll('*').forEach((el, i) => docOrder.set(el, i));
  const eligible = candidates.filter(isEligible).map(el => ({
    el, category: categoryOf(el),
  }));
  eligible.sort((a, b) =>
    (PRIORITY[a.category] - PRIORITY[b.category]) ||
    ((docOrder.get(a.el) || 0) - (docOrder.get(b.el) || 0)));
  const selected = [];
  function nearSameRect(a, b) {
    return Math.abs(a.left-b.left) < 2 && Math.abs(a.top-b.top) < 2 &&
           Math.abs(a.right-b.right) < 2 && Math.abs(a.bottom-b.bottom) < 2;
  }
  for (const cand of eligible) {
    if (selected.length >= maxElements) break;
    const rect = cand.el.getBoundingClientRect();
    let redundant = false;
    for (const s of selected) {
      const nested = s.el.contains(cand.el) || cand.el.contains(s.el);
      if (nested && (s.category === cand.category ||
                     nearSameRect(s.el.getBoundingClientRect(), rect))) {
        redundant = true; break;
      }
    }
    if (redundant) continue;
    let id = cand.el.getAttribute('data-visor-el-id');
    if (!id || used.has(id) && selected.some(s => s.visor_el_id === id)) {
      let n = selected.length + 1;
      do { id = 'visor-el-' + String(n).padStart(2, '0'); n += 1; }
      while (used.has(id));
      cand.el.setAttribute('data-visor-el-id', id);
    }
    used.add(id);
    const label = (cand.el.getAttribute('aria-label') ||
      cand.el.innerText || cand.el.getAttribute('placeholder') ||
      cand.el.getAttribute('name') || cand.el.getAttribute('title') ||
      '').trim().replace(/\s+/g, ' ').slice(0, 80);
    selected.push({el: cand.el, visor_el_id: id,
      category: cand.category,
      tag: cand.el.tagName.toLowerCase(), label});
  }
  return selected.map(s => ({visor_el_id: s.visor_el_id,
    category: s.category, tag: s.tag, label: s.label}));
}
"""

# Hierarchy + LCA extraction. Single page.evaluate() per viewport.
# Adjacency rule (explicit): an "adjacent sibling pair" is two *selected*
# elements that are consecutive selected entries in the same parent's
# `children` collection. Arbitrary nearby / document-order elements are
# NOT treated as siblings; caller-supplied pairs are labelled
# `selected_pair` unless they meet the sibling rule.
# Ancestor chains stop at <body> (structural boundary) or maxAncestorDepth.
# React hints: explicit app markers (data-component etc.) first; Fiber-key
# heuristic second and always marked source="heuristic". Form values are
# never read (password fields yield no text hint at all).
_HIERARCHY_JS = r"""
({ids, maxAncestorDepth, pairs}) => {
  const MAX_DEPTH = maxAncestorDepth || 8;
  const trunc = (s, n) => (s || '').trim().replace(/\s+/g, ' ').slice(0, n);
  function cssSignature(el) {
    if (!el || !el.isConnected) return null;
    const cs = window.getComputedStyle(el);
    const pick = (p) => cs.getPropertyValue(p) || '';
    return {position: pick('position'), 'z-index': pick('z-index'),
      display: pick('display'), 'flex-direction': pick('flex-direction'),
      'flex-wrap': pick('flex-wrap'), overflow: pick('overflow'),
      'overflow-x': pick('overflow-x'), 'overflow-y': pick('overflow-y'),
      width: pick('width'), 'max-width': pick('max-width')};
  }
  function reactHint(el) {
    const ATTRS = ['data-component', 'data-react-component',
      'data-component-name', 'data-visor-component'];
    try {
      const marked = el.closest(ATTRS.map(a => '[' + a + ']').join(','));
      if (marked) for (const a of ATTRS) {
        const v = marked.getAttribute(a);
        if (v) return {react_hint: trunc(v, 80),
                       react_hint_source: 'explicit_marker'};
      }
    } catch (e) {}
    try {
      const key = Object.keys(el).find(k =>
        k.startsWith('__reactFiber$') || k.startsWith('__reactContainer$'));
      if (key) {
        let node = el[key], hops = 0;
        while (node && hops < 16) {
          const t = node.type;
          const name = (t && (t.displayName ||
            (typeof t === 'function' && t.name) ||
            (typeof t === 'object' && t.name))) || '';
          if (name && typeof t !== 'string')
            return {react_hint: trunc(String(name), 80),
                    react_hint_source: 'heuristic'};
          node = node.return; hops += 1;
        }
        return {react_hint: null, react_hint_source: 'heuristic'};
      }
    } catch (e) {}
    return {react_hint: null, react_hint_source: null};
  }
  function descriptor(el) {
    if (!el) return null;
    const tag = el.tagName.toLowerCase();
    const isForm = ['input','select','textarea'].includes(tag);
    const isPassword = tag === 'input' &&
      (el.getAttribute('type') || '') === 'password';
    let text = el.getAttribute('aria-label') || '';
    if (!text && isForm && !isPassword)
      text = el.getAttribute('placeholder') || el.getAttribute('name') || '';
    if (!text && !isForm) text = el.innerText || '';
    const hint = reactHint(el);
    return {tag, id: el.id || '',
      classes: Array.from(el.classList || []).slice(0, 8)
        .map(c => trunc(c, 48)),
      'data-visor-el-id': el.getAttribute('data-visor-el-id'),
      role: el.getAttribute('role'),
      'aria-label': trunc(el.getAttribute('aria-label') || '', 80) || null,
      'data-testid': el.getAttribute('data-testid'),
      text_hint: trunc(text, 60), ...hint};
  }
  function ancestorsInclusive(el) {
    const out = []; let cur = el, guard = 0;
    while (cur && cur.nodeType === 1 && guard < 64) {
      out.push(cur); guard += 1;
      if (cur === document.body) break;
      cur = cur.parentElement;
    }
    return out;
  }
  function findLCA(a, b) {
    if (!a || !b) return {lca: null, status: 'detached'};
    if (!a.isConnected || !b.isConnected)
      return {lca: null, status: 'detached'};
    if (a === b) return {lca: a, status: 'identical'};
    const setA = new Set(ancestorsInclusive(a));
    let cur = b, guard = 0;
    while (cur && cur.nodeType === 1 && guard < 64) {
      if (setA.has(cur)) return {lca: cur, status: 'found'};
      if (cur === document.body) break;
      cur = cur.parentElement; guard += 1;
    }
    return {lca: null, status: 'no_common_ancestor'};
  }
  function byId(id) {
    if (!id) return null;
    try { return document.querySelector(
      '[data-visor-el-id="' + CSS.escape(id) + '"]'); }
    catch (e) { return null; }
  }
  const resolved = new Map(ids.map(id => [id, byId(id)]));
  const records = [];
  // 1) element_ancestry per selected element (LCA of element with itself).
  for (const id of ids) {
    const el = resolved.get(id);
    if (!id) { records.push({relationship: 'element_ancestry',
      element_ids: [id], element: null, ancestor_chain: [],
      lca: null, lca_found: false, lca_status: 'missing_id',
      lca_css_signature: null, element_css_signatures: {}}); continue; }
    if (!el || !el.isConnected) {
      records.push({relationship: 'element_ancestry', element_ids: [id],
        element: null, ancestor_chain: [], lca: null, lca_found: false,
        lca_status: 'detached',
        notes: 'element not found in document (detached or removed)',
        lca_css_signature: null, element_css_signatures: {}}); continue; }
    const chain = ancestorsInclusive(el).slice(1, MAX_DEPTH + 1);
    records.push({relationship: 'element_ancestry', element_ids: [id],
      element: descriptor(el), sibling: null,
      ancestor_chain: chain.map(descriptor),
      chain_truncated: chain.length >= MAX_DEPTH &&
        chain[chain.length - 1] !== document.body,
      lca: descriptor(el), lca_found: true, lca_status: 'identical',
      notes: 'self-LCA: lowest common ancestor of the element with itself',
      lca_css_signature: cssSignature(el),
      element_css_signatures: {[id]: cssSignature(el)}});
  }
  // 2) adjacent sibling pairs: consecutive selected children per parent.
  const pairKeys = new Set(); const pairList = [];
  const byParent = new Map();
  for (const id of ids) {
    const el = resolved.get(id);
    if (!el || !el.isConnected || !el.parentElement) continue;
    const p = el.parentElement;
    if (!byParent.has(p)) byParent.set(p, []);
    byParent.get(p).push(id);
  }
  for (const [parent, childIds] of byParent) {
    const ordered = childIds.slice().sort((a, b) => {
      const kids = Array.from(parent.children);
      return kids.indexOf(resolved.get(a)) - kids.indexOf(resolved.get(b));
    });
    for (let i = 0; i + 1 < ordered.length; i++) {
      const key = ordered[i] + '|' + ordered[i + 1];
      if (!pairKeys.has(key)) { pairKeys.add(key);
        pairList.push([ordered[i], ordered[i + 1],
                       'adjacent_sibling_pair']); }
    }
  }
  // 3) caller-supplied pairs (never silently relabelled as siblings).
  for (const pr of (pairs || [])) {
    if (!Array.isArray(pr) || pr.length !== 2) continue;
    const key = pr[0] + '|' + pr[1];
    if (pairKeys.has(key)) continue;
    pairKeys.add(key);
    const a = resolved.get(pr[0]) || byId(pr[0]);
    const b = resolved.get(pr[1]) || byId(pr[1]);
    const sibling = a && b && a.parentElement &&
      a.parentElement === b.parentElement;
    pairList.push([pr[0], pr[1],
      sibling ? 'adjacent_sibling_pair' : 'selected_pair']);
  }
  for (const [idA, idB, rel] of pairList) {
    const a = resolved.get(idA) || byId(idA);
    const b = resolved.get(idB) || byId(idB);
    const {lca, status} = findLCA(a, b);
    const chain = lca ? ancestorsInclusive(lca).slice(0, MAX_DEPTH) : [];
    const css = {};
    if (a) css[idA] = cssSignature(a);
    if (b) css[idB] = cssSignature(b);
    records.push({relationship: rel, element_ids: [idA, idB],
      element: a ? descriptor(a) : null,
      sibling: b ? descriptor(b) : null,
      ancestor_chain: chain.map(descriptor),
      chain_truncated: chain.length >= MAX_DEPTH &&
        chain[chain.length - 1] !== document.body,
      lca: lca ? descriptor(lca) : null,
      lca_found: !!lca, lca_status: status,
      lca_css_signature: lca ? cssSignature(lca) : null,
      element_css_signatures: css});
  }
  return records;
}
"""


def _build_geometry(
    injected: List[Dict[str, Any]],
    raw: List[Dict[str, Any]],
    viewport_name: str,
) -> List[ElementGeometry]:
    """Merge injection metadata with extracted boxes; compute centers."""
    meta = {m["visor_el_id"]: m for m in injected}
    out: List[ElementGeometry] = []
    for item in raw:
        vid = item["visor_el_id"]
        m = meta.get(vid, {})
        box_data = item.get("B_DOM")
        box = DOMBoundingBox(**box_data) if box_data else None
        c_x = c_y = None
        if box is not None and item.get("status") not in (
            ElementStatus.DETACHED.value,
        ):
            c_x, c_y = compute_center(box)
        out.append(
            ElementGeometry(
                visor_el_id=vid,
                category=m.get("category", ""),
                tag=m.get("tag", ""),
                label=m.get("label", ""),
                B_DOM=box,
                c_x=c_x,
                c_y=c_y,
                viewport=viewport_name,
                status=item.get("status", "ok"),
                in_viewport=bool(item.get("in_viewport", False)),
                partially_visible=bool(item.get("partially_visible", False)),
            )
        )
    return out


def _build_hierarchy(
    raw: List[Dict[str, Any]], viewport_name: str
) -> List["HierarchyRecord"]:
    out: List[HierarchyRecord] = []
    for item in raw or []:
        item = {**item, "viewport": viewport_name}
        # JS emits null CSS signatures for detached nodes; drop null values
        # in element_css_signatures so typed validation stays clean.
        if isinstance(item.get("element_css_signatures"), dict):
            item["element_css_signatures"] = {
                k: v for k, v in item["element_css_signatures"].items() if v
            }
        out.append(HierarchyRecord(**item))
    return out


async def extract_hierarchy(
    page: Any,
    ids: Sequence[str],
    pairs: Optional[Sequence[Sequence[str]]] = None,
    max_ancestor_depth: int = 8,
    viewport_name: str = "",
) -> List["HierarchyRecord"]:
    """Run the single LCA ``page.evaluate()`` for already-identified IDs."""
    raw = await page.evaluate(
        _HIERARCHY_JS,
        {"ids": list(ids), "maxAncestorDepth": int(max_ancestor_depth),
         "pairs": [list(p) for p in (pairs or [])]},
    )
    return _build_hierarchy(raw, viewport_name)


class PlaywrightDualViewportRenderer:
    """Render one URL at both viewports; isolate failures per viewport."""

    def __init__(
        self,
        navigation_timeout_ms: Optional[int] = None,
        stabilization_ms: int = 150,
        network_idle_timeout_ms: int = 3000,
        allowed_schemes: Optional[Sequence[str]] = None,
        headless: bool = True,
        max_ancestor_depth: int = 8,
        include_hierarchy: bool = True,
    ) -> None:
        self.navigation_timeout_ms = int(
            navigation_timeout_ms
            or getattr(settings, "BROWSER_NAV_TIMEOUT_MS", 30000)
        )
        self.stabilization_ms = stabilization_ms
        self.network_idle_timeout_ms = network_idle_timeout_ms
        self.allowed_schemes = allowed_schemes
        self.headless = headless
        self.max_ancestor_depth = int(max_ancestor_depth)
        self.include_hierarchy = include_hierarchy

    async def render_all(
        self, preview_url: str, output_dir: Optional[str | Path] = None
    ) -> DualViewportResult:
        url = validate_preview_url(preview_url, self.allowed_schemes)
        run_id = uuid4().hex[:12]
        # Collision-safe artifact dir for concurrent runs.
        base = Path(output_dir) if output_dir else Path(
            getattr(settings, "BROWSER_ARTIFACTS_DIR", "artifacts")
        )
        run_dir = base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result = DualViewportResult(
            run_id=run_id, preview_url=sanitize_url(url),
            output_dir=str(run_dir),
        )
        # Imported lazily so URL-validation errors surface without a browser.
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as pw:
                browser = await self._launch_browser(pw)
                try:
                    for name, (w, h) in VIEWPORTS.items():
                        vp = await self._render_viewport(
                            browser, url, name, w, h, run_dir
                        )
                        result.viewports.append(vp)
                        if vp.error:
                            result.errors.append(f"{name}: {vp.error}")
                finally:
                    await browser.close()
        except Exception as exc:  # browser launch failure: fail both
            msg = f"browser launch failed: {type(exc).__name__}"
            logger.error("render_all %s for %s", msg, sanitize_url(url))
            for name, (w, h) in VIEWPORTS.items():
                if result.viewport(name) is None:
                    result.viewports.append(ViewportRenderResult(
                        name=name, width=w, height=h, error=msg))
            result.errors.append(msg)
        result.success = (
            len(result.viewports) == len(VIEWPORTS)
            and all(v.error is None for v in result.viewports)
        )
        geometry_path = run_dir / "geometry.json"
        geometry_path.write_text(
            json.dumps(result.model_dump(by_alias=True), indent=2),
            encoding="utf-8",
        )
        result.geometry_path = str(geometry_path)
        # Rewrite so geometry_path itself is recorded in the file.
        geometry_path.write_text(
            json.dumps(result.model_dump(by_alias=True), indent=2),
            encoding="utf-8",
        )
        return result

    async def _launch_browser(self, pw):
        """Launch Chromium, falling back to a system Chrome if needed.

        Primary path uses Playwright's bundled headless shell
        (``playwright install chromium``). If that build is absent, fall
        back to the full Chromium executable, then to system Chrome
        (``channel="chrome"``) with sandbox-safe flags.
        """
        try:
            return await pw.chromium.launch(headless=self.headless)
        except Exception:
            exe = Path(pw.chromium.executable_path)
            if exe.exists():
                return await pw.chromium.launch(
                    headless=self.headless, executable_path=str(exe),
                    args=["--no-sandbox", "--disable-dev-shm-usage"])
            return await pw.chromium.launch(
                headless=self.headless, channel="chrome",
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-gpu"])

    async def _render_viewport(self, browser, url, name, width, height,
                               run_dir: Path) -> ViewportRenderResult:
        vp = ViewportRenderResult(name=name, width=width, height=height)
        context = page = None
        try:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,  # 1 CSS px == 1 screenshot px
            )
            context.set_default_timeout(self.navigation_timeout_ms)
            context.set_default_navigation_timeout(
                self.navigation_timeout_ms)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded",
                            timeout=self.navigation_timeout_ms)
            # Readiness without depending exclusively on networkidle.
            try:
                await page.wait_for_load_state(
                    "load", timeout=self.navigation_timeout_ms)
            except Exception:
                pass
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=self.network_idle_timeout_ms)
            except Exception:
                pass  # long-polling pages: readiness already established
            await page.evaluate(
                "() => new Promise(r => requestAnimationFrame("
                "() => requestAnimationFrame(r)))")
            if self.stabilization_ms:
                await page.wait_for_timeout(self.stabilization_ms)
            injected = await page.evaluate(
                _INJECT_JS,
                {"minTarget": MIN_TARGET_ELEMENTS,
                 "maxElements": MAX_ELEMENTS},
            )
            ids = [i["visor_el_id"] for i in injected]
            raw = await page.evaluate(_EXTRACT_JS, ids) if ids else []
            elements = _build_geometry(injected, raw, name)
            # Drop detached/hidden/zero-sized from reported geometry? No:
            # they stay, explicitly flagged via `status`.
            vp.elements = elements
            vp.element_count = len(elements)
            vp.target_range_met = (
                MIN_TARGET_ELEMENTS <= len(elements) <= MAX_ELEMENTS)
            if self.include_hierarchy and ids:
                vp.hierarchy = await extract_hierarchy(
                    page, ids,
                    max_ancestor_depth=self.max_ancestor_depth,
                    viewport_name=name)
            # Screenshot last, with no scroll/mutation after extraction,
            # so geometry and pixels describe the same layout state.
            shot = run_dir / f"{name}.png"
            await page.screenshot(path=str(shot), type="png",
                                  full_page=False)
            vp.screenshot_path = str(shot)
            vp.screenshot_width, vp.screenshot_height = png_dimensions(
                shot.read_bytes())
            if (vp.screenshot_width, vp.screenshot_height) != (width, height):
                vp.error = (
                    f"screenshot size {vp.screenshot_width}x"
                    f"{vp.screenshot_height} != viewport {width}x{height}")
        except Exception as exc:
            vp.error = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("viewport %s failed for %s: %s",
                           name, sanitize_url(url), type(exc).__name__)
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
        return vp


async def render_dual_viewport(
    preview_url: str, output_dir: Optional[str | Path] = None, **kwargs: Any
) -> DualViewportResult:
    """Convenience entry point used by the SENSE node / CLI."""
    return await PlaywrightDualViewportRenderer(**kwargs).render_all(
        preview_url, output_dir)


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preview_url")
    parser.add_argument("output_dir", nargs="?", default=None)
    args = parser.parse_args(argv)
    result = asyncio.run(render_dual_viewport(
        args.preview_url, args.output_dir))
    print(json.dumps(result.model_dump(by_alias=True), indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(_main())


# Geometry for previously injected IDs. Missing node => detached; the rest
# are classified explicitly. No scrolling is performed.
_EXTRACT_JS = r"""
(ids) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  return ids.map(id => {
    const el = document.querySelector(
      '[data-visor-el-id="' + CSS.escape(id) + '"]');
    if (!el || !el.isConnected)
      return {visor_el_id: id, status: 'detached', B_DOM: null};
    const r = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    const box = {x: r.x, y: r.y, width: r.width, height: r.height};
    if (cs.display === 'none' || cs.visibility === 'hidden')
      return {visor_el_id: id, status: 'hidden', B_DOM: box};
    if (r.width <= 0 || r.height <= 0)
      return {visor_el_id: id, status: 'zero_size', B_DOM: box};
    const intersects = r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
    const fullyIn = r.left >= 0 && r.top >= 0 && r.right <= vw && r.bottom <= vh;
    if (!intersects)
      return {visor_el_id: id, status: 'off_viewport', B_DOM: box,
              in_viewport: false, partially_visible: false};
    return {visor_el_id: id,
      status: fullyIn ? 'ok' : 'partially_off_viewport', B_DOM: box,
      in_viewport: true, partially_visible: !fullyIn};
  });
}
"""
