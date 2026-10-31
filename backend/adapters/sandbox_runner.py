"""Local worktree sandbox (VISOR-ENV-001/002) + backward-compatible re-exports.

``LocalWorktreeSandboxRunner`` is the production zero-cost runner: an
isolated per-run copy/worktree of the target app under a sandbox temp
root, deterministic ``repository_files`` indexing, state injection for
Nodes 1-5, snapshot/rollback between strikes, a persistent dev-server
subprocess (own process group, free-port fallback), and live headless
Chromium dual-viewport capture. It subclasses ``LocalSandboxRunner`` so
all existing patch/HMR behaviour is reused unchanged.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.sandbox.interface import SandboxRunner as SandboxRunnerStrategy, ServerState
from backend.sandbox.local_runner import LocalSandboxRunner, _free_port
from backend.sandbox.modal_runner import ModalSandboxRunner

logger = logging.getLogger("visorqa.sandbox_runner")

EXCLUDED_DIRS = {".git", "node_modules", ".next", "dist", "build",
                 "__pycache__", ".visor-snapshots"}
CANONICAL_FIXTURE = {
    "src/components/PromoBanner.tsx": (
        'import React from "react";\n\n'
        "export function PromoBanner() {\n  return (\n"
        '    <div className="fixed top-0 z-50 promo-banner">\n'
        "      <span>Sale ends soon</span>\n    </div>\n  );\n}\n"),
    "src/app/checkout/CheckoutPage.tsx": (
        'import React from "react";\n'
        'import { PromoBanner } from "../../components/PromoBanner";\n'
        'import { Button } from "../../components/ui/Button";\n\n'
        "export function CheckoutPage() {\n  return (\n    <main>\n"
        "      <PromoBanner />\n      <h1>Checkout</h1>\n"
        "      <Button>Pay now</Button>\n    </main>\n  );\n}\n"),
    "src/components/ui/Button.tsx": (
        'import React from "react";\n\n'
        "export function Button({ children }: { children: React.ReactNode }) {\n"
        '  return <button className="ui-button">{children}</button>;\n}\n'),
    "package.json": '{"name": "demo-target-app", "private": true, "scripts": {"dev": "python3 -m http.server 3001 --bind 127.0.0.1"}}\n',
    "index.html": (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>Demo Target</title></head><body>\n"
        '<div class="promo-banner" data-visor-el-id="visor-el-01">'
        "<span>Sale ends soon</span></div>\n"
        '<main><h1>Checkout</h1>'
        '<button class="checkout-cta" data-visor-el-id="visor-el-04">Pay now</button>\n'
        '<a href="/checkout">Continue</a><input placeholder="Email"></main>\n'
        "</body></html>\n"),
}
SAFE_CHROMIUM_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
_GEOMETRY_JS = """() => {
  const sels = 'button,a[href],input,select,textarea,header,nav,[data-visor-el-id],[class*="card" i],article,main,h1';
  const seen = new Set(); const out = [];
  document.querySelectorAll(sels).forEach((el, i) => {
    if (seen.has(el)) return; seen.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.display === 'none' || cs.visibility === 'hidden' || r.width <= 0 || r.height <= 0) return;
    const id = el.getAttribute('data-visor-el-id') || ('visor-el-' + String(out.length+1).padStart(2,'0'));
    el.setAttribute('data-visor-el-id', id);
    // Real visibility measurement: sample points inside the element box
    // (clipped to the viewport) and count how many hit-test to this
    // element or one of its descendants. Occluding overlays (e.g. a fixed
    // banner) therefore lower the ratio exactly as a user would see it.
    let vrHits = 0, vrTotal = 0;
    const vx0 = Math.max(r.left, 0), vy0 = Math.max(r.top, 0);
    const vx1 = Math.min(r.right, innerWidth), vy1 = Math.min(r.bottom, innerHeight);
    if (vx1 > vx0 && vy1 > vy0) {
      const nx = Math.min(5, Math.max(1, Math.floor((vx1 - vx0) / 24)));
      const ny = Math.min(5, Math.max(1, Math.floor((vy1 - vy0) / 24)));
      for (let ix = 0; ix < nx; ix++) {
        for (let iy = 0; iy < ny; iy++) {
          const px = vx0 + ((ix + 0.5) * (vx1 - vx0)) / nx;
          const py = vy0 + ((iy + 0.5) * (vy1 - vy0)) / ny;
          const hit = document.elementFromPoint(px, py);
          vrTotal += 1;
          if (hit && (hit === el || el.contains(hit))) vrHits += 1;
        }
      }
    }
    const visibilityRatio = vrTotal ? vrHits / vrTotal : 0;
    out.push({element_id: id, visor_el_id: id, tag: el.tagName.toLowerCase(),
      visibility_ratio: visibilityRatio, v_r: visibilityRatio,
      bounding_box: {x: r.x, y: r.y, width: r.width, height: r.height},
      b_dom_box: {x: r.x, y: r.y, width: r.width, height: r.height},
      c_x: r.x + r.width/2, c_y: r.y + r.height/2,
      computed_css: {position: cs.position, zIndex: cs.zIndex, overflow: cs.overflow,
        display: cs.display, flexWrap: cs.flexWrap, visibility: cs.visibility},
      computed_styles: {position: cs.position, zIndex: cs.zIndex, overflow: cs.overflow,
        display: cs.display, flexWrap: cs.flexWrap, visibility: cs.visibility}});
  });
  return out.slice(0, 40);
}"""


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def ensure_target_fixture(source: Path) -> Path:
    """Create canonical target files under ``source`` only if missing."""
    source.mkdir(parents=True, exist_ok=True)
    for rel, content in CANONICAL_FIXTURE.items():
        target = source / rel
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return source


def list_repository_files(root: Path) -> List[str]:
    out: List[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(seg in EXCLUDED_DIRS or seg.startswith(".visor") for seg in rel.split("/")):
            continue
        out.append(rel)
    return sorted(out)


async def launch_chromium(pw: Any, headless: bool = True):
    """Launch Chromium with safe flags; fall back to system Chrome (ENV-002)."""
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path("/tmp/ms-playwright").is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/ms-playwright"
    try:
        return await pw.chromium.launch(headless=headless, args=SAFE_CHROMIUM_ARGS)
    except Exception:
        exe = Path(pw.chromium.executable_path)
        if exe.exists():
            return await pw.chromium.launch(headless=headless, executable_path=str(exe), args=SAFE_CHROMIUM_ARGS)
        for candidate in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
            if Path(candidate).exists():
                return await pw.chromium.launch(headless=headless, executable_path=candidate, args=SAFE_CHROMIUM_ARGS)
        return await pw.chromium.launch(headless=headless, channel="chrome", args=SAFE_CHROMIUM_ARGS)


class LocalWorktreeSandboxRunner(LocalSandboxRunner):
    """Isolated local worktree/workspace runner (zero billing)."""

    backend_name = "local"
    worktree_enabled = True

    def __init__(self, *, source_dir: Optional[str] = None,
                 target_app_port: Optional[int] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._source_dir = source_dir
        self._target_app_port = target_app_port
        self._used_worktree = False
        self._worktree_source: Optional[Path] = None
        self._snapshots: Dict[str, Path] = {}
        self._geo_cache: Dict[tuple, Any] = {}

    # -- provisioning ---------------------------------------------------
    def _prepare_checkout(self, workdir, source_dir, repo_url, branch, commit_sha):
        src_raw = source_dir or self._source_dir
        if repo_url or not src_raw:
            return super()._prepare_checkout(workdir, source_dir, repo_url, branch, commit_sha)
        src = Path(src_raw).expanduser()
        if src.resolve() == workdir.resolve():
            return
        if not src.is_dir() or not any(src.iterdir()):
            ensure_target_fixture(src)
        if (src / ".git").exists():
            # Fast detached worktree; fall back to the clone/copy path.
            try:
                workdir.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "-C", str(src), "worktree", "add", "--detach", str(workdir), "HEAD"],
                               check=True, capture_output=True, text=True, timeout=60)
                self._used_worktree = True
                self._worktree_source = src.resolve()
                return
            except Exception:
                self._used_worktree = False
                if workdir.exists():
                    shutil.rmtree(workdir, ignore_errors=True)
        return super()._prepare_checkout(workdir, str(src), repo_url, branch, commit_sha)

    async def create_or_attach(self, session_id, *, source_dir=None, repo_url=None,
                               branch="main", commit_sha="", authorized_files=None,
                               dev_command=None, port=None):
        if port is None and self._target_app_port:
            port = self._target_app_port if _port_free(int(self._target_app_port)) else _free_port()
        status = await super().create_or_attach(
            session_id, source_dir=source_dir or self._source_dir, repo_url=repo_url,
            branch=branch, commit_sha=commit_sha, authorized_files=authorized_files,
            dev_command=dev_command, port=port)
        if self.working_dir:
            self.snapshot("baseline")
        return status

    async def ensure_workspace(self, state: Any = None, run_id: str = "") -> Path:
        """Create/attach the per-run workspace for ``state.run_id``."""
        if self.working_dir and self.working_dir.is_dir():
            return self.working_dir
        rid = run_id or (getattr(state, "run_id", "") if state is not None else "") or "visor-run"
        source = self._source_dir
        if source is None:
            try:
                from backend.config import settings as _s
                source = str(Path(getattr(_s, "TARGET_APP_PATH", "./demo-target-app")))
                if self._target_app_port is None:
                    self._target_app_port = int(getattr(_s, "TARGET_APP_PORT", 3001))
            except Exception:
                source = "./demo-target-app"
        await self.create_or_attach(str(rid), source_dir=source)
        assert self.working_dir is not None
        return self.working_dir

    # -- state injection --------------------------------------------------
    def repository_files(self, root: Optional[Path] = None) -> List[str]:
        return list_repository_files(root or self.working_dir) if (root or self.working_dir) else []

    def inject_state(self, state: Any) -> Dict[str, Any]:
        """Inject checkout keys + file tree into state.repair_spec (no clobber)."""
        if not self.working_dir:
            return {}
        root = str(self.working_dir)
        files = self.repository_files()
        spec: Dict[str, Any] = dict(getattr(state, "repair_spec", {}) or {})
        for key in ("repo_root", "repository_root", "checkout_path", "workspace_dir",
                    "repo_path", "repository_path"):
            spec.setdefault(key, root)
        if not spec.get("repository_files") and files:
            spec["repository_files"] = files
        spec.setdefault("file_tree", spec.get("repository_files") or files)
        spec.setdefault("repo_files", spec.get("repository_files") or files)
        state.repair_spec = spec
        try:
            state.sandbox.working_dir = root
        except Exception:
            pass
        return spec

    async def ensure_and_inject(self, state: Any) -> Path:
        root = await self.ensure_workspace(state)
        self.inject_state(state)
        return root

    # -- snapshots / rollback ---------------------------------------------
    def snapshot(self, name: str = "baseline") -> Optional[Path]:
        if not self.working_dir or not self.working_dir.is_dir():
            return None
        dest = self.working_dir.parent / ".visor-snapshots" / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for rel in self.repository_files():
            src = self.working_dir / rel
            dst = dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self._snapshots[name] = dest
        return dest

    def restore_snapshot(self, name: str = "baseline") -> bool:
        return self.rollback(name)

    def rollback(self, name: str = "baseline") -> bool:
        """Reset workspace files to a snapshot; extra files are removed."""
        snap = self._snapshots.get(name) or (self.working_dir.parent / ".visor-snapshots" / name if self.working_dir else None)
        if not snap or not Path(snap).is_dir() or not self.working_dir:
            return False
        snap = Path(snap)
        keep = set(list_repository_files(snap))
        for rel in self.repository_files():
            if rel not in keep:
                (self.working_dir / rel).unlink(missing_ok=True)
        for rel in keep:
            dst = self.working_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snap / rel, dst)
        self._geo_cache.clear()
        return True

    def reset_to_baseline(self) -> bool:
        return self.rollback("baseline")

    # -- dev server ---------------------------------------------------------
    def _default_dev_command(self, port: int) -> List[str]:
        workdir = self.working_dir
        if workdir and (workdir / "index.html").is_file() and not (workdir / "node_modules" / "next").exists():
            return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(workdir)]
        return super()._default_dev_command(port)

    async def apply_patch(self, patch_text, *, authorized_files=None):
        result = await super().apply_patch(patch_text, authorized_files=authorized_files)
        if result.success:
            self._geo_cache.clear()
        return result

    async def wait_for_settle(self, timeout: float = 2.0) -> None:
        if self._status.patch_count:
            await self.wait_for_hmr(timeout=timeout)
        else:
            await asyncio.sleep(0.05)

    # -- Playwright dual-viewport capture -----------------------------------
    async def _render_live(self, width: int, height: int):
        url = await self.get_preview_url()
        if not url:
            return [], b""
        key = (url, width, height)
        if key in self._geo_cache:
            return self._geo_cache[key]
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                page = await browser.new_page(viewport={"width": width, "height": height})
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                geometry = await page.evaluate(_GEOMETRY_JS)
                # LCA for first two elements (hierarchy summary)
                try:
                    hierarchy = await page.evaluate("""(ids) => {
                      const els = ids.map(id => document.querySelector('[data-visor-el-id="'+id+'"]'));
                      function anc(el){ const o=[]; let c=el; while(c && c!==document.body){o.push(c.tagName.toLowerCase()); c=c.parentElement;} return o; }
                      if (els.length < 2 || !els[0] || !els[1]) return [];
                      const a = anc(els[0]), b = anc(els[1]);
                      const lca = a.find(x => b.includes(x)) || 'body';
                      return [{relationship:'selected_pair', element_ids: ids.slice(0,2), lca:{tag:lca}, lca_found:true, lca_status:'found'}];
                    }""", [g["element_id"] for g in geometry])
                except Exception:
                    hierarchy = []
                for g in geometry:
                    g["hierarchy"] = hierarchy
                    g["lca"] = hierarchy[0]["lca"] if hierarchy else None
                shot = await page.screenshot(type="png")
            finally:
                await browser.close()
        result = (geometry, shot)
        self._geo_cache[key] = result
        return result

    async def extract_dom_geometry(self, viewport_width: int, viewport_height: int):
        if not self.working_dir:
            return []
        try:
            geometry, _ = await self._render_live(int(viewport_width), int(viewport_height))
            return geometry
        except Exception:
            return []

    async def capture_screenshot(self, viewport_width: int, viewport_height: int) -> bytes:
        try:
            _, shot = await self._render_live(int(viewport_width), int(viewport_height))
            return shot
        except Exception:
            return b""

    async def capture_dual_viewport(self, url: Optional[str] = None) -> Dict[str, Any]:
        viewports: Dict[str, Any] = {}
        for name, (w, h) in (("mobile", (375, 812)), ("desktop", (1440, 900))):
            geometry, shot = await self._render_live(w, h)
            viewports[name] = {"width": w, "height": h, "screenshot": shot,
                               "screenshot_bytes": len(shot), "elements": geometry,
                               "geometry": geometry}
        return {"viewports": viewports, "mobile": viewports["mobile"], "desktop": viewports["desktop"]}

    # -- lifecycle ------------------------------------------------------------
    async def stop(self) -> None:
        await self.terminate()

    async def terminate(self) -> None:
        # Worktree deregistration + path-containment guard.
        workdir = self.working_dir
        if self._used_worktree and self._worktree_source and workdir:
            try:
                subprocess.run(["git", "-C", str(self._worktree_source), "worktree", "remove", "--force", str(workdir)],
                               capture_output=True, text=True, timeout=30)
            except Exception:
                pass
            self._used_worktree = False
        if workdir is not None:
            try:
                root = self.base_dir.resolve()
                session_root = workdir.parent.resolve()
                if root not in session_root.parents and session_root != root:
                    # Refuse to delete outside the sandbox temp root; still stop server.
                    self.cleanup_on_terminate = False
            except Exception:
                self.cleanup_on_terminate = False
        await super().terminate()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.terminate()
        return False


async def _e2b_run_cmd(sbx: Any, cmd: str, background: bool = False, timeout: int = 30) -> Any:
    fn = sbx.commands.run
    if inspect.iscoroutinefunction(fn):
        return await fn(cmd, background=background, timeout=timeout)
    return await asyncio.to_thread(fn, cmd, background=background, timeout=timeout)


async def _e2b_write_file(sbx: Any, path: str, data: bytes) -> Any:
    fn = sbx.files.write
    if inspect.iscoroutinefunction(fn):
        return await fn(path, data)
    return await asyncio.to_thread(fn, path, data)


async def _e2b_kill(sbx: Any) -> Any:
    fn = sbx.kill
    if inspect.iscoroutinefunction(fn):
        return await fn()
    return await asyncio.to_thread(fn)


class E2BSandboxRunner(LocalWorktreeSandboxRunner):
    """E2B cloud microVM sandbox with automatic local fallback.

    Provisions one ephemeral E2B sandbox per run (bounded timeout),
    uploads the workspace, serves it from the cloud VM, and records real
    telemetry (sandbox_id, provider label, HMR round-trip latency). Local
    files remain the patch/hashing source of truth; patched files are
    synced back to the VM. Any provisioning/capture failure logs a warning
    and seamlessly delegates to the local worktree runner — a live scan
    never crashes because E2B is unavailable. Cleanup kills the sandbox.
    """

    backend_name = "e2b"
    REMOTE_ROOT = "/home/user/app"

    def __init__(self, *, api_key: Optional[str] = None,
                 sandbox_timeout: int = 180,
                 source_dir: Optional[str] = None, **kwargs: Any):
        super().__init__(source_dir=source_dir, **kwargs)
        if api_key is None:
            try:
                from backend.config import settings as _s
                api_key = str(getattr(_s, "E2B_API_KEY", "") or "") or None
            except Exception:
                api_key = None
        self._api_key = api_key
        self._sandbox_timeout = int(sandbox_timeout or 180)
        self._sandbox: Any = None
        self._sandbox_id = ""
        self._e2b_active = False
        self._fallback_reason = ""
        self._local_fallback: Optional[LocalWorktreeSandboxRunner] = None
        self._run_id = ""
        self.hmr_latency_ms: Optional[float] = None

    # -- identity / telemetry ----------------------------------------------
    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def e2b_active(self) -> bool:
        return self._e2b_active

    @property
    def provider_label(self) -> str:
        if self._e2b_active and self._sandbox_id:
            return f"E2B CLOUD SANDBOX (sbx_{self._sandbox_id[:12]})"
        if self._fallback_reason:
            return "LOCAL WORKTREE SANDBOX"
        return "LOCAL WORKTREE SANDBOX"

    def _mark_status(self) -> None:
        self._status.backend = self.provider_label
        self._status.sandbox_id = self.sandbox_id or None
        if self.hmr_latency_ms is not None:
            self._status.timings.total_patch_to_hmr_ms = self.hmr_latency_ms
            self._status.timings.hmr_propagation_ms = self.hmr_latency_ms

    # -- provisioning ---------------------------------------------------------
    async def _provision_e2b(self, state: Any = None) -> Path:
        src = Path(self._source_dir or "./demo-target-app").expanduser()
        if not src.is_dir() or not any(src.iterdir()):
            src = ensure_target_fixture(src)
        try:
            from e2b import Sandbox
            self._sandbox = await asyncio.to_thread(
                Sandbox.create, timeout=self._sandbox_timeout, api_key=self._api_key)
        except Exception:
            from e2b import AsyncSandbox
            self._sandbox = await AsyncSandbox.create(
                timeout=self._sandbox_timeout, api_key=self._api_key)
        self._sandbox_id = str(getattr(self._sandbox, "sandbox_id", "") or "")
        # Upload the workspace (bounded; frontend/test files are small).
        uploaded = 0
        for rel in list_repository_files(src)[:200]:
            if uploaded >= 200:
                break
            try:
                data = (src / rel).read_bytes()
            except Exception:
                continue
            await _e2b_write_file(self._sandbox, f"{self.REMOTE_ROOT}/{rel}", data)
            uploaded += 1
        self._e2b_active = True
        # Local mirror stays the Node 4 snapshot/hash source of truth.
        self._status.working_dir = str(src)
        self._status.session_id = self._run_id
        self._mark_status()
        logger.info(f"E2B sandbox provisioned: {self.provider_label} "
                    f"({uploaded} files uploaded)")
        return src

    async def _fallback_local(self, state: Any = None, run_id: str = "") -> Path:
        if self._local_fallback is None:
            self._local_fallback = LocalWorktreeSandboxRunner(
                source_dir=self._source_dir)
        return await self._local_fallback.ensure_workspace(state, run_id)

    async def ensure_workspace(self, state: Any = None, run_id: str = "") -> Path:
        self._run_id = run_id or (getattr(state, "run_id", "") if state is not None else "") or self._run_id
        if self._e2b_active:
            return Path(self._status.working_dir)
        if not self._api_key:
            self._fallback_reason = "E2B_API_KEY not configured"
            logger.warning("E2B unavailable (no API key); using local worktree sandbox")
            return await super().ensure_workspace(state, run_id)
        try:
            return await self._provision_e2b(state)
        except Exception as exc:
            self._fallback_reason = f"E2B provisioning failed: {exc}"
            logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
            self._e2b_active = False
            self._sandbox = None
            self._sandbox_id = ""
            return await super().ensure_workspace(state, run_id)

    # -- dev server / preview --------------------------------------------------
    async def start_dev_server(self):  # type: ignore[override]
        if not self._e2b_active or self._sandbox is None:
            return await super().start_dev_server()
        port = int(self._target_app_port or 3001)
        try:
            await _e2b_run_cmd(
                self._sandbox,
                f"python3 -m http.server {port} --bind 0.0.0.0 --directory {self.REMOTE_ROOT}",
                background=True, timeout=30)
            host = self._sandbox.get_host(port)
            preview = f"https://{host}"
            # Bounded readiness poll against the public host URL.
            import httpx as _httpx
            deadline = time.monotonic() + 25.0
            ready = False
            while time.monotonic() < deadline:
                try:
                    async with _httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(preview)
                        if resp.status_code < 500:
                            ready = True
                            break
                except Exception:
                    pass
                await asyncio.sleep(0.75)
            if not ready:
                raise RuntimeError("E2B preview host did not become ready")
            self._status.preview_url = preview
            self._status.server_state = ServerState.RUNNING
            self._mark_status()
            return self._status
        except Exception as exc:
            self._fallback_reason = f"E2B dev server failed: {exc}"
            logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
            await self._kill_e2b()
            return await super().start_dev_server()

    async def get_preview_url(self) -> Optional[str]:
        if self._e2b_active and self._status.preview_url:
            return self._status.preview_url
        return await super().get_preview_url()

    async def get_status(self):  # type: ignore[override]
        status = await super().get_status()
        if self._e2b_active:
            status.backend = self.provider_label
            status.sandbox_id = self.sandbox_id or None
            status.preview_url = self._status.preview_url
            status.server_state = ServerState.RUNNING
            self._mark_status()
        return status

    # -- patch + cloud sync ------------------------------------------------------
    async def apply_patch(self, patch_text, *, authorized_files=None):  # type: ignore[override]
        result = await super().apply_patch(
            patch_text, authorized_files=authorized_files)
        if result.success and self._e2b_active and self._sandbox is not None:
            try:
                targets = list(authorized_files or [])
                if not targets:
                    targets = [ln[len("+++ b/"):].strip()
                               for ln in str(patch_text).split("\n")
                               if ln.startswith("+++ b/")]
                root = self.working_dir
                for rel in targets:
                    if root and (root / rel).is_file():
                        await _e2b_write_file(
                            self._sandbox,
                            f"{self.REMOTE_ROOT}/{rel}", (root / rel).read_bytes())
                # Measure the real cloud reload round-trip as HMR latency.
                preview = await self.get_preview_url()
                started = time.monotonic()
                measured = False
                if preview:
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=10.0) as client:
                        for _ in range(5):
                            try:
                                resp = await client.get(preview)
                                if resp.status_code < 500:
                                    measured = True
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                if measured:
                    self.hmr_latency_ms = round((time.monotonic() - started) * 1000.0, 2)
                else:
                    t_ping = time.monotonic()
                    await _e2b_run_cmd(self._sandbox, "true", background=False, timeout=10)
                    self.hmr_latency_ms = round((time.monotonic() - t_ping) * 1000.0, 2)
                self._mark_status()
            except Exception as exc:
                logger.warning(f"E2B patch sync/HMR measure failed: {exc}")
        return result

    # -- capture with fallback ---------------------------------------------------
    async def extract_dom_geometry(self, viewport_width: int, viewport_height: int):
        geometry = await super().extract_dom_geometry(viewport_width, viewport_height)
        if geometry or not self._e2b_active:
            return geometry
        logger.warning("E2B browser capture returned no geometry; "
                       "falling back to local sandbox capture")
        self._fallback_reason = "E2B browser capture empty"
        if self._local_fallback is None:
            await self._fallback_local(None, self._run_id)
        assert self._local_fallback is not None
        return await self._local_fallback.extract_dom_geometry(
            viewport_width, viewport_height)

    # -- lifecycle -----------------------------------------------------------------
    async def _kill_e2b(self) -> None:
        if self._sandbox is not None:
            try:
                await _e2b_kill(self._sandbox)
            except Exception:
                pass
            self._sandbox = None
        self._e2b_active = False
        self._sandbox_id = ""

    async def terminate(self) -> None:
        try:
            await self._kill_e2b()
        finally:
            await super().terminate()


class StubSandboxRunner(LocalWorktreeSandboxRunner):
    """Offline stub: workspace/file-tree only, never spawns a browser/server."""

    backend_name = "stub"

    async def start_dev_server(self):
        return await self.get_status()

    async def extract_dom_geometry(self, viewport_width, viewport_height):
        return []

    async def capture_screenshot(self, viewport_width, viewport_height):
        return b""


def create_sandbox_runner(settings_obj: Any = None, backend: Optional[str] = None):
    from backend.sandbox.factory import create_sandbox_runner as _create
    return _create(settings_obj, backend)


get_sandbox_runner = create_sandbox_runner

# Historical alias required by the task / older imports.
LocalPlaywrightRunner = LocalWorktreeSandboxRunner
SandboxRunner = SandboxRunnerStrategy

__all__ = [
    "SandboxRunnerStrategy", "SandboxRunner", "LocalSandboxRunner",
    "LocalWorktreeSandboxRunner", "LocalPlaywrightRunner", "StubSandboxRunner",
    "ModalSandboxRunner", "EXCLUDED_DIRS", "CANONICAL_FIXTURE",
    "ensure_target_fixture", "list_repository_files", "launch_chromium",
    "create_sandbox_runner", "get_sandbox_runner",
]
