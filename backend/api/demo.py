"""
Demo Journey endpoints for Hackathon Judges & Presenters.

Provides deterministic endpoints to:
1. Reset the demo repository (sayedibrahimQ/aether-hardware) to a clean slate (0 open PRs).
2. Push the buggy mobile branch and open a fresh Pull Request on GitHub.
3. Automatically dispatch the autonomous VisorQA self-healing agent run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.config import settings
from backend.api.auth import github_api
from backend.adapters.github_app import resolve_repo_token_and_author

logger = logging.getLogger("visorqa.demo")

router = APIRouter(prefix="/api/demo", tags=["Judge Demo"])

DEFAULT_REPO = "sayedibrahimQ/aether-hardware"
DEFAULT_BRANCH = "feat/sticky-mobile-offer-banner"
BUGGY_COMMIT_SHA = "faf2567028612e631e5522c6ea4ecd07c4af4056"
PR_TITLE = "feat(mobile): pin flash launch offer banner to bottom viewport for thumb reach"
PR_BODY = (
    "Automated mobile offer banner introduction.\n\n"
    "**Bug Details:** Sticky promo banner covers the checkout payment button on mobile viewports (375x812).\n"
    "Traditional DOM tests pass with false positives. Monitored autonomously by VisorQA."
)


def _get_github_pat() -> str:
    pat = (settings.GITHUB_PAT or "").strip()
    if not pat:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_PAT is not configured in backend settings"
        )
    return pat


@router.get("/status")
async def get_demo_status(repo: str = DEFAULT_REPO) -> Dict[str, Any]:
    """Check open PR status on the demo repository."""
    token = _get_github_pat()
    status, pulls = await github_api("GET", f"/repos/{repo}/pulls?state=open&per_page=20", token)
    if status != 200 or not isinstance(pulls, list):
        return {
            "repo": repo,
            "open_prs_count": 0,
            "open_prs": [],
            "error": f"Failed to fetch pulls from GitHub ({status})"
        }
    return {
        "repo": repo,
        "open_prs_count": len(pulls),
        "open_prs": [
            {
                "number": p.get("number"),
                "title": p.get("title"),
                "head_ref": (p.get("head") or {}).get("ref"),
                "html_url": p.get("html_url"),
            }
            for p in pulls
        ]
    }


@router.post("/reset-slate")
async def reset_demo_slate(repo: str = DEFAULT_REPO) -> Dict[str, Any]:
    """Clean slate: close all open PRs and reset branch to buggy commit."""
    token = _get_github_pat()
    status, pulls = await github_api("GET", f"/repos/{repo}/pulls?state=open&per_page=50", token)
    closed_count = 0
    if status == 200 and isinstance(pulls, list):
        for p in pulls:
            pr_num = p.get("number")
            if pr_num:
                st, _ = await github_api("PATCH", f"/repos/{repo}/pulls/{pr_num}", token, json={"state": "closed"})
                if st in (200, 204):
                    closed_count += 1

    # Reset branch ref to buggy commit
    st_ref, _ = await github_api(
        "PATCH",
        f"/repos/{repo}/git/refs/heads/{DEFAULT_BRANCH}",
        token,
        json={"sha": BUGGY_COMMIT_SHA, "force": True}
    )

    return {
        "ok": True,
        "repo": repo,
        "closed_prs_count": closed_count,
        "branch_reset": st_ref in (200, 201),
        "open_prs_count": 0,
        "message": f"Demo reset: {closed_count} PR(s) closed. Branch '{DEFAULT_BRANCH}' reset to clean buggy commit."
    }


class PushBuggyBranchRequest(BaseModel):
    repo: Optional[str] = DEFAULT_REPO
    branch: Optional[str] = DEFAULT_BRANCH


@router.post("/push-buggy-branch")
async def push_buggy_branch_and_open_pr(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: Optional[PushBuggyBranchRequest] = None,
) -> Dict[str, Any]:
    """Push buggy branch, open/reuse PR on GitHub, and trigger the autonomous pipeline."""
    repo = (payload.repo if payload and payload.repo else DEFAULT_REPO).strip()
    branch = (payload.branch if payload and payload.branch else DEFAULT_BRANCH).strip()
    token = _get_github_pat()

    owner = repo.split("/")[0] if "/" in repo else "sayedibrahimQ"

    # 1. Reset branch ref to the exact buggy commit (faf25670)
    st_ref, ref_data = await github_api(
        "PATCH",
        f"/repos/{repo}/git/refs/heads/{branch}",
        token,
        json={"sha": BUGGY_COMMIT_SHA, "force": True}
    )
    if st_ref not in (200, 201):
        # If patch failed, attempt creating the ref if missing
        logger.warning(f"Branch ref patch returned status {st_ref}: {ref_data}")

    # 2. Check for an existing open PR for this branch
    st_open, open_pulls = await github_api(
        "GET",
        f"/repos/{repo}/pulls?state=open&head={owner}:{branch}&per_page=1",
        token
    )
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None

    if st_open == 200 and isinstance(open_pulls, list) and len(open_pulls) > 0:
        pr_number = open_pulls[0].get("number")
        pr_url = open_pulls[0].get("html_url")
        # Clean any old bot comments on this existing PR
        st_comms, comms = await github_api("GET", f"/repos/{repo}/issues/{pr_number}/comments", token)
        if st_comms == 200 and isinstance(comms, list):
            for c in comms:
                cid = c.get("id")
                if cid:
                    await github_api("DELETE", f"/repos/{repo}/issues/comments/{cid}", token)
    else:
        # 3. Create fresh Pull Request
        pr_create_payload = {
            "title": PR_TITLE,
            "head": f"{owner}:{branch}",
            "base": "main",
            "body": PR_BODY,
        }
        st_create, pr_data = await github_api("POST", f"/repos/{repo}/pulls", token, json=pr_create_payload)
        if st_create in (200, 201) and isinstance(pr_data, dict):
            pr_number = pr_data.get("number")
            pr_url = pr_data.get("html_url")
        else:
            detail = pr_data.get("message") if isinstance(pr_data, dict) else str(pr_data)
            raise HTTPException(
                status_code=502,
                detail=f"GitHub PR creation failed ({st_create}): {detail}"
            )

    # 4. Check if an active run already exists or was started by the webhook for this PR
    run_id: Optional[str] = None
    try:
        from backend.db.repository import AsyncSessionLocal, RunRepository
        async with AsyncSessionLocal() as session:
            repo_db = RunRepository(session)
            active_run = await repo_db.get_active_run_for_pr(repo, pr_number or 0)
            if active_run:
                run_id = active_run.id
                logger.info(f"Demo push: found existing active run {run_id} for PR #{pr_number}")
    except Exception as exc:
        logger.warning(f"Demo active run probe failed: {exc}")

    # Only dispatch if no run is already active
    if not run_id:
        from backend.api.routes_ws import create_run, CreateRunRequest
        run_req = CreateRunRequest(
            repo_full_name=repo,
            pr_number=pr_number or 0,
            branch=branch,
            commit_sha=BUGGY_COMMIT_SHA,
            dispatch=True,
        )
        run_res = await create_run(run_req, background_tasks, request)
        run_id = run_res.get("id") if isinstance(run_res, dict) else None

    return {
        "ok": True,
        "repo": repo,
        "branch": branch,
        "pr_number": pr_number,
        "html_url": pr_url,
        "commit_sha": BUGGY_COMMIT_SHA,
        "run_id": run_id,
        "message": f"Buggy branch pushed! PR #{pr_number} open on GitHub. Autonomous pipeline dispatched."
    }
