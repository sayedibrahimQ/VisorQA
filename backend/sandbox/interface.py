"""Shared SandboxRunner contract for VisorQA (Local + Modal backends).

Both backends implement exactly this interface. The orchestrator only
ever talks to ``SandboxRunner``; backend-specific APIs (subprocess,
Modal SDK) never leak past the adapters.

Phases are deliberately distinct (never collapsed):
``PATCH_APPLIED`` -> ``COMPILATION_SUCCEEDED`` -> ``HMR_OBSERVED`` ->
``VISUAL_VERIFIED``. Only Node 5 may produce ``VISUAL_VERIFIED``;
runners report up to ``HMR_OBSERVED``.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SandboxError(RuntimeError):
    """Base sandbox failure."""


class SandboxConfigError(SandboxError):
    """Missing/invalid backend configuration (actionable, no fallback)."""


class PatchRejectedError(SandboxError):
    """Patch failed validation/authorization/stale checks; FS untouched."""


class ServerState(str, Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    CRASHED = "crashed"
    STOPPED = "stopped"


class PatchPhase(str, Enum):
    NONE = "none"
    PATCH_APPLIED = "patch_applied"
    COMPILATION_SUCCEEDED = "compilation_succeeded"
    HMR_OBSERVED = "hmr_observed"
    VISUAL_VERIFIED = "visual_verified"  # Node 5 only; runners never emit


class HMRStatus(str, Enum):
    OBSERVED = "observed"
    TIMEOUT = "timeout"
    COMPILE_FAILED = "compile_failed"
    NOT_RUNNING = "not_running"
    STALE = "stale"


@dataclass
class TimingMetrics:
    patch_validation_ms: Optional[float] = None
    patch_apply_ms: Optional[float] = None
    hmr_propagation_ms: Optional[float] = None
    total_patch_to_hmr_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


@dataclass
class HMRResult:
    status: HMRStatus
    patch_id: int = 0
    latency_ms: Optional[float] = None
    detail: str = ""

    @property
    def observed(self) -> bool:
        return self.status == HMRStatus.OBSERVED


@dataclass
class PatchResult:
    success: bool
    patch_id: int = 0
    files_changed: List[str] = field(default_factory=list)
    phase: PatchPhase = PatchPhase.NONE
    timings: TimingMetrics = field(default_factory=TimingMetrics)
    hmr: Optional[HMRResult] = None
    error: Optional[str] = None
    server_restarted: bool = False
    server_pid: Optional[int] = None


@dataclass
class SandboxStatus:
    backend: str = ""
    sandbox_id: Optional[str] = None
    session_id: str = ""
    branch: str = "main"
    commit_sha: str = ""
    working_dir: str = ""
    server_state: ServerState = ServerState.NOT_STARTED
    preview_url: Optional[str] = None
    server_pid: Optional[int] = None
    patch_count: int = 0
    last_phase: PatchPhase = PatchPhase.NONE
    last_error: Optional[str] = None
    timings: TimingMetrics = field(default_factory=TimingMetrics)
    cpu_limit: Optional[float] = None
    memory_limit_mb: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.__dict__)
        data["server_state"] = self.server_state.value
        data["last_phase"] = self.last_phase.value
        data["timings"] = self.timings.to_dict()
        return data


class SandboxRunner(ABC):
    """Interchangeable persistent-Next.js sandbox contract."""

    backend_name: str = "abstract"

    @abstractmethod
    async def create_or_attach(
        self, session_id: str, *, source_dir: Optional[str] = None,
        repo_url: Optional[str] = None, branch: str = "main",
        commit_sha: str = "", authorized_files: Optional[List[str]] = None,
        dev_command: Optional[List[str]] = None,
        port: Optional[int] = None,
    ) -> SandboxStatus:
        """Create the isolated per-session workspace, or attach to it."""

    @abstractmethod
    async def start_dev_server(self) -> SandboxStatus:
        """Start (or restart a crashed) persistent dev server."""

    @abstractmethod
    async def apply_patch(
        self, patch_text: str, *, authorized_files: Optional[List[str]] = None,
    ) -> PatchResult:
        """Validate + apply a Unified Diff in place; server stays alive."""

    @abstractmethod
    async def wait_for_hmr(
        self, patch_id: Optional[int] = None, *, timeout: Optional[float] = None,
    ) -> HMRResult:
        """Wait for the compiler/HMR event for ``patch_id`` (stale-safe)."""

    @abstractmethod
    async def get_status(self) -> SandboxStatus:
        """Current health/state snapshot."""

    @abstractmethod
    async def get_preview_url(self) -> Optional[str]:
        """Browser-accessible preview URL, when the server is running."""

    @abstractmethod
    async def terminate(self) -> None:
        """Stop the server and release the sandbox."""

    # -- Legacy SandboxRunnerStrategy compatibility (SENSE node) -----
    async def boot_branch(self, repo_name: str, branch: str) -> str:
        status = await self.create_or_attach(
            session_id=f"{repo_name}-{branch}".replace("/", "-"), branch=branch)
        await self.start_dev_server()
        return status.preview_url or (await self.get_preview_url()) or ""

    async def extract_dom_geometry(self, viewport_width: int, viewport_height: int) -> List[Dict[str, Any]]:
        return []  # DOM extraction stays with backend.browser.renderer

    async def capture_screenshot(self, viewport_width: int, viewport_height: int) -> bytes:
        return b""

    async def apply_hmr_patch(self, file_path: str, patch_content: str) -> bool:
        return False  # superseded by apply_patch(unified_diff)

    async def teardown(self) -> None:
        await self.terminate()
