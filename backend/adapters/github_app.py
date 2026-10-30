"""VisorQA GitHub App Authentication Adapter (visorqa-bot[bot]).

Provides secure RS256 JWT generation, GitHub App installation token exchange,
in-memory token caching with expiration tracking, and safe secret handling.
Never leaks private keys or tokens in logs or exceptions.
"""
from __future__ import annotations

import asyncio
import logging
import stat
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import jwt

from backend.config import settings

logger = logging.getLogger("visorqa.github_app")


class GitHubAppError(RuntimeError):
    """Base error for GitHub App operations."""
    retryable = False


class GitHubAppConfigError(GitHubAppError):
    """Raised when GitHub App credentials or keys are missing or invalid."""
    pass


class GitHubAppAuthError(GitHubAppError):
    """Raised when GitHub rejects the JWT or installation token exchange."""
    pass


def mask_token(token: Optional[str]) -> str:
    """Safely mask access tokens for logging (e.g. 'ghs_a1b2...c3d4')."""
    if not token:
        return "<none>"
    if len(token) <= 8:
        return "***"
    prefix = token[:4]
    suffix = token[-4:]
    return f"{prefix}...{suffix} ({len(token)} chars)"


class GitHubAppAuth:
    """Secure GitHub App authenticator managing RS256 JWTs and installation tokens."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        default_installation_id: Optional[Any] = None,
    ):
        self.app_id = (settings.GITHUB_APP_ID if app_id is None else app_id).strip()
        self._private_key_inline = (settings.GITHUB_PRIVATE_KEY if private_key is None else private_key).strip()
        self._private_key_path = (settings.GITHUB_PRIVATE_KEY_PATH if private_key_path is None else private_key_path).strip()
        self.default_installation_id = settings.GITHUB_INSTALLATION_ID if default_installation_id is None else default_installation_id

        # Cache: installation_id -> (token_str, expires_at_timestamp)
        self._token_cache: Dict[int, Tuple[str, float]] = {}
        self._cache_lock = asyncio.Lock()

    def is_configured(self) -> bool:
        """Check if minimum GitHub App credentials (App ID + Private Key) exist."""
        if not self.app_id:
            return False
        return bool(self._private_key_inline or self._private_key_path)

    def resolve_private_key(self) -> str:
        """Safely load and return the RSA private key PEM string.

        Checks inline PEM first, then candidate paths on disk.
        Warns if file permissions are overly permissive.
        """
        if self._private_key_inline:
            return self._private_key_inline

        if not self._private_key_path:
            raise GitHubAppConfigError(
                "GitHub App private key is not configured. Set GITHUB_PRIVATE_KEY_PATH or GITHUB_PRIVATE_KEY."
            )

        # Candidate paths (support relative paths from repo root or backend dir)
        candidates = [
            Path(self._private_key_path),
            Path.cwd() / self._private_key_path,
            Path(__file__).resolve().parent.parent / self._private_key_path,
            Path(__file__).resolve().parent.parent / Path(self._private_key_path).name,
        ]

        found_path: Optional[Path] = None
        for cand in candidates:
            if cand.is_file():
                found_path = cand.resolve()
                break

        if not found_path:
            raise GitHubAppConfigError(
                f"GitHub App private key file not found. Checked: {self._private_key_path}"
            )

        # Security check: warn if key is world-readable on POSIX systems
        try:
            st = found_path.stat()
            if bool(st.st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
                logger.warning(
                    f"Security Warning: GitHub App private key at {found_path} is readable by others. "
                    f"Run `chmod 600 {found_path}` to restrict access."
                )
        except Exception:
            pass

        try:
            pem_content = found_path.read_text(encoding="utf-8").strip()
            if "BEGIN" not in pem_content:
                raise GitHubAppConfigError(f"Private key file at {found_path} does not look like a valid PEM file.")
            return pem_content
        except Exception as exc:
            if isinstance(exc, GitHubAppConfigError):
                raise
            raise GitHubAppConfigError(f"Failed to read private key file: {exc}") from exc

    def generate_jwt(self, app_id: Optional[str] = None, private_key_pem: Optional[str] = None) -> str:
        """Generate RS256 JWT valid for 9 minutes with 60-second clock skew tolerance."""
        resolved_app_id = (app_id or self.app_id).strip()
        if not resolved_app_id:
            raise GitHubAppConfigError("GITHUB_APP_ID is not configured.")

        pem_text = private_key_pem or self.resolve_private_key()

        now = int(time.time())
        payload = {
            "iat": now - 60,            # 60s clock drift buffer
            "exp": now + (9 * 60),      # Valid for 9 minutes (max allowed by GitHub is 10)
            "iss": resolved_app_id,
        }

        try:
            return jwt.encode(payload, pem_text, algorithm="RS256")
        except Exception as exc:
            raise GitHubAppConfigError(f"Failed to sign GitHub App JWT: {exc}") from exc

    async def get_installation_token(
        self,
        installation_id: Optional[Any] = None,
        *,
        app_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        force_refresh: bool = False,
    ) -> str:
        """Obtain an installation access token (cached with TTL until 5m before expiry)."""
        target_raw = installation_id or self.default_installation_id
        if not target_raw:
            raise GitHubAppConfigError(
                "GitHub App installation ID was not provided and GITHUB_INSTALLATION_ID is not set."
            )

        target_str = str(target_raw).strip()
        if not target_str.isdigit():
            if target_str.startswith("Iv1.") or target_str.startswith("Iv23") or len(target_str) == 20:
                raise GitHubAppConfigError(
                    f"Invalid GITHUB_INSTALLATION_ID '{target_str}': This looks like a GitHub App Client ID, "
                    f"not an Installation ID. To find your numeric Installation ID: in GitHub App settings, click 'Install App' "
                    f"in the left sidebar -> click the gear icon next to your account. The URL will be "
                    f"https://github.com/settings/installations/<NUMBER> — the number at the end (e.g. 12345678) is your installation ID."
                )
            raise GitHubAppConfigError(
                f"Invalid GITHUB_INSTALLATION_ID '{target_str}': Installation ID must be a numeric integer."
            )

        target_id = int(target_str)

        now = time.time()
        async with self._cache_lock:
            # Check cache if not forcing refresh
            if not force_refresh and target_id in self._token_cache:
                cached_token, expires_at = self._token_cache[target_id]
                # Keep token if valid for at least 5 more minutes
                if expires_at - now > 300:
                    return cached_token

            # Exchange JWT for token
            app_jwt = self.generate_jwt(app_id=app_id, private_key_pem=private_key_pem)
            headers = {
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            url = f"https://api.github.com/app/installations/{target_id}/access_tokens"

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(url, headers=headers)
                    if res.status_code == 401:
                        raise GitHubAppAuthError(
                            "GitHub rejected JWT: unauthorized (verify App ID and private key match)."
                        )
                    if res.status_code == 404:
                        raise GitHubAppAuthError(
                            f"GitHub installation {target_id} not found or App is not installed on target repo."
                        )
                    res.raise_for_status()
                    data = res.json()
            except httpx.HTTPStatusError as exc:
                raise GitHubAppAuthError(f"GitHub token exchange failed (HTTP {exc.response.status_code}): {exc}") from exc
            except Exception as exc:
                if isinstance(exc, (GitHubAppError, GitHubAppAuthError)):
                    raise
                raise GitHubAppAuthError(f"Network error during GitHub App token exchange: {exc}") from exc

            token = data.get("token")
            if not token:
                raise GitHubAppAuthError("GitHub did not return an access token in the response.")

            # Parse expires_at (defaults to 1 hour from now)
            expires_at_ts = now + 3600.0
            if "expires_at" in data:
                try:
                    # e.g. 2026-10-30T11:00:00Z
                    from datetime import datetime
                    exp_dt = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                    expires_at_ts = exp_dt.timestamp()
                except Exception:
                    pass

            self._token_cache[target_id] = (token, expires_at_ts)
            logger.info(
                f"Acquired new GitHub App installation token for installation {target_id} "
                f"(masked: {mask_token(token)})"
            )
            return token

    async def get_authenticated_client(self, installation_id: Optional[int] = None) -> Any:
        """Create a GitHubClient authenticated with the GitHub App installation token."""
        token = await self.get_installation_token(installation_id=installation_id)
        from backend.adapters.github_client import GitHubClient
        return GitHubClient(token=token)


# Global singleton instance
github_app_auth = GitHubAppAuth()
