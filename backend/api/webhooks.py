"""
VisorQA Controller Layer - Autonomous GitHub Webhooks Listener (Jira)
POST /api/webhooks/github

- Raw-bytes HMAC SHA-256 signature verification (X-Hub-Signature-256)
- Event filtering: pull_request (opened, synchronize, reopened) and valid push events
- PostgreSQL AgentState / PRRun initialization with idempotency via X-GitHub-Delivery
- Live telemetry broadcast of SENSE_STARTED via ConnectionManager (ws_broadcast)
- Asynchronous agent dispatch (run_visor_agent) with strong task reference retention
- Strict performance budget: < 1.2s acceptance latency
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional, Set
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlmodel import select

from backend.config import settings
from backend.core.state import AgentState, FSMStep, RunStatus
from backend.db.repository import (
    AsyncSessionLocal,
    RepositoryRecord,
    RunRepository,
)

logger = logging.getLogger("visorqa.webhooks")

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# 5 MB maximum request body size
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

# Set holding strong references to running background agent tasks
_background_tasks: Set[asyncio.Task[Any]] = set()


def verify_github_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
    """Validates the GitHub Webhook HMAC SHA-256 signature (X-Hub-Signature-256).

    Rejects missing, malformed, or mismatched signatures using constant-time comparison.
    Never logs or leaks the secret.
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        logger.error("GITHUB_WEBHOOK_SECRET is not configured on the server")
        return False

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


