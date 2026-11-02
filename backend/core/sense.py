"""Node 1 - SENSE: Dual-viewport rendering, SAM 3.1 masks, and DOM geometry.

Provides Playwright capture with E2B traffic access token header injection
for cloud sandboxes (*.e2b.dev) and seamless fallback to local worktree
runners on EC2.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger("visorqa.core.sense")

E2B_TRAFFIC_HEADER = "e2b-traffic-access-token"


def get_e2b_traffic_token(sandbox: Any = None) -> Optional[str]:
    """Retrieve E2B traffic access token from sandbox instance or environment.

    Checks:
    1. sandbox.get_traffic_token()
    2. sandbox._api_key
    3. os.environ["E2B_API_KEY"]
    4. settings.E2B_API_KEY
    """
    token: Optional[str] = None
    if sandbox is not None:
        fn = getattr(sandbox, "get_traffic_token", None)
        if callable(fn):
            try:
                token = fn()
            except Exception:
                token = None
        if not token:
            raw_key = getattr(sandbox, "_api_key", None)
            if raw_key:
                token = str(raw_key).strip()

    if not token:
        env_val = os.getenv("E2B_API_KEY", "").strip()
        if env_val:
            token = env_val

    if not token:
        try:
            cfg_val = str(getattr(settings, "E2B_API_KEY", "") or "").strip()
            if cfg_val:
                token = cfg_val
        except Exception:
            pass

    return token or None


def is_e2b_url(url: Optional[str]) -> bool:
    """Return True if ``url`` points to an E2B cloud sandbox (*.e2b.dev)."""
    if not url or not isinstance(url, str):
        return False
    clean = url.strip().lower()
    try:
        parsed = urlparse(clean)
        host = (parsed.hostname or "").lower()
        return host.endswith(".e2b.dev") or ".e2b.dev" in clean
    except Exception:
        return ".e2b.dev" in clean


def get_e2b_traffic_headers(url: Optional[str], sandbox: Any = None) -> Dict[str, str]:
    """Return HTTP headers required to traverse E2B traffic gateway.

    When navigating to an E2B URL (*.e2b.dev), returns
    ``{"e2b-traffic-access-token": <token>}`` so Playwright and HTTP clients
    bypass the E2B gateway 403 Forbidden check.
    For local or non-E2B URLs, returns an empty dict.
    """
    if not is_e2b_url(url):
        return {}
    token = get_e2b_traffic_token(sandbox)
    if not token:
        logger.warning(
            f"E2B URL detected ({url}) but no E2B_API_KEY or traffic token available; "
            "gateway may return 403 Forbidden"
        )
        return {}
    return {E2B_TRAFFIC_HEADER: token}


__all__ = [
    "E2B_TRAFFIC_HEADER",
    "get_e2b_traffic_token",
    "is_e2b_url",
    "get_e2b_traffic_headers",
]
