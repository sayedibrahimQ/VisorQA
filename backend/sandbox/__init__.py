"""Dual sandbox infrastructure: Local (working now) + Modal (credential-ready)."""
from backend.sandbox.interface import (
    HMRResult,
    HMRStatus,
    PatchPhase,
    PatchRejectedError,
    PatchResult,
    SandboxConfigError,
    SandboxError,
    SandboxRunner,
    SandboxStatus,
    ServerState,
    TimingMetrics,
)
from backend.sandbox.local_runner import LocalSandboxRunner
from backend.sandbox.modal_runner import ModalSandboxRunner
from backend.sandbox.factory import create_sandbox_runner, get_sandbox_runner

__all__ = [
    "SandboxRunner", "LocalSandboxRunner", "ModalSandboxRunner",
    "create_sandbox_runner", "get_sandbox_runner",
    "SandboxStatus", "SandboxError", "SandboxConfigError", "PatchRejectedError",
    "PatchResult", "HMRResult", "HMRStatus", "PatchPhase", "ServerState",
    "TimingMetrics",
]