async def _run_agent_lifecycle(state: AgentState) -> None:
    """Asynchronous background worker for run_visor_agent.

    Ensures lifecycle safety, fresh DB session isolation, and FSM failure handling.
    """
    try:
        from backend.api.routes_ws import ws_broadcast
        from backend.core.orchestrator import run_visor_agent

        logger.info(f"Dispatching autonomous QA agent for run {state.run_id} ({state.repo_full_name} PR #{state.pr_number})")
        final_state = await run_visor_agent(state, ws_broadcast=ws_broadcast)

        # Sync final FSM resolution state to PostgreSQL using a fresh session
        try:
            async with AsyncSessionLocal() as session:
                repo = RunRepository(session)
                await repo.sync_agent_state(final_state)
        except Exception as sync_err:
            logger.error(f"Failed to sync final agent state for run {state.run_id}: {sync_err}")

    except asyncio.CancelledError:
        logger.info(f"Agent execution for run {state.run_id} was cancelled")
    except Exception as exc:
        logger.exception(f"Unhandled exception in agent run {state.run_id}: {exc}")
        # Mark run as FAILED and notify observers
        try:
            state.status = RunStatus.FAILED
            from backend.api.routes_ws import ws_broadcast

            await ws_broadcast("RUN_HALTED", state)
            async with AsyncSessionLocal() as session:
                repo = RunRepository(session)
                await repo.sync_agent_state(state)
        except Exception as fail_err:
            logger.error(f"Failed to record failure status for run {state.run_id}: {fail_err}")


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def handle_github_webhook(
    request: Request,
    response: Response,
    x_hub_signature_256: Optional[str] = Header(default=None),
    x_github_event: Optional[str] = Header(default=None),
    x_github_delivery: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Autonomous GitHub Webhook Listener.

    Accepts pull_request and push webhooks within 1.2s, records initial state in PostgreSQL,
    broadcasts SENSE_STARTED to Mission Control, and dispatches run_visor_agent asynchronously.
    """
    t_start = time.perf_counter()

    # 1. Enforce payload size limit
    status_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_PAYLOAD_BYTES:
                raise HTTPException(
                    status_code=status_413,
                    detail=f"Webhook payload exceeds maximum limit of {MAX_PAYLOAD_BYTES} bytes",
                )
        except ValueError:
            pass

    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status_413,
            detail=f"Webhook payload exceeds maximum limit of {MAX_PAYLOAD_BYTES} bytes",
        )

    # 2. Strict HMAC SHA-256 signature verification
    t_sig_start = time.perf_counter()
    if not verify_github_signature(body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, missing, or malformed X-Hub-Signature-256 webhook signature",
        )
    t_sig_ms = (time.perf_counter() - t_sig_start) * 1000.0

    # 3. Validate GitHub event header & parse JSON
    if not x_github_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook payload",
        )

    delivery_id = x_github_delivery or str(uuid4())

    # 4. Filter events: only pull_request (opened, synchronize, reopened) and push
    if x_github_event == "pull_request":
        action = payload.get("action", "")
        if action not in {"opened", "synchronize", "reopened"}:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ignored",
                    "reason": f"Pull request action '{action}' is not configured for autonomous visual QA",
                    "delivery_id": delivery_id,
                },
            )

        pr_data = payload.get("pull_request") or {}
        repo_data = payload.get("repository") or {}
        repo_full_name = repo_data.get("full_name") or payload.get("repo_name", "unknown/repo")
        pr_number = pr_data.get("number") or payload.get("number", 0)
        branch = pr_data.get("head", {}).get("ref") or payload.get("branch", "main")
        commit_sha = pr_data.get("head", {}).get("sha") or payload.get("commit_sha", "HEAD")
        pr_url = pr_data.get("html_url") or f"https://github.com/{repo_full_name}/pull/{pr_number}"

    elif x_github_event == "push":
        # Ignore branch deletion push events
        if payload.get("deleted") is True or payload.get("after") == "0000000000000000000000000000000000000000":
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ignored",
                    "reason": "Branch deletion push event ignored",
                    "delivery_id": delivery_id,
                },
            )

        repo_data = payload.get("repository") or {}
        repo_full_name = repo_data.get("full_name") or payload.get("repo_name", "unknown/repo")
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else (ref or "main")
        commit_sha = payload.get("after") or payload.get("head_commit", {}).get("id", "HEAD")
        pr_number = 0
        pr_url = payload.get("compare") or repo_data.get("html_url", f"https://github.com/{repo_full_name}")
        action = "push"

    else:
        # Safely ignore all other event types (ping, issues, star, release, etc.)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ignored",
                "reason": f"GitHub event '{x_github_event}' is not monitored for visual regression QA",
                "delivery_id": delivery_id,
            },
        )

    # 5. Initialize & Persist in PostgreSQL (with delivery_id idempotency)
    t_db_start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            repo = RunRepository(session)

            # Idempotency check: repeated deliveries must not create duplicate runs
            existing_run = await repo.get_run_by_delivery_id(delivery_id)
            if existing_run:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status": "duplicate",
                        "message": f"Webhook delivery '{delivery_id}' was already processed",
                        "run_id": existing_run.id,
                        "delivery_id": delivery_id,
                    },
                )

            # Ensure RepositoryRecord exists or create one
            stmt = select(RepositoryRecord).where(RepositoryRecord.repo_full_name == repo_full_name)
            res = await session.execute(stmt)
            repository_record = res.scalars().first()
            if not repository_record:
                repository_record = RepositoryRecord(
                    repo_full_name=repo_full_name,
                    default_branch=branch,
                )
                session.add(repository_record)
                await session.flush()

            # Create master PRRun record
            run = await repo.create_run(
                repo_id=repository_record.id,
                repo_name=repo_full_name,
                pr_number=pr_number,
                branch=branch,
                commit_sha=commit_sha,
                github_delivery_id=delivery_id,
            )

    except Exception as db_exc:
        logger.error(f"Database error initializing run for delivery {delivery_id}: {db_exc}")
        # GitHub expects non-2xx to retry delivery
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist initial run state in database",
        )
    t_db_ms = (time.perf_counter() - t_db_start) * 1000.0

    # 6. Initialize AgentState domain model
    agent_state = AgentState(
        run_id=run.id,
        repo_name=repo_full_name,
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        branch=branch,
        commit_sha=commit_sha,
        pr_url=pr_url,
        status=RunStatus.RUNNING,
        current_step=FSMStep.SENSE,
    )

    # 7. Broadcast SENSE_STARTED over WebSocket ConnectionManager
    t_bc_start = time.perf_counter()
    from backend.api.routes_ws import ws_broadcast

    await ws_broadcast("SENSE_STARTED", agent_state)
    t_bc_ms = (time.perf_counter() - t_bc_start) * 1000.0

    # 8. Asynchronously dispatch run_visor_agent without blocking the HTTP request
    t_disp_start = time.perf_counter()
    task = asyncio.create_task(
        _run_agent_lifecycle(agent_state),
        name=f"visor-agent-{run.id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    t_disp_ms = (time.perf_counter() - t_disp_start) * 1000.0

    # 9. Compute total acceptance latency
    t_total_ms = (time.perf_counter() - t_start) * 1000.0

    response.headers["X-Response-Time-Ms"] = f"{t_total_ms:.2f}"
    response.headers["X-GitHub-Delivery"] = delivery_id
    response.headers["X-VisorQA-Run-ID"] = run.id

    return {
        "status": "accepted",
        "run_id": run.id,
        "delivery_id": delivery_id,
        "event": x_github_event,
        "action": action,
        "repo": repo_full_name,
        "pr_number": pr_number,
        "branch": branch,
        "commit_sha": commit_sha,
        "timing_ms": {
            "signature": round(t_sig_ms, 2),
            "db_persist": round(t_db_ms, 2),
            "broadcast": round(t_bc_ms, 2),
            "dispatch": round(t_disp_ms, 2),
            "total": round(t_total_ms, 2),
        },
    }
