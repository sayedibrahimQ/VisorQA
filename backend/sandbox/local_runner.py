"""LocalSandboxRunner: fully functional, zero credentials required.

One isolated working directory per PR/repair session under a sandbox
root. The Next.js dev server is a persistent subprocess (process group)
that survives patches; HMR is confirmed from dev-server log events
emitted *after* the patch's recorded log offset plus an HTTP health
probe -- never from a fixed sleep alone. A monotonically increasing
patch id prevents stale HMR events being attributed to a newer patch.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from backend.sandbox.interface import (
    HMRResult,
    HMRStatus,
    PatchPhase,
    PatchRejectedError,
    PatchResult,
    SandboxError,
    SandboxRunner,
    SandboxStatus,
    ServerState,
    TimingMetrics,
)
from backend.sandbox.patch_utils import commit_plan, validate_and_plan

_SUCCESS_MARKERS = ("compiled successfully", "✓ compiled", "compiled /", "compiled in", "hmr updated", "compiled client and server")
_FAILURE_MARKERS = ("failed to compile", "compile error", "module not found", "syntax error")
_SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_ok(port: int, timeout: float = 2.0) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/")
        resp = conn.getresponse()
        resp.read()
        return resp.status < 500
    except OSError:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


class LocalSandboxRunner(SandboxRunner):
    backend_name = "local"

    def __init__(
        self, *, base_dir: Optional[str] = None, hmr_timeout: float = 15.0,
        idle_timeout: float = 1800.0, startup_timeout: float = 60.0,
        cpu_limit: Optional[float] = None, memory_limit_mb: Optional[int] = None,
        cleanup_on_terminate: bool = True,
    ):
        self.base_dir = Path(base_dir or os.environ.get(
            "SANDBOX_LOCAL_ROOT", "/tmp/visorqa-sandboxes")).expanduser()
        self.hmr_timeout = float(hmr_timeout)
        self.idle_timeout = float(idle_timeout)
        self.startup_timeout = float(startup_timeout)
        self.cpu_limit = cpu_limit
        self.memory_limit_mb = memory_limit_mb
        self.cleanup_on_terminate = cleanup_on_terminate
        self._status = SandboxStatus(backend="local", cpu_limit=cpu_limit,
                                     memory_limit_mb=memory_limit_mb)
        self._proc: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._log_path: Optional[Path] = None
        self._log_offset = 0
        self._patch_seq = 0
        self._patch_started_at: dict[int, float] = {}
        self._authorized: Optional[List[str]] = None
        self._dev_command: Optional[List[str]] = None
        self._port: Optional[int] = None

    # -- workspace ---------------------------------------------------
    @property
    def working_dir(self) -> Optional[Path]:
        return Path(self._status.working_dir) if self._status.working_dir else None

    async def create_or_attach(self, session_id, *, source_dir=None, repo_url=None,
                               branch="main", commit_sha="", authorized_files=None,
                               dev_command=None, port=None) -> SandboxStatus:
        safe = _SESSION_RE.sub("-", str(session_id)).strip("-.") or "session"
        session_root = self.base_dir / safe
        workdir = session_root / "app"
        marker = session_root / ".visor-sandbox.json"
        self._authorized = list(authorized_files) if authorized_files is not None else None
        self._dev_command = list(dev_command) if dev_command else None
        self._port = int(port) if port else None
        if marker.is_file() and workdir.is_dir():
            meta = json.loads(marker.read_text(encoding="utf-8"))
            self._status.session_id = safe
            self._status.branch = meta.get("branch", branch)
            self._status.commit_sha = meta.get("commit_sha", commit_sha)
            self._status.working_dir = str(workdir)
            self._status.sandbox_id = f"local-{safe}"
            self._touch()
            return await self.get_status()
        session_root.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._prepare_checkout, workdir, source_dir, repo_url, branch, commit_sha)
        session_root.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(
            {"session_id": safe, "branch": branch, "commit_sha": commit_sha}),
            encoding="utf-8")
        self._status = SandboxStatus(
            backend="local", sandbox_id=f"local-{safe}", session_id=safe,
            branch=branch, commit_sha=commit_sha, working_dir=str(workdir),
            cpu_limit=self.cpu_limit, memory_limit_mb=self.memory_limit_mb)
        self._log_path = session_root / "dev-server.log"
        self._touch()
        return await self.get_status()

    def _prepare_checkout(self, workdir: Path, source_dir, repo_url, branch, commit_sha) -> None:
        if workdir.exists():
            shutil.rmtree(workdir)
        if repo_url:
            cmd = ["git", "clone", "--quiet", "--branch", str(branch), str(repo_url), str(workdir)]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        elif source_dir:
            src = Path(source_dir).expanduser().resolve()
            if not src.is_dir():
                raise SandboxError(f"source_dir does not exist: {src}")
            if (src / ".git").exists():
                subprocess.run(["git", "clone", "--quiet", "--local", str(src), str(workdir)],
                               check=True, capture_output=True, text=True, timeout=300)
                if branch:
                    subprocess.run(["git", "-C", str(workdir), "checkout", "--quiet", str(branch)],
                                   capture_output=True, text=True, timeout=60)
            else:
                def _ignore(_d, names):
                    return [n for n in names if n in {"node_modules", ".next", ".git"}]
                shutil.copytree(src, workdir, ignore=_ignore)
                nm = src / "node_modules"
                if nm.is_dir():  # share deps read/write-light via symlink
                    (workdir / "node_modules").symlink_to(nm, target_is_directory=True)
        else:
            workdir.mkdir(parents=True, exist_ok=True)  # empty sandbox
        if commit_sha and (workdir / ".git").exists():
            subprocess.run(["git", "-C", str(workdir), "checkout", "--quiet", str(commit_sha)],
                           check=True, capture_output=True, text=True, timeout=60)
            head = subprocess.run(["git", "-C", str(workdir), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=30)
            self._status.commit_sha = head.stdout.strip() or commit_sha

    # -- dev server ----------------------------------------------------
    def _default_dev_command(self, port: int) -> List[str]:
        workdir = self.working_dir
        pkg = workdir / "package.json" if workdir else None
        if pkg and pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            except Exception:
                scripts = {}
            if "dev" in scripts:
                return ["npm", "run", "dev", "--", "-p", str(port), "-H", "127.0.0.1"]
        return ["npx", "--yes", "next", "dev", "-p", str(port), "-H", "127.0.0.1"]

    async def start_dev_server(self) -> SandboxStatus:
        workdir = self.working_dir
        if workdir is None or not workdir.is_dir():
            raise SandboxError("create_or_attach must be called before start_dev_server")
        if self._proc is not None and self._proc.poll() is None:
            return await self.get_status()  # already persistent
        port = self._port or _free_port()
        self._port = port
        cmd = self._dev_command or self._default_dev_command(port)
        self._status.server_state = ServerState.STARTING
        self._log_path = self._log_path or (workdir.parent / "dev-server.log")
        log = open(self._log_path, "ab", buffering=0)  # noqa: SIM115 - owned by child
        env = dict(os.environ, PORT=str(port), HOSTNAME="127.0.0.1", NODE_ENV="development")
        env.pop("MODAL_TOKEN", None)
        preexec = None
        if self.memory_limit_mb or self.cpu_limit:
            def preexec():  # pragma: no cover - exercised with limits configured
                import resource
                if self.memory_limit_mb:
                    n = int(self.memory_limit_mb) * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (n, n))
                if self.cpu_limit:
                    secs = max(1, int(self.cpu_limit * 60))
                    resource.setrlimit(resource.RLIMIT_CPU, (secs, secs))
        self._proc = subprocess.Popen(
            cmd, cwd=str(workdir), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env, start_new_session=True,
            preexec_fn=preexec)
        self._status.server_pid = self._proc.pid
        self._status.preview_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._status.server_state = ServerState.CRASHED
                self._status.last_error = f"dev server exited with code {self._proc.returncode}"
                return await self.get_status()
            if _http_ok(port):
                self._status.server_state = ServerState.RUNNING
                self._touch()
                return await self.get_status()
            await asyncio.sleep(0.1)
        self._status.server_state = ServerState.CRASHED
        self._status.last_error = "dev server startup timeout"
        return await self.get_status()

    async def recover(self) -> SandboxStatus:
        """Restart after a crash; patches/files are preserved."""
        if self._proc is not None and self._proc.poll() is not None:
            self._proc = None
            self._status.server_state = ServerState.CRASHED
        return await self.start_dev_server()

    # -- patch + HMR ---------------------------------------------------
    async def apply_patch(self, patch_text, *, authorized_files=None) -> PatchResult:
        async with self._lock:  # serialize concurrent writes per sandbox
            workdir = self.working_dir
            if workdir is None:
                return PatchResult(success=False, error="sandbox not created")
            pid_before = self._proc.pid if self._proc and self._proc.poll() is None else None
            self._log_offset = self._log_path.stat().st_size if self._log_path and self._log_path.exists() else 0
            effective_auth = authorized_files if authorized_files is not None else self._authorized
            try:
                plan, timings = validate_and_plan(patch_text, workdir, effective_auth)
            except PatchRejectedError as exc:
                self._status.last_error = str(exc)
                return PatchResult(success=False, error=str(exc),
                                   server_pid=pid_before, timings=TimingMetrics())
            t0 = time.perf_counter()
            try:
                files = commit_plan(plan, timings)
            except PatchRejectedError as exc:
                self._status.last_error = str(exc)
                return PatchResult(success=False, error=str(exc), server_pid=pid_before, timings=timings)
            self._patch_seq += 1
            self._patch_started_at[self._patch_seq] = t0
            self._status.patch_count = self._patch_seq
            self._status.last_phase = PatchPhase.PATCH_APPLIED
            self._status.timings = timings
            self._status.last_error = None
            self._touch()
            return PatchResult(success=True, patch_id=self._patch_seq, files_changed=files,
                               phase=PatchPhase.PATCH_APPLIED, timings=timings,
                               server_restarted=False, server_pid=pid_before)

    async def wait_for_hmr(self, patch_id=None, *, timeout=None) -> HMRResult:
        patch_id = self._patch_seq if patch_id is None else int(patch_id)
        if patch_id != self._patch_seq:
            return HMRResult(status=HMRStatus.STALE, patch_id=patch_id,
                             detail="superseded by a newer patch; event not attributed")
        if self._proc is None or self._status.server_state in (ServerState.NOT_STARTED, ServerState.STOPPED):
            return HMRResult(status=HMRStatus.NOT_RUNNING, patch_id=patch_id,
                             detail="dev server not running")
        deadline = time.monotonic() + (self.hmr_timeout if timeout is None else float(timeout))
        started = self._patch_started_at.get(patch_id, time.perf_counter())
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._status.server_state = ServerState.CRASHED
                self._status.last_error = f"dev server exited with code {self._proc.returncode}"
                return HMRResult(status=HMRStatus.COMPILE_FAILED, patch_id=patch_id,
                                 detail=self._status.last_error)
            text = ""
            if self._log_path and self._log_path.exists():
                with open(self._log_path, "rb") as fh:
                    fh.seek(self._log_offset)
                    text = fh.read().decode("utf-8", errors="replace").lower()
            if any(m in text for m in _FAILURE_MARKERS):
                latency = (time.perf_counter() - started) * 1000.0
                self._status.last_phase = PatchPhase.PATCH_APPLIED
                return HMRResult(status=HMRStatus.COMPILE_FAILED, patch_id=patch_id,
                                 latency_ms=latency, detail="compiler reported failure")
            if any(m in text for m in _SUCCESS_MARKERS) and self._port and _http_ok(self._port):
                latency = (time.perf_counter() - started) * 1000.0
                self._status.last_phase = PatchPhase.HMR_OBSERVED
                self._status.timings.hmr_propagation_ms = latency
                self._status.timings.total_patch_to_hmr_ms = latency
                self._touch()
                return HMRResult(status=HMRStatus.OBSERVED, patch_id=patch_id,
                                 latency_ms=latency, detail="compiler/HMR event after patch offset")
            await asyncio.sleep(0.02)  # event poll interval, not the detection strategy
        return HMRResult(status=HMRStatus.TIMEOUT, patch_id=patch_id,
                         latency_ms=(time.perf_counter() - started) * 1000.0,
                         detail=f"no HMR event within {timeout or self.hmr_timeout}s")

    # -- status / lifecycle ---------------------------------------------
    def _touch(self) -> None:
        self._status.last_activity_at = time.time()

    async def get_status(self) -> SandboxStatus:
        if self._proc is not None:
            if self._proc.poll() is None:
                if self._status.server_state not in (ServerState.STARTING,):
                    self._status.server_state = ServerState.RUNNING
            elif self._status.server_state == ServerState.RUNNING:
                self._status.server_state = ServerState.CRASHED
                self._status.last_error = f"dev server exited with code {self._proc.returncode}"
        return self._status

    async def get_preview_url(self) -> Optional[str]:
        status = await self.get_status()
        return status.preview_url if status.server_state == ServerState.RUNNING else status.preview_url

    async def terminate(self) -> None:
        if self._proc is not None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self._proc = None
        self._status.server_state = ServerState.STOPPED
        self._status.server_pid = None
        workdir = self.working_dir
        if self.cleanup_on_terminate and workdir is not None and workdir.parent.exists():
            await asyncio.to_thread(shutil.rmtree, workdir.parent, True)

    async def cleanup_expired(self) -> List[str]:
        """Remove idle session dirs under the sandbox root (not own live one)."""
        removed: List[str] = []
        if not self.base_dir.is_dir():
            return removed
        now = time.time()
        for child in self.base_dir.iterdir():
            marker = child / ".visor-sandbox.json"
            if not marker.is_file():
                continue
            if self.working_dir and child == self.working_dir.parent:
                continue
            if now - marker.stat().st_mtime > self.idle_timeout:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)
        return removed
