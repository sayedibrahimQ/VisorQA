"""Backend selection via dependency injection (SANDBOX_PROVIDER/BACKEND).

Default is ``local`` (LocalWorktreeSandboxRunner, zero credentials).
``modal`` constructs the Modal adapter only when selected; a
missing-credential Modal selection raises at first live use.
``stub`` returns an offline runner that never spawns browsers/servers.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.sandbox.interface import SandboxConfigError, SandboxRunner


def _resolve_name(cfg: Any, backend: Optional[str]) -> str:
    if backend:
        return str(backend).strip().lower()
    provider = str(getattr(cfg, "SANDBOX_PROVIDER", "") or "").strip().lower()
    legacy = str(getattr(cfg, "SANDBOX_BACKEND", "") or "").strip().lower()
    # An explicit non-default value in either spelling wins.
    if legacy and legacy != "local":
        return legacy
    if provider:
        return provider
    # Auto: E2B cloud when a key is configured, else local.
    if str(getattr(cfg, "E2B_API_KEY", "") or "").strip():
        return "e2b"
    return legacy or "local"


def create_sandbox_runner(settings_obj: Any = None, backend: Optional[str] = None) -> SandboxRunner:
    from backend.config import settings as default_settings
    cfg = settings_obj or default_settings
    name = _resolve_name(cfg, backend)
    if name == "local":
        from backend.adapters.sandbox_runner import LocalWorktreeSandboxRunner
        return LocalWorktreeSandboxRunner(
            source_dir=str(getattr(cfg, "TARGET_APP_PATH", "./demo-target-app") or "./demo-target-app"),
            target_app_port=int(getattr(cfg, "TARGET_APP_PORT", 3001) or 3001),
            base_dir=getattr(cfg, "SANDBOX_LOCAL_ROOT", "") or None,
            hmr_timeout=float(getattr(cfg, "SANDBOX_HMR_TIMEOUT_SECONDS", 15.0)),
            idle_timeout=float(getattr(cfg, "SANDBOX_IDLE_TIMEOUT_SECONDS", 1800.0)),
            cpu_limit=getattr(cfg, "SANDBOX_CPU_LIMIT", None) or None,
            memory_limit_mb=getattr(cfg, "SANDBOX_MEMORY_LIMIT_MB", None) or None)
    if name == "e2b":
        from backend.adapters.sandbox_runner import E2BSandboxRunner
        return E2BSandboxRunner(
            source_dir=str(getattr(cfg, "TARGET_APP_PATH", "./demo-target-app") or "./demo-target-app"),
            api_key=str(getattr(cfg, "E2B_API_KEY", "") or "") or None,
            sandbox_timeout=int(getattr(cfg, "E2B_SANDBOX_TIMEOUT_SECONDS", 180) or 180),
            target_app_port=int(getattr(cfg, "TARGET_APP_PORT", 3001) or 3001),
            base_dir=getattr(cfg, "SANDBOX_LOCAL_ROOT", "") or None,
            hmr_timeout=float(getattr(cfg, "SANDBOX_HMR_TIMEOUT_SECONDS", 15.0)))
    if name == "stub":
        from backend.adapters.sandbox_runner import StubSandboxRunner
        return StubSandboxRunner(
            source_dir=str(getattr(cfg, "TARGET_APP_PATH", "./demo-target-app") or "./demo-target-app"),
            base_dir=getattr(cfg, "SANDBOX_LOCAL_ROOT", "") or None)
    if name == "modal":
        from backend.sandbox.modal_runner import ModalSandboxRunner
        return ModalSandboxRunner(
            token_id=getattr(cfg, "MODAL_TOKEN_ID", "") or None,
            token_secret=getattr(cfg, "MODAL_TOKEN_SECRET", "") or None,
            token=getattr(cfg, "MODAL_TOKEN", "") or None,
            app_name=getattr(cfg, "MODAL_APP_NAME", "visorqa-sandbox"),
            hmr_timeout=float(getattr(cfg, "SANDBOX_HMR_TIMEOUT_SECONDS", 15.0)),
            cpu_limit=getattr(cfg, "SANDBOX_CPU_LIMIT", None) or 2.0,
            memory_limit_mb=getattr(cfg, "SANDBOX_MEMORY_LIMIT_MB", None) or 4096)
    raise SandboxConfigError(
        f"Invalid SANDBOX_BACKEND={name!r}. Supported values: 'e2b', 'local', 'modal', 'stub'. "
        "Set SANDBOX_BACKEND=local for credential-free development.")


get_sandbox_runner = create_sandbox_runner
