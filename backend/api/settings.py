"""Watched-repository settings API (Task 1): /api/settings/watched-repo.

GET returns the persisted singleton record (or null). POST validates the
repository against GitHub, upserts the singleton record, and verifies
(or, when WEBHOOK_PUBLIC_URL is set, auto-registers) the pull_request
webhook. webhook_active is only true when GitHub confirms a matching
hook — it is never assumed.

Token resolution mirrors GET /api/github/repos and
GET /api/github/repos/{owner}/{repo}/pulls: the caller's session OAuth
token first, then GITHUB_PAT, then the GitHub App installation token.
A 404 from one credential (common for private repos visible to the PAT
but not the OAuth user) falls through to the next credential, and a
repo already present in an accessible GET /user/repos listing counts
as validated. Webhook verify/registration is best-effort: its failure
never blocks saving the watched repository.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import app_installation_token, current_session, github_api, resolve_github_token
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


async def _candidate_tokens(request: Request) -> List[Tuple[str, str]]:
    """Ordered, de-duplicated (token, auth_mode) candidates.

    Priority: session OAuth token -> GITHUB_PAT -> GitHub App
    installation token — the same credentials that make
    GET /api/github/repos and the repo pulls endpoint succeed.
    """
    candidates: List[Tuple[str, str]] = []

    def _add(token: Optional[str], mode: str) -> None:
        tok = (token or "").strip()
        if tok and all(tok != existing for existing, _ in candidates):
            candidates.append((tok, mode))

    session = current_session(request) if request is not None else None
    if session:
        _add(session.get("token"), str(session.get("auth_mode") or "oauth"))
    else:
        # Fall back to the shared resolver (also covers test doubles and
        # any future session store) before the env/App credentials.
        try:
            resolved = await resolve_github_token(request)
        except Exception:
            resolved = None
        if resolved:
            _add(resolved[0], resolved[1])
    _add(settings.GITHUB_PAT, "pat")
    try:
        _add(await app_installation_token(), "github_app")
    except Exception:
        pass
    return candidates


async def _repo_listing_entry(token: str, repo_full_name: str) -> Optional[Dict[str, Any]]:
    """Repo entry from the token's accessible listing, or None.

    Mirrors GET /api/github/repos: /user/repos for user/PAT tokens and
    /installation/repositories for GitHub App installation tokens.
    """
    wanted = repo_full_name.lower()
    for path in ("/user/repos?per_page=100&affiliation=owner,collaborator,organization_member",
                 "/installation/repositories"):
        try:
            status, body = await github_api("GET", path, token)
        except Exception:
            continue
        if status != 200:
            continue
        rows: List[Any] = []
        if isinstance(body, list):
            rows = body
        elif isinstance(body, dict) and isinstance(body.get("repositories"), list):
            rows = body["repositories"]
        for row in rows:
            if isinstance(row, dict) and str(row.get("full_name") or "").lower() == wanted:
                return row
    return None


async def _validate_repo(
    repo_full_name: str, candidates: List[Tuple[str, str]],
) -> Tuple[Optional[str], str, Optional[int]]:
    """(winning_token, default_branch, last_status) across all candidates."""
    last_status: Optional[int] = None
    for token, _mode in candidates:
        try:
            status, body = await github_api("GET", f"/repos/{repo_full_name}", token)
        except Exception:
            continue
        last_status = status
        if status == 200 and isinstance(body, dict):
            return token, str(body.get("default_branch") or "main"), status
    # Direct lookup failed for every credential (e.g. OAuth 404 on a
    # private repo): a repo already listed by GET /api/github/repos for
    # any candidate still counts as validated.
    for token, _mode in candidates:
        entry = await _repo_listing_entry(token, repo_full_name)
        if entry is not None:
            return token, str(entry.get("default_branch") or "main"), 200
    return None, "main", last_status


async def _verify_or_register_webhook(repo_full_name: str, token: str) -> Dict[str, Any]:
    """Confirm a VisorQA pull_request hook exists; register if possible.

    Best-effort by contract: every failure is reported in the result,
    never raised, so it cannot block saving the watched repository.
    """
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
    candidates = await _candidate_tokens(request)
    if candidates:
        token, default_branch, last_status = await _validate_repo(repo_full_name, candidates)
        if token is None:
            raise HTTPException(
                status_code=422,
                detail=f"repository '{repo_full_name}' is not accessible via GitHub ({last_status})")
        try:
            webhook = await _verify_or_register_webhook(repo_full_name, token)
        except Exception as exc:  # webhook setup must never block saving
            webhook = {"registered": False, "webhook_active": False,
                       "reason": f"hook verification failed: {exc}"}

    record = save_watched_repository(
        repo_full_name,
        default_branch=default_branch,
        installation_id=payload.installation_id,
        webhook_active=bool(webhook.get("webhook_active")),
        auto_heal_enabled=bool(payload.auto_heal_enabled),
    )
    return {"watched_repo": record, "webhook": webhook}
