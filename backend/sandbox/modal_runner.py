"""ModalSandboxRunner: real Modal SDK adapter, credentials deferred.

The module imports cleanly with no Modal credentials and even with the
``modal`` package absent. Live calls are gated: selecting Modal without
credentials (or without the SDK) raises an actionable
``SandboxConfigError`` -- it never silently falls back to local.

Verified against modal 1.6.3 (inspected locally):
``App.lookup(name, create_if_missing=True)``,
``Image.debian_slim().apt_install(...).run_commands(...)``,
``Sandbox.create(*args, app=, image=, timeout=, idle_timeout=,
encrypted_ports=, cpu=, memory=, workdir=)``, ``Sandbox.exec(...)``,
``Sandbox.tunnels() -> {port: Tunnel(url=...)}``, ``Sandbox.terminate()``.

Live Modal execution is **pending credentials** and has not been run.
"""
from __future__ import annotations

import base64
import inspect
import time
from typing import Any, List, Optional

from backend.sandbox.interface import (
    HMRResult,
    HMRStatus,
    PatchPhase,
    PatchRejectedError,
    PatchResult,
    SandboxConfigError,
    SandboxRunner,
    SandboxStatus,
    ServerState,
)
from backend.sandbox.patch_utils import extract_patch_paths

_CONTAINER_WORKDIR = "/workspace/app"
_CONTAINER_LOG = "/tmp/visor-dev.log"


