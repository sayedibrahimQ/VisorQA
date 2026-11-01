"""Watched-repository settings API (Task 1): /api/settings/watched-repo.

GET returns the persisted singleton record (or null). POST validates the
repository against GitHub with the caller's authenticated token, upserts
the singleton record, and verifies (or, when WEBHOOK_PUBLIC_URL is set,
auto-registers) the pull_request webhook. webhook_active is only true
when GitHub confirms a matching hook — it is never assumed.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import github_api, resolve_github_token
from backend.config import settings
from backend.db.models import get_watched_repository, save_watched_repository

router = APIRouter(prefix="/api/settings", tags=["Settings"])

_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class WatchedRepoRequest(BaseModel):
    repo_full_name: str
    auto_heal_enabled: bool = True
    installation_id: Optional[int] = None


@router.get("/watched-repo")
async def get_watched_repo() -> Any:
    """Currently persisted watched repository, or null if not selected."""
    return get_watched_repository()


async def _verify_or_register_webhook(repo_full_name: str, token: str) -> Dict[str, Any]:
    """Confirm a VisorQA pull_request hook exists; register if possible."""
    owner_repo = repo_full_name
    try:
        status, hooks = await github_api(
            "GET", f"/repos/{owner_repo}/hooks?per_page=100", token)
        if status == 200 and isinstance(hooks, list):
            for hook in hooks:
                url = str(((hook or {}).get("config") or {}).get("url") or "")
                if url.rstrip("/").endswith("/api/webhooks/github"):
                    return {"registered": True, "webhook_active": True,
                            "reason": "existing hook found"}
    except Exception:
        pass
    public = (settings.WEBHOOK_PUBLIC_URL or "").strip().rstrip("/")
    if not public:
        return {"registered": False, "webhook_active": False,
                "reason": "no matching hook and WEBHOOK_PUBLIC_URL not configured"}
    config: Dict[str, Any] = {"url": f"{public}/api/webhooks/github",
                              "content_type": "json"}
    secret = (settings.GITHUB_WEBHOOK_SECRET or "").strip()
    if secret:
        config["secret"] = secret
    try:
        status, _body = await github_api(
            "POST", f"/repos/{owner_repo}/hooks", token,
            json={"name": "web", "active": True,
                  "events": ["pull_request"], "config": config})
        if status in (200, 201):
            return {"registered": True, "webhook_active": True,
                    "reason": "hook registered"}
        return {"registered": False, "webhook_active": False,
                "reason": f"GitHub hook registration returned {status}"}
    except Exception as exc:
        return {"registered": False, "webhook_active": False,
                "reason": f"hook registration failed: {exc}"}


@router.post("/watched-repo")
async def set_watched_repo(payload: WatchedRepoRequest, request: Request) -> Dict[str, Any]:
    repo_full_name = (payload.repo_full_name or "").strip()
    if not _REPO_RE.match(repo_full_name):
        raise HTTPException(status_code=422,
                            detail="repo_full_name must look like 'owner/repo'")

    default_branch = "main"
    webhook: Dict[str, Any] = {"registered": False, "webhook_active": False,
                               "reason": "no GitHub token available to verify"}
    resolved = await resolve_github_token(request)
    token = resolved[0] if resolved else ""
    if token:
        status, body = await github_api("GET", f"/repos/{repo_full_name}", token)
        if status != 200 or not isinstance(body, dict):
            raise HTTPException(
                status_code=422,
                detail=f"repository '{repo_full_name}' is not accessible via GitHub ({status})")
        default_branch = str(body.get("default_branch") or "main")
        webhook = await _verify_or_register_webhook(repo_full_name, token)

    record = save_watched_repository(
        repo_full_name,
        default_branch=default_branch,
        installation_id=payload.installation_id,
        webhook_active=bool(webhook.get("webhook_active")),
        auto_heal_enabled=bool(payload.auto_heal_enabled),
    )
    return {"watched_repo": record, "webhook": webhook}
