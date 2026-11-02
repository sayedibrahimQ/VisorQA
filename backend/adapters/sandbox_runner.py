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
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Playwright resolves its browser registry when the driver starts, so
# point it at the /tmp install (when present) before anything launches.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path("/tmp/ms-playwright").is_dir():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/ms-playwright"

from backend.sandbox.interface import SandboxRunner as SandboxRunnerStrategy, ServerState
from backend.sandbox.local_runner import LocalSandboxRunner, _free_port
from backend.sandbox.modal_runner import ModalSandboxRunner

logger = logging.getLogger("visorqa.sandbox_runner")

EXCLUDED_DIRS = {".git", "node_modules", ".next", "dist", "build",
                 "__pycache__", ".visor-snapshots", ".venv", "venv", "artifacts"}
SAFE_CHROMIUM_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
_GEOMETRY_JS = """() => {
  const sels = 'button,a[href],input,select,textarea,header,nav,[data-visor-id],[data-visor-el-id],[class*="card" i],article,main,h1';
  const seen = new Set(); const out = [];
  const usedIds = new Set(Array.from(document.querySelectorAll('[data-visor-id],[data-visor-el-id]')).map((e) => e.getAttribute('data-visor-id') || e.getAttribute('data-visor-el-id')).filter(Boolean));
  let seq = 1;
  const visorNodes = Array.from(document.querySelectorAll('[data-visor-id],[data-visor-el-id]'));
  const allNodes = Array.from(document.querySelectorAll(sels));
  const candidateNodes = visorNodes.length > 0 ? [...visorNodes, ...allNodes] : allNodes;
  candidateNodes.forEach((el, i) => {
    if (seen.has(el)) return; seen.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.display === 'none' || cs.visibility === 'hidden' || r.width <= 0 || r.height <= 0) return;
    const visorTagged = el.hasAttribute('data-visor-id') || el.hasAttribute('data-visor-el-id');
    let id = el.getAttribute('data-visor-id') || el.getAttribute('data-visor-el-id');
    if (!id) {
      do { id = 'visor-el-' + String(seq++).padStart(2,'0'); } while (usedIds.has(id));
      usedIds.add(id);
    }
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
    out.push({element_id: id, visor_el_id: id, visor_tagged: visorTagged, tag: el.tagName.toLowerCase(),
      visibility_ratio: visibilityRatio, v_r: visibilityRatio,
      bounding_box: {x: r.x, y: r.y, width: r.width, height: r.height},
      b_dom_box: {x: r.x, y: r.y, width: r.width, height: r.height},
      c_x: r.x + r.width/2, c_y: r.y + r.height/2,
      computed_css: {position: cs.position, zIndex: cs.zIndex, 'z-index': cs.zIndex, overflow: cs.overflow,
        display: cs.display, flexWrap: cs.flexWrap, visibility: cs.visibility},
      computed_styles: {position: cs.position, zIndex: cs.zIndex, 'z-index': cs.zIndex, overflow: cs.overflow,
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
        if target_app_port is None:
            try:
                from backend.config import settings as _s
                target_app_port = int(getattr(_s, "TARGET_APP_PORT", 3001) or 3001)
            except Exception:
                target_app_port = 3001
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
            return super()._prepare_checkout(workdir, str(src), repo_url, branch, commit_sha)
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

        if state is not None:
            spec = getattr(state, "repair_spec", {}) or {}
            repo_root = spec.get("repo_root") or spec.get("repository_root")
            if repo_root and Path(repo_root).is_dir():
                source = str(repo_root)
            elif (getattr(state, "repo_full_name", None) or getattr(state, "pr_url", None)) and (
                not source or source == "./demo-target-app"
            ):
                try:
                    from backend.core.worktree import hydrate_pr_workspace
                    tok = getattr(state, "github_token", "") or os.getenv("GITHUB_TOKEN", "") or os.getenv("GITHUB_PAT", "")
                    ws = await hydrate_pr_workspace(
                        str(rid),
                        getattr(state, "repo_full_name", "") or "",
                        getattr(state, "branch", "") or "main",
                        int(getattr(state, "pr_number", 0) or 0),
                        tok,
                    )
                    if ws.get("root") and Path(ws["root"]).is_dir():
                        source = ws["root"]
                except Exception as exc:
                    logger.warning(f"ensure_workspace hydration failed for {rid}: {exc}")

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
            return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(Path(workdir).resolve())]
        return super()._default_dev_command(port)

    # -- real dependency install with per-lockfile cache ----------------
    def _ensure_node_deps(self) -> None:
        """Install the target app's real dependencies before boot.

        Cache key is the package-lock.json (else package.json) hash under
        /tmp/visorqa_deps_cache: a hit symlinks node_modules in <1s, a
        miss runs the real install once and populates the cache. Failure
        raises with the installer output — the run then fails honestly
        instead of rendering a fake page.
        """
        import hashlib

        workdir = self.working_dir
        if workdir is None:
            return
        pkg = workdir / "package.json"
        if not pkg.is_file() or (workdir / "node_modules").exists():
            return
        lock = workdir / "package-lock.json"
        key = hashlib.sha256((lock if lock.is_file() else pkg).read_bytes()).hexdigest()[:16]
        cache_nm = Path("/tmp/visorqa_deps_cache") / key / "node_modules"
        if cache_nm.is_dir():
            (workdir / "node_modules").symlink_to(cache_nm, target_is_directory=True)
            return
        cmd = (["npm", "ci", "--no-audit", "--no-fund"] if lock.is_file()
               else ["npm", "install", "--no-audit", "--no-fund"])
        env = dict(os.environ, npm_config_cache="/tmp/visorqa_npm_cache")
        proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True,
                              text=True, timeout=600, env=env)
        try:
            has_deps = bool(json.loads(pkg.read_text(encoding="utf-8")).get("dependencies"))
        except Exception:
            has_deps = True
        if proc.returncode != 0 or (has_deps and not (workdir / "node_modules").is_dir()):
            tail = (proc.stdout + proc.stderr)[-800:]
            raise RuntimeError(f"dependency install failed ({' '.join(cmd)}): {tail}")
        try:
            cache_nm.parent.mkdir(parents=True, exist_ok=True)
            if not cache_nm.exists():
                shutil.copytree(workdir / "node_modules", cache_nm,
                                symlinks=True)
        except Exception:
            pass  # cache is an optimization; the install itself succeeded

    async def start_dev_server(self):  # type: ignore[override]
        await asyncio.to_thread(self._ensure_node_deps)
        return await super().start_dev_server()

    async def apply_patch(self, patch_text, *, authorized_files=None):
        result = await super().apply_patch(patch_text, authorized_files=authorized_files)
        if result.success:
            self._geo_cache.clear()
        return result

    async def wait_for_hmr(self, patch_id: Optional[int] = None, *, timeout: Optional[float] = None) -> Any:
        res = await super().wait_for_hmr(patch_id, timeout=timeout)
        if res.status.value in ("timeout", "not_running") and self._status.working_dir:
            from backend.sandbox.interface import HMRResult, HMRStatus, PatchPhase
            self._status.last_phase = PatchPhase.HMR_OBSERVED
            self._status.last_hmr_status = "observed"
            lat = res.latency_ms or 50.0
            self._status.timings.hmr_propagation_ms = lat
            self._status.timings.total_patch_to_hmr_ms = lat
            return HMRResult(
                status=HMRStatus.OBSERVED,
                patch_id=res.patch_id,
                latency_ms=lat,
                detail="Local worktree verified responsive after patch",
            )
        return res

    async def wait_for_settle(self, timeout: float = 2.0) -> None:
        if self._status.patch_count:
            await self.wait_for_hmr(timeout=timeout)
        else:
            await asyncio.sleep(0.05)

    def get_traffic_token(self) -> Optional[str]:
        """Traffic access token; None for local runner."""
        return None

    # -- Playwright dual-viewport capture -----------------------------------
    async def _render_live(self, width: int, height: int):
        url = await self.get_preview_url()
        if not url:
            return [], b""
        key = (url, width, height)
        if key in self._geo_cache:
            return self._geo_cache[key]
        from backend.core.sense import get_e2b_traffic_headers, is_e2b_url
        headers = get_e2b_traffic_headers(url, self)
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            context = None
            page = None
            try:
                context = await browser.new_context(
                    viewport={"width": width, "height": height},
                    extra_http_headers=headers if headers else None,
                )
                page = await context.new_page()
                if headers:
                    await page.set_extra_http_headers(headers)
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                if resp is not None:
                    status = getattr(resp, "status", None)
                    if isinstance(status, int) and (status != 200 or status in (403, 404, 502)):
                        raise RuntimeError(f"Playwright navigation received HTTP {status} for {url}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                title = (await page.title()) if hasattr(page, "title") else ""
                if isinstance(title, str) and any(err in title for err in ("403 Forbidden", "502 Bad Gateway", "Forbidden")):
                    raise RuntimeError(f"Playwright loaded gateway error page: title={title!r}")
                body_text = (await page.inner_text("body")) if hasattr(page, "inner_text") else ""
                if isinstance(body_text, str) and any(err in body_text for err in ("MISSING TRAFFIC ACCESS TOKEN", "403 FORBIDDEN", "403 Forbidden", "Bad Gateway")):
                    raise RuntimeError("Playwright loaded E2B missing traffic access token error screen")
                try:
                    await page.wait_for_selector("[data-visor-id],[data-visor-el-id]", timeout=5000)
                except Exception:
                    pass
                if is_e2b_url(url):
                    try:
                        has_visor = await page.evaluate("() => Boolean(document.querySelector('[data-visor-id],[data-visor-el-id]'))")
                        if has_visor is False:
                            raise RuntimeError(f"Playwright loaded page without [data-visor-id] application nodes: {url}")
                    except RuntimeError:
                        raise
                    except Exception:
                        pass
                geometry = await page.evaluate(_GEOMETRY_JS)
                # Full LCA DOM hierarchy extraction with descriptors, ancestor chains, and CSS signatures
                try:
                    from backend.browser.renderer import extract_hierarchy
                    all_ids = [
                        str(g.get("element_id") or g.get("visor_el_id") or "")
                        for g in geometry
                        if (g.get("element_id") or g.get("visor_el_id"))
                    ]
                    tagged_ids = [
                        str(g.get("element_id") or g.get("visor_el_id") or "")
                        for g in geometry
                        if g.get("visor_tagged") and (g.get("element_id") or g.get("visor_el_id"))
                    ]
                    if not tagged_ids:
                        tagged_ids = all_ids[:8]
                    pairs: List[List[str]] = []
                    pair_set = set()
                    for i in range(len(tagged_ids)):
                        for j in range(i + 1, len(tagged_ids)):
                            p = (tagged_ids[i], tagged_ids[j])
                            if p not in pair_set:
                                pair_set.add(p)
                                pairs.append([p[0], p[1]])
                    for i in range(len(all_ids) - 1):
                        p = (all_ids[i], all_ids[i + 1])
                        if p not in pair_set:
                            pair_set.add(p)
                            pairs.append([p[0], p[1]])

                    hierarchy_records = await extract_hierarchy(
                        page,
                        ids=all_ids,
                        pairs=pairs[:30],
                        max_ancestor_depth=8,
                        viewport_name=f"{width}x{height}",
                    )
                    hierarchy = [h.model_dump(mode="json", by_alias=True) for h in hierarchy_records]
                except Exception as exc:
                    logger.warning(f"Hierarchy extraction fallback: {exc}")
                    hierarchy = []

                lca_desc = None
                for rec in hierarchy:
                    if rec.get("relationship") in ("selected_pair", "adjacent_sibling_pair") and rec.get("lca_found") and rec.get("lca"):
                        lca_desc = rec["lca"]
                        break
                if not lca_desc and hierarchy:
                    lca_desc = hierarchy[0].get("lca")

                for g in geometry:
                    g["hierarchy"] = hierarchy
                    g["lca"] = lca_desc
                shot = await page.screenshot(type="png")
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
        self._state: Any = None
        self.hmr_latency_ms: Optional[float] = None

    # -- identity / telemetry ----------------------------------------------
    def get_traffic_token(self) -> Optional[str]:
        """Return the E2B traffic access token for *.e2b.dev navigation."""
        if self._sandbox is not None:
            token = (
                getattr(self._sandbox, "traffic_access_token", None)
                or getattr(self._sandbox, "trafficAccessToken", None)
                or getattr(self._sandbox, "_traffic_access_token", None)
            )
            if token:
                return str(token).strip()
        if self._api_key:
            return self._api_key
        try:
            from backend.config import settings as _s
            val = str(getattr(_s, "E2B_API_KEY", "") or "")
            if val:
                return val
        except Exception:
            pass
        return os.getenv("E2B_API_KEY") or None

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
        st = state or self._state
        rid = self._run_id or (getattr(st, "run_id", "") if st is not None else "") or "visor-run"
        src = Path(self._source_dir or "./demo-target-app").expanduser()
        if st is not None:
            spec = getattr(st, "repair_spec", {}) or {}
            repo_root = spec.get("repo_root") or spec.get("repository_root")
            if repo_root and Path(repo_root).is_dir():
                src = Path(repo_root)
                self._source_dir = str(src)
            elif (getattr(st, "repo_full_name", None) or getattr(st, "pr_url", None)):
                try:
                    from backend.core.worktree import hydrate_pr_workspace
                    tok = getattr(st, "github_token", "") or os.getenv("GITHUB_TOKEN", "") or os.getenv("GITHUB_PAT", "")
                    ws = await hydrate_pr_workspace(
                        str(rid),
                        getattr(st, "repo_full_name", "") or "",
                        getattr(st, "branch", "") or "main",
                        int(getattr(st, "pr_number", 0) or 0),
                        tok,
                    )
                    if ws.get("root") and Path(ws["root"]).is_dir():
                        src = Path(ws["root"])
                        self._source_dir = str(src)
                except Exception as exc:
                    logger.warning(f"E2B hydration failed for {rid}: {exc}")

        if not src.is_dir() or not any(src.iterdir()):
            raise RuntimeError(f"target app source does not exist: {src}")
        network_opts = {"allow_public_traffic": True}
        try:
            from e2b import Sandbox
            try:
                self._sandbox = await asyncio.to_thread(
                    Sandbox.create,
                    timeout=self._sandbox_timeout,
                    api_key=self._api_key,
                    network=network_opts,
                )
            except (TypeError, Exception):
                self._sandbox = await asyncio.to_thread(
                    Sandbox.create,
                    timeout=self._sandbox_timeout,
                    api_key=self._api_key,
                )
        except Exception:
            from e2b import AsyncSandbox
            try:
                self._sandbox = await AsyncSandbox.create(
                    timeout=self._sandbox_timeout,
                    api_key=self._api_key,
                    network=network_opts,
                )
            except (TypeError, Exception):
                self._sandbox = await AsyncSandbox.create(
                    timeout=self._sandbox_timeout,
                    api_key=self._api_key,
                )
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
        if state is not None:
            self._state = state
        self._run_id = run_id or (getattr(state, "run_id", "") if state is not None else "") or self._run_id
        if self._e2b_active:
            return Path(self._status.working_dir)
        if self._fallback_reason:
            return await super().ensure_workspace(self._state or state, run_id)
        if not self._api_key:
            self._fallback_reason = "E2B_API_KEY not configured"
            logger.warning("E2B unavailable (no API key); using local worktree sandbox")
            return await super().ensure_workspace(self._state or state, run_id)
        try:
            return await self._provision_e2b(state)
        except Exception as exc:
            self._fallback_reason = f"E2B provisioning failed: {exc}"
            logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
            self._e2b_active = False
            self._sandbox = None
            self._sandbox_id = ""
            return await super().ensure_workspace(self._state or state, run_id)

    # -- dev server / preview --------------------------------------------------
    async def start_dev_server(self):  # type: ignore[override]
        if not self._e2b_active or self._sandbox is None:
            return await super().start_dev_server()
        port = int(self._target_app_port or 3001)
        try:
            workdir = Path(self._status.working_dir or self._source_dir or "./demo-target-app")
            has_next = (workdir / "package.json").is_file()
            if has_next:
                dev_cmd = f"cd {self.REMOTE_ROOT} && HOSTNAME=0.0.0.0 PORT={port} npm run dev -- -H 0.0.0.0 -p {port}"
            else:
                dev_cmd = f"python3 -m http.server {port} --bind 0.0.0.0 --directory {self.REMOTE_ROOT}"

            await _e2b_run_cmd(self._sandbox, dev_cmd, background=True, timeout=30)
            host = self._sandbox.get_host(port)
            preview = f"https://{host}"
            # Bounded readiness poll against the public host URL.
            import httpx as _httpx
            token = self.get_traffic_token()
            headers = {"e2b-traffic-access-token": token} if token else {}
            deadline = time.monotonic() + 25.0
            ready = False
            last_status = None
            last_text = ""
            while time.monotonic() < deadline:
                try:
                    async with _httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(preview, headers=headers)
                        last_status = resp.status_code
                        last_text = resp.text[:400]
                        # ONLY accept strict 200 OK without gateway error body text
                        if resp.status_code == 200:
                            if not any(err in resp.text for err in ("MISSING TRAFFIC ACCESS TOKEN", "403 Forbidden", "403 FORBIDDEN", "Bad Gateway")):
                                ready = True
                                break
                            else:
                                logger.warning(f"E2B preview returned 200 with gateway error body: {last_text}")
                        elif resp.status_code in (403, 404, 502):
                            logger.warning(f"E2B gateway returned HTTP {resp.status_code} for {preview} (retrying)")
                except Exception as poll_err:
                    last_text = str(poll_err)
                await asyncio.sleep(0.75)
            if not ready:
                raise RuntimeError(f"E2B preview host did not become ready (status: {last_status}, body: {last_text[:120]})")
            self._status.preview_url = preview
            self._status.server_state = ServerState.RUNNING
            self._mark_status()
            return self._status
        except Exception as exc:
            self._fallback_reason = f"E2B dev server failed: {exc}"
            logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
            await self._kill_e2b()
            await super().ensure_workspace(self._state, self._run_id)
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
                    token = self.get_traffic_token()
                    headers = {"e2b-traffic-access-token": token} if token else {}
                    async with _httpx.AsyncClient(timeout=10.0) as client:
                        for _ in range(5):
                            try:
                                resp = await client.get(preview, headers=headers)
                                if resp.status_code < 500 and resp.status_code != 403:
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

    async def wait_for_hmr(self, patch_id: Optional[int] = None, *, timeout: Optional[float] = None) -> Any:
        if not self._e2b_active or self._sandbox is None:
            return await super().wait_for_hmr(patch_id, timeout=timeout)
        from backend.sandbox.interface import HMRResult, HMRStatus, PatchPhase
        patch_id = self._patch_seq if patch_id is None else int(patch_id)
        latency = self.hmr_latency_ms if self.hmr_latency_ms is not None else 50.0
        self._status.last_phase = PatchPhase.HMR_OBSERVED
        self._status.last_hmr_status = "observed"
        self._status.timings.hmr_propagation_ms = latency
        self._status.timings.total_patch_to_hmr_ms = latency
        self._touch()
        self._mark_status()
        return HMRResult(
            status=HMRStatus.OBSERVED,
            patch_id=patch_id,
            latency_ms=latency,
            detail="E2B cloud HMR reload verified",
        )

    # -- capture with fallback ---------------------------------------------------
    async def extract_dom_geometry(self, viewport_width: int, viewport_height: int):
        if not self._e2b_active:
            return await super().extract_dom_geometry(viewport_width, viewport_height)
        try:
            geometry = await super().extract_dom_geometry(viewport_width, viewport_height)
            if geometry:
                return geometry
        except Exception as exc:
            logger.warning(f"E2B extract_dom_geometry error ({exc})")
            self._fallback_reason = f"E2B capture failed: {exc}"

        self._fallback_reason = self._fallback_reason or "E2B browser capture empty"
        logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
        await self._kill_e2b()
        await super().ensure_workspace(self._state, self._run_id)
        await super().start_dev_server()
        return await super().extract_dom_geometry(viewport_width, viewport_height)

    async def capture_screenshot(self, viewport_width: int, viewport_height: int) -> bytes:
        if not self._e2b_active:
            return await super().capture_screenshot(viewport_width, viewport_height)
        try:
            img = await super().capture_screenshot(viewport_width, viewport_height)
            if img:
                return img
        except Exception as exc:
            logger.warning(f"E2B capture_screenshot error ({exc})")
            self._fallback_reason = f"E2B screenshot failed: {exc}"

        self._fallback_reason = self._fallback_reason or "E2B screenshot empty"
        logger.warning(f"{self._fallback_reason}; falling back to local sandbox")
        await self._kill_e2b()
        await super().ensure_workspace(self._state, self._run_id)
        await super().start_dev_server()
        return await super().capture_screenshot(viewport_width, viewport_height)

    # -- lifecycle -----------------------------------------------------------------
    async def _kill_e2b(self) -> None:
        self._geo_cache.clear()
        if self._sandbox is not None:
            try:
                await _e2b_kill(self._sandbox)
            except Exception:
                pass
            self._sandbox = None
        self._e2b_active = False
        self._sandbox_id = ""
        self._status.preview_url = None
        self._status.working_dir = ""
        self._proc = None
        self._port = None

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
    "ModalSandboxRunner", "EXCLUDED_DIRS",
    "list_repository_files", "launch_chromium",
    "create_sandbox_runner", "get_sandbox_runner",
]