class ModalSandboxRunner(SandboxRunner):
    backend_name = "modal"

    def __init__(
        self, token: Optional[str] = None, *, token_id: Optional[str] = None,
        token_secret: Optional[str] = None, app_name: str = "visorqa-sandbox",
        node_version: str = "20", timeout_seconds: int = 1800,
        idle_timeout_seconds: int = 300, cpu_limit: Optional[float] = 2.0,
        memory_limit_mb: Optional[int] = 4096, hmr_timeout: float = 30.0,
        port: int = 3000, modal_module: Any = None,
    ):
        # Never import modal or read credentials at construction/import.
        self.token_id = token_id or ""
        self.token_secret = token_secret or ""
        self._legacy_token = token or ""
        self.app_name = app_name
        self.node_version = node_version
        self.timeout_seconds = timeout_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        self.cpu_limit = cpu_limit
        self.memory_limit_mb = memory_limit_mb
        self.hmr_timeout = float(hmr_timeout)
        self.port = int(port)
        self._modal_module = modal_module  # DI seam for credential-free tests
        self._sandbox: Any = None
        self._status = SandboxStatus(backend="modal", cpu_limit=cpu_limit,
                                     memory_limit_mb=memory_limit_mb)
        self._patch_seq = 0
        self._log_offset = 0
        self._patch_started_at: dict[int, float] = {}

    # -- credential / SDK gate -----------------------------------------
    def _load_modal(self) -> Any:
        if self._modal_module is not None:
            return self._modal_module
        try:
            import modal  # lazy: imports must work without the SDK/creds
        except ImportError as exc:
            raise SandboxConfigError(
                "SANDBOX_BACKEND=modal but the Modal SDK is not installed. "
                "Install it with: pip install 'modal>=1.0' (see backend/requirements.txt). "
                "No local fallback was performed.") from exc
        configured = bool(
            (self.token_id and self.token_secret) or self._legacy_token
            or _env_present("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
            or _env_present("MODAL_TOKEN_ID") or _env_present("MODAL_TOKEN"))
        if not configured:
            raise SandboxConfigError(
                "SANDBOX_BACKEND=modal but Modal credentials are missing. "
                "Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (create them at "
                "modal.com -> Settings -> API Tokens), or run `modal setup`. "
                "See .env.example. No local fallback was performed.")
        return modal

    # -- SDK helpers (tolerant of sync/async SDK objects) ---------------
    async def _exec(self, *args: str, timeout: int = 120) -> str:
        proc = self._sandbox.exec(*args, timeout=timeout)
        if inspect.isawaitable(proc):
            proc = await proc
        out = ""
        stream = getattr(proc, "stdout", None)
        if stream is not None:
            read = getattr(stream, "read", None)
            if callable(read):
                out = read()
                if inspect.isawaitable(out):
                    out = await out
            else:
                out = str(stream)
        wait = getattr(proc, "wait", None)
        if callable(wait):
            result = wait()
            if inspect.isawaitable(result):
                await result
        return out or ""

    def _build_image(self, modal: Any) -> Any:
        return (
            modal.Image.debian_slim()
            .apt_install("curl", "git", "ca-certificates")
            .run_commands(
                f"curl -fsSL https://deb.nodesource.com/setup_{self.node_version}.x | bash -",
                "apt-get install -y nodejs",
                "node --version && npm --version")
        )

    # -- contract ---------------------------------------------------------
    async def create_or_attach(self, session_id, *, source_dir=None, repo_url=None,
                               branch="main", commit_sha="", authorized_files=None,
                               dev_command=None, port=None) -> SandboxStatus:
        modal = self._load_modal()  # raises actionable config error first
        if self._sandbox is not None:
            return await self.get_status()
        app = modal.App.lookup(self.app_name, create_if_missing=True)
        if inspect.isawaitable(app):
            app = await app
        image = self._build_image(modal)
        create_kwargs = dict(app=app, image=image, timeout=self.timeout_seconds,
                             idle_timeout=self.idle_timeout_seconds,
                             encrypted_ports=[port or self.port],
                             workdir=_CONTAINER_WORKDIR)
        if self.cpu_limit:
            create_kwargs["cpu"] = self.cpu_limit
        if self.memory_limit_mb:
            create_kwargs["memory"] = self.memory_limit_mb
        sandbox = modal.Sandbox.create("sleep", "infinity", **create_kwargs)
        if inspect.isawaitable(sandbox):
            sandbox = await sandbox
        self._sandbox = sandbox
        self._status.sandbox_id = getattr(sandbox, "object_id", None) or f"modal-{session_id}"
        self._status.session_id = str(session_id)
        self._status.branch = branch
        self._status.commit_sha = commit_sha
        self._status.working_dir = _CONTAINER_WORKDIR
        if repo_url:
            await self._exec("git", "clone", "--branch", str(branch), str(repo_url), _CONTAINER_WORKDIR)
            if commit_sha:
                await self._exec("git", "-C", _CONTAINER_WORKDIR, "checkout", str(commit_sha))
            await self._exec("bash", "-lc", f"cd {_CONTAINER_WORKDIR} && npm ci --no-audit --no-fund || npm install --no-audit --no-fund")
        self._status.server_state = ServerState.NOT_STARTED
        return await self.get_status()

    async def start_dev_server(self) -> SandboxStatus:
        if self._sandbox is None:
            raise SandboxConfigError("create_or_attach must succeed before start_dev_server")
        cmd = (f"cd {_CONTAINER_WORKDIR} && nohup npm run dev -- -p {self.port} "
               f"-H 0.0.0.0 > {_CONTAINER_LOG} 2>&1 & echo started")
        await self._exec("bash", "-lc", cmd)
        self._status.server_state = ServerState.RUNNING
        url = await self.get_preview_url()
        self._status.preview_url = url
        return await self.get_status()

    async def apply_patch(self, patch_text, *, authorized_files=None) -> PatchResult:
        if self._sandbox is None:
            return PatchResult(success=False, error="sandbox not created")
        # Validate locally first (same strict rules; no FS writes on reject).
        try:
            _validate_syntax_only(patch_text, authorized_files)
        except PatchRejectedError as exc:
            return PatchResult(success=False, error=str(exc))
        files = extract_patch_paths(patch_text)
        encoded = base64.b64encode(patch_text.encode()).decode()
        apply_cmd = (
            f"cd {_CONTAINER_WORKDIR} && printf %s {encoded} | base64 -d > /tmp/visor.patch && "
            "cp -a . /tmp/visor-backup-check 2>/dev/null; "
            "git apply --check /tmp/visor.patch && git apply /tmp/visor.patch && echo APPLIED")
        started = time.perf_counter()
        try:
            out = await self._exec("bash", "-lc", apply_cmd)
        except Exception as exc:  # container/transport failure: reported, not hidden
            return PatchResult(success=False, error=f"modal exec failed: {exc}")
        if "APPLIED" not in out:
            return PatchResult(success=False, error="git apply failed inside Modal sandbox (stale or invalid patch)")
        self._patch_seq += 1
        self._patch_started_at[self._patch_seq] = started
        self._status.patch_count = self._patch_seq
        self._status.last_phase = PatchPhase.PATCH_APPLIED
        from backend.sandbox.interface import TimingMetrics
        timings = TimingMetrics(patch_apply_ms=(time.perf_counter() - started) * 1000.0)
        self._status.timings = timings
        return PatchResult(success=True, patch_id=self._patch_seq, files_changed=files,
                           phase=PatchPhase.PATCH_APPLIED, timings=timings)

    async def wait_for_hmr(self, patch_id=None, *, timeout=None) -> HMRResult:
        patch_id = self._patch_seq if patch_id is None else int(patch_id)
        if patch_id != self._patch_seq:
            return HMRResult(status=HMRStatus.STALE, patch_id=patch_id,
                             detail="superseded by a newer patch")
        if self._sandbox is None or self._status.server_state != ServerState.RUNNING:
            return HMRResult(status=HMRStatus.NOT_RUNNING, patch_id=patch_id)
        import asyncio
        deadline = time.monotonic() + (self.hmr_timeout if timeout is None else float(timeout))
        started = self._patch_started_at.get(patch_id, time.perf_counter())
        while time.monotonic() < deadline:
            log = await self._exec("bash", "-lc", f"tail -c 20000 {_CONTAINER_LOG} 2>/dev/null || true")
            low = log.lower()
            if "failed to compile" in low or "compile error" in low:
                return HMRResult(status=HMRStatus.COMPILE_FAILED, patch_id=patch_id,
                                 latency_ms=(time.perf_counter() - started) * 1000.0)
            if "compiled" in low:
                latency = (time.perf_counter() - started) * 1000.0
                self._status.last_phase = PatchPhase.HMR_OBSERVED
                self._status.timings.hmr_propagation_ms = latency
                self._status.timings.total_patch_to_hmr_ms = latency
                return HMRResult(status=HMRStatus.OBSERVED, patch_id=patch_id, latency_ms=latency)
            await asyncio.sleep(0.1)
        return HMRResult(status=HMRStatus.TIMEOUT, patch_id=patch_id,
                         latency_ms=(time.perf_counter() - started) * 1000.0)

    async def get_status(self) -> SandboxStatus:
        if self._sandbox is not None and self._status.server_state == ServerState.RUNNING:
            poll = getattr(self._sandbox, "poll", None)
            if callable(poll) and poll() is not None:
                self._status.server_state = ServerState.CRASHED
                self._status.last_error = "modal sandbox terminated unexpectedly"
        return self._status

    async def get_preview_url(self) -> Optional[str]:
        if self._sandbox is None:
            return None
        tunnels_fn = getattr(self._sandbox, "tunnels", None)
        if not callable(tunnels_fn):
            return self._status.preview_url
        tunnels = tunnels_fn()
        if inspect.isawaitable(tunnels):
            tunnels = await tunnels
        entry = (tunnels or {}).get(self.port) or next(iter((tunnels or {}).values()), None)
        url = getattr(entry, "url", None) if entry is not None else None
        if url:
            self._status.preview_url = url
        return url or self._status.preview_url

    async def terminate(self) -> None:
        if self._sandbox is not None:
            result = self._sandbox.terminate()
            if inspect.isawaitable(result):
                await result
            self._sandbox = None
        self._status.server_state = ServerState.STOPPED


def _env_present(*names: str) -> bool:
    import os
    return all(os.environ.get(n) for n in names) if len(names) > 1 else bool(os.environ.get(names[0]))


def _validate_syntax_only(patch_text: str, authorized_files) -> None:
    from backend.core.patch import normalize_diff, parse_unified_diff, check_patch_policy, PatchValidationError
    from backend.core.triage import normalize_path, is_protected_path
    try:
        normalized = normalize_diff(patch_text)
        parsed = parse_unified_diff(normalized)
        check_patch_policy(normalized)
    except PatchValidationError as exc:
        raise PatchRejectedError(str(exc)) from exc
    authorized = None
    if authorized_files is not None:
        authorized = {n for n in (normalize_path(p) for p in authorized_files) if n}
    for patch in parsed:
        rel = normalize_path(patch.path)
        if rel is None:
            raise PatchRejectedError(f"patch path is malformed or traverses: {patch.path!r}")
        if is_protected_path(rel):
            raise PatchRejectedError(f"patch targets protected shared UI (BR-2): {rel}")
        if authorized is not None and rel not in authorized:
            raise PatchRejectedError(f"patch file not authorized for this sandbox: {rel}")
