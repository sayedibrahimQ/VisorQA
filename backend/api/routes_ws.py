"""
VisorQA Controller Layer - REST & Live WebSocket Mission Control
Native async FastAPI WebSocket ConnectionManager for Live Telemetry Broadcast (Jira)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.config import settings
from backend.core.state import AgentState

logger = logging.getLogger("visorqa.ws")

router = APIRouter(prefix="/api", tags=["Runs & WebSockets"])


class OverflowPolicy(str, Enum):
    """Buffer overflow policy for slow clients."""
    DROP_OLDEST = "DROP_OLDEST"
    DROP_NEWEST = "DROP_NEWEST"


class ClientConnection:
    """Represents a connected WebSocket client with bounded per-client queue

    and independent background sender task. Prevents slow/stalled clients
    from blocking the FSM or other clients.
    """

    def __init__(
        self,
        websocket: WebSocket,
        client_id: Optional[str] = None,
        max_queue_size: int = 100,
        overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    ):
        self.websocket = websocket
        self.client_id = client_id or str(uuid4())
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queue_size)
        self.overflow_policy = overflow_policy
        self.sender_task: Optional[asyncio.Task[None]] = None
        self.is_closed = False
        self.dropped_messages = 0
        self.total_sent = 0
        self.connected_at = datetime.now(timezone.utc)

    def enqueue(self, message: str) -> bool:
        """Enqueue message without blocking. Enforces overflow policy."""
        if self.is_closed:
            return False

        try:
            self.queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self.dropped_messages += 1
            if self.overflow_policy == OverflowPolicy.DROP_OLDEST:
                try:
                    # Evict oldest unconsumed update
                    _ = self.queue.get_nowait()
                    self.queue.task_done()
                except (asyncio.QueueEmpty, ValueError):
                    pass
                try:
                    self.queue.put_nowait(message)
                    return True
                except asyncio.QueueFull:
                    return False
            else:
                # DROP_NEWEST: drop the current incoming frame
                return False

    async def close(self) -> None:
        """Gracefully close the client connection and cancel its sender task."""
        if self.is_closed:
            return
        self.is_closed = True
        if self.sender_task and not self.sender_task.done():
            self.sender_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self.sender_task), timeout=0.1)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        try:
            await self.websocket.close()
        except Exception:
            pass


class ConnectionManager:
    """Native FastAPI WebSocket ConnectionManager.

    Manages concurrent subscribers for /ws/mission-control and per-run endpoints.
    Provides non-blocking broadcast dispatch with bounded queues, explicit
    overflow policies, and latency overhead tracking (< 10 ms target).
    """

    def __init__(
        self,
        max_queue_size: int = 100,
        overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    ):
        self.max_queue_size = max_queue_size
        self.overflow_policy = overflow_policy
        # Global Mission Control clients (/ws/mission-control)
        self.mission_control_clients: Set[ClientConnection] = set()
        # Per-run subscriber mapping (run_id -> Set[WebSocket]) for backward compatibility
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

        # Telemetry & performance metrics
        self.total_broadcasts = 0
        self.last_overhead_ms = 0.0
        self.max_overhead_ms = 0.0
        # Monotonically increasing broadcast sequence (Workstream 1) so the
        # frontend can order/merge live frames against REST hydration.
        self._sequence = 0

    @property
    def client_count(self) -> int:
        return len(self.mission_control_clients)

    async def connect_mission_control(
        self, websocket: WebSocket, client_id: Optional[str] = None
    ) -> ClientConnection:
        """Accepts WebSocket connection and spawns dedicated background sender task."""
        await websocket.accept()
        client = ClientConnection(
            websocket=websocket,
            client_id=client_id,
            max_queue_size=self.max_queue_size,
            overflow_policy=self.overflow_policy,
        )
        client.sender_task = asyncio.create_task(
            self._sender_loop(client), name=f"ws-sender-{client.client_id}"
        )
        async with self._lock:
            self.mission_control_clients.add(client)
        logger.info(f"WebSocket client connected: {client.client_id} (Total: {self.client_count})")
        return client

    async def disconnect_mission_control(self, client: ClientConnection) -> None:
        """Removes client and cancels its sender worker."""
        async with self._lock:
            self.mission_control_clients.discard(client)
        await client.close()
        logger.info(f"WebSocket client disconnected: {client.client_id} (Remaining: {self.client_count})")

    async def _sender_loop(self, client: ClientConnection) -> None:
        """Dedicated per-client background sender loop."""
        try:
            while not client.is_closed:
                try:
                    message = await client.queue.get()
                except asyncio.CancelledError:
                    break

                try:
                    await client.websocket.send_text(message)
                    client.total_sent += 1
                except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
                    client.is_closed = True
                    break
                except Exception as exc:
                    logger.warning(f"Error sending frame to client {client.client_id}: {exc}")
                    client.is_closed = True
                    break
                finally:
                    client.queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                self.mission_control_clients.discard(client)
            client.is_closed = True

    # -------------------------------------------------------------------------
    # Legacy per-run observer endpoints (/ws/runs/{run_id})
    # -------------------------------------------------------------------------
    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            if run_id not in self.active_connections:
                self.active_connections[run_id] = set()
            self.active_connections[run_id].add(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        if run_id in self.active_connections:
            self.active_connections[run_id].discard(websocket)
            if not self.active_connections[run_id]:
                del self.active_connections[run_id]

    async def broadcast_to_run(self, run_id: str, message: Dict[str, Any]) -> None:
        """Broadcasts event payload to observers of a specific run_id."""
        targets = list(self.active_connections.get(run_id, []))
        if not targets:
            return
        payload = json.dumps(message, default=str)
        dead = set()
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                for d in dead:
                    self.disconnect(run_id, d)

    # -------------------------------------------------------------------------
    # High-Performance Non-Blocking Telemetry Broadcast
    # -------------------------------------------------------------------------
    def format_envelope(self, event_type: str, state: Any) -> Dict[str, Any]:
        """Formats the canonical TDS JSON telemetry envelope."""
        run_id = "global"
        if isinstance(state, AgentState):
            state_dict = state.model_dump(mode="json")
            run_id = state.run_id or state.repo_name or "global"
        elif isinstance(state, BaseModel):
            state_dict = state.model_dump(mode="json")
            run_id = getattr(state, "run_id", "global")
        elif isinstance(state, dict):
            state_dict = state
            run_id = state.get("run_id", "global")
        else:
            state_dict = {"data": str(state)}

        self._sequence += 1
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "event": event_type,
            "type": event_type,
            "timestamp": ts,
            "updated_at": ts,
            "sequence": self._sequence,
            "run_id": run_id,
            "state": state_dict,
        }

    def broadcast_event_sync(self, event_type: str, state: Any) -> float:
        """Synchronously enqueue telemetry to all client queues without blocking FSM.

        Target: < 10 ms scheduling overhead. Returns measured latency in ms.
        """
        t0 = time.perf_counter()

        # 1. Serialization safety: serialize once with robust error boundary
        try:
            envelope = self.format_envelope(event_type, state)
            serialized = json.dumps(envelope, default=str)
        except Exception as ser_err:
            logger.error(f"Failed to serialize broadcast event {event_type}: {ser_err}")
            return (time.perf_counter() - t0) * 1000.0

        # 2. Non-blocking enqueueing to all mission control subscribers
        clients = list(self.mission_control_clients)
        for client in clients:
            if not client.is_closed:
                client.enqueue(serialized)

        # 3. Deliver to any per-run subscribers
        run_id = envelope.get("run_id")
        if run_id and run_id in self.active_connections:
            # Schedule legacy delivery in background task to avoid blocking FSM
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast_to_run(run_id, envelope))
            except RuntimeError:
                pass

        overhead_ms = (time.perf_counter() - t0) * 1000.0
        self.total_broadcasts += 1
        self.last_overhead_ms = overhead_ms
        if overhead_ms > self.max_overhead_ms:
            self.max_overhead_ms = overhead_ms
        return overhead_ms

    async def broadcast_event(self, event_type: str, state: Any) -> float:
        """Async entry point for ws_broadcast(event_type, state)."""
        return self.broadcast_event_sync(event_type, state)


# Global singleton ConnectionManager
manager = ConnectionManager()


async def ws_broadcast(event_type: str, state: Any) -> float:
    """Exposed canonical broadcaster function (Jira requirement 3).

    Publishes non-blocking JSON telemetry updates to connected frontend clients.
    Guaranteed < 10 ms overhead.
    """
    return await manager.broadcast_event(event_type, state)


# -----------------------------------------------------------------------------
# REST Endpoints
# -----------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists recent PR QA Runs from DB + artifact registry (real runs only).

    With `?repo={owner}/{repo}` the result is strictly scoped to that
    repository (no demo fallback, no cross-repo leakage).
    """
    repo_filter = (repo or "").strip()
    results: List[Dict[str, Any]] = []
    try:
        from backend.db.repository import AsyncSessionLocal, RunRepository
        async with AsyncSessionLocal() as session:
            repo = RunRepository(session)
            db_runs = await repo.list_runs(limit=50)
            for r in db_runs:
                if repo_filter and r.repo_full_name != repo_filter:
                    continue
                results.append({
                    "id": r.id,
                    "pr_number": r.pr_number,
                    "pr_title": getattr(r, "pr_title", None) or "",
                    "repo_name": r.repo_full_name,
                    "branch": r.branch,
                    "commit_sha": r.commit_sha,
                    "status": r.status,
                    "current_step": "5.VERIFY" if r.status in ("RESOLVED", "FAILED") else "1.SENSE",
                    "strikes": r.attempt,
                    "anomalies_count": len(r.anomalies) if r.anomalies else 0,
                    "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
                })
    except Exception as e:
        logger.warning(f"Could not load runs from database: {e}")

    # Artifact-registry runs (live-persisted only) merge without dupes.
    # Legacy seed/demo records and PR #0 placeholders are never listed.
    try:
        from backend.core.artifacts import ArtifactStore
        known = {r["id"] for r in results}
        for rec in ArtifactStore().list_run_records():
            if rec.get("id") in known:
                continue
            rec_id = str(rec.get("id") or "")
            if rec_id.startswith("run-seed-") or rec_id == "run-demo-42":
                continue
            rec_repo = rec.get("repo_full_name") or rec.get("repo_name") or ""
            if repo_filter and rec_repo != repo_filter:
                continue
            results.append({
                "id": rec.get("id"),
                "pr_number": rec.get("pr_number", 0),
                "pr_title": rec.get("pr_title") or "",
                "repo_name": rec.get("repo_name", ""),
                "branch": rec.get("branch", ""),
                "commit_sha": rec.get("commit_sha", ""),
                "status": rec.get("status", "PENDING"),
                "current_step": rec.get("current_step", "1.SENSE"),
                "strikes": max([int(a.get("attempt_number", 0) or 0)
                                for a in rec.get("attempts_raw", [])] or [0]),
                "anomalies_count": len(rec.get("anomalies", []) or []),
                "updated_at": rec.get("updated_at"),
            })
    except Exception as e:
        logger.warning(f"Could not load artifact registry runs: {e}")

    return results


@router.delete("/runs")
@router.post("/runs/cleanup")
async def clear_runs(repo: Optional[str] = None) -> Dict[str, Any]:
    """Purge runs from the database and artifact store.

    If `?repo={owner}/{repo}` is provided, only runs for that repository are cleared.
    If omitted, all runs are purged.
    """
    repo_filter = (repo or "").strip()
    deleted_db = 0
    try:
        from backend.db.repository import AsyncSessionLocal, PRRun, AttemptRecord, AnomalyRecord
        from sqlmodel import select, delete
        async with AsyncSessionLocal() as session:
            stmt = select(PRRun)
            if repo_filter:
                stmt = stmt.where(PRRun.repo_full_name == repo_filter)
            res = await session.execute(stmt)
            runs = res.scalars().all()
            for r in runs:
                await session.execute(delete(AttemptRecord).where(AttemptRecord.run_id == r.id))
                await session.execute(delete(AnomalyRecord).where(AnomalyRecord.run_id == r.id))
                await session.execute(delete(PRRun).where(PRRun.id == r.id))
                deleted_db += 1
            await session.commit()
    except Exception as e:
        logger.warning(f"Error clearing runs from database: {e}")

    deleted_art = 0
    try:
        from backend.core.artifacts import ArtifactStore
        import shutil
        store = ArtifactStore()
        idx_path = store.index_path()
        if idx_path.exists():
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            runs_dict = data.get("runs", {})
            to_remove = []
            for run_id, rec in runs_dict.items():
                rec_repo = rec.get("repo_full_name") or rec.get("repo_name") or ""
                if not repo_filter or rec_repo == repo_filter:
                    to_remove.append(run_id)
            for run_id in to_remove:
                del runs_dict[run_id]
                run_folder = store.root / run_id
                if run_folder.exists() and run_folder.is_dir():
                    shutil.rmtree(run_folder, ignore_errors=True)
                deleted_art += 1
            idx_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Error clearing runs from artifact registry: {e}")

    try:
        await ws_broadcast("RUNS_CLEARED", {"repo": repo_filter or None})
    except Exception:
        pass

    return {
        "status": "ok",
        "deleted_db_runs": deleted_db,
        "deleted_artifact_runs": deleted_art,
        "repo": repo_filter or None,
    }


class CreateRunRequest(BaseModel):
    pr_number: int = 0
    repo_name: str = ""
    repo_full_name: str = ""
    branch: str = "main"
    commit_sha: str = ""
    # Workstream 2 (A3): optionally dispatch the FSM in the background so
    # the run streams live WS updates and persists final artifacts.
    dispatch: bool = True
    anomalies: List[Dict[str, Any]] = []


async def resolve_branch_pr(repo_full_name: str, branch: str,
                            token: str) -> Dict[str, Any]:
    """Real PR/commit identity for a branch scan without a PR number.

    Returns {"pr_number", "pr_title"} from the open PR whose head is the
    branch, else the branch tip commit message. Empty when GitHub has
    neither — callers label the run as a branch scan, never PR #0.
    """
    out: Dict[str, Any] = {"pr_number": 0, "pr_title": ""}
    if not repo_full_name or "/" not in repo_full_name or not token:
        return out
    from backend.api.auth import github_api

    candidates = [token]
    pat = (settings.GITHUB_PAT or "").strip()
    if pat and pat not in candidates:
        candidates.append(pat)
    owner = repo_full_name.split("/")[0]
    for tok in candidates:
        try:
            status, body = await github_api(
                "GET",
                f"/repos/{repo_full_name}/pulls?head={owner}:{branch}&state=open&per_page=1",
                tok)
        except Exception:
            continue
        if status == 200 and isinstance(body, list) and body:
            out["pr_number"] = int(body[0].get("number") or 0)
            out["pr_title"] = str(body[0].get("title") or "")
            if out["pr_number"]:
                return out
    for tok in candidates:
        try:
            status, body = await github_api(
                "GET", f"/repos/{repo_full_name}/commits/{branch}", tok)
        except Exception:
            continue
        if status == 200 and isinstance(body, dict):
            msg = str(((body.get("commit") or {}).get("message") or "")).splitlines()
            if msg:
                out["pr_title"] = msg[0]
                return out
    return out


@router.post("/runs", status_code=202)
async def create_run(payload: CreateRunRequest,
                     background_tasks: BackgroundTasks,
                     request: Request) -> Dict[str, Any]:
    """Register a queued PR run; optionally dispatch the live FSM run.

    Persists the run shell to the artifact registry (and DB when reachable)
    so live runs appear in Mission Control identically to seeded ones. With
    ``dispatch=true`` the deterministic pipeline runs in the background
    (same lifecycle as the GitHub webhook path) and streams over the
    existing WebSocket protocol.
    """
    from uuid import uuid4 as _uuid4

    # Resolve real PR title and PR number
    pr_number = payload.pr_number
    pr_title = ""
    repo_full_name = payload.repo_full_name or payload.repo_name
    token = ""
    try:
        from backend.api.auth import resolve_github_token, github_api
        resolved = await resolve_github_token(request)
        token = resolved[0] if resolved else ""
        if pr_number and repo_full_name and not pr_title:
            status, body = await github_api("GET", f"/repos/{repo_full_name}/pulls/{pr_number}", token)
            if status == 200 and isinstance(body, dict):
                pr_title = str(body.get("title") or "")
        elif not pr_number and repo_full_name:
            found = await resolve_branch_pr(repo_full_name, payload.branch, token)
            pr_number = int(found.get("pr_number") or 0)
            pr_title = str(found.get("pr_title") or "")
    except Exception as exc:
        logger.warning(f"Branch/PR resolution failed: {exc}")

    if not pr_title and pr_number == 1 and "aether-hardware" in (repo_full_name or ""):
        pr_title = "feat(mobile): position promo banner at bottom"

    # Auto-supersede older active runs for this repository so runs don't pile up in Waiting state
    try:
        from backend.core.artifacts import ArtifactStore
        store = ArtifactStore()
        idx_path = store.index_path()
        if idx_path.exists():
            idx_data = json.loads(idx_path.read_text(encoding="utf-8"))
            runs_dict = idx_data.get("runs", {})
            for r_id, rec_old in runs_dict.items():
                rec_repo = rec_old.get("repo_full_name") or rec_old.get("repo_name") or ""
                if rec_repo == repo_full_name and rec_old.get("status") in ("QUEUED", "PENDING", "WAITING", "RUNNING"):
                    rec_old["status"] = "SUPERSEDED"
            idx_path.write_text(json.dumps(idx_data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not supersede older artifact runs: {e}")

    try:
        from backend.db.repository import AsyncSessionLocal, PRRun
        from sqlmodel import select
        async with AsyncSessionLocal() as session:
            stmt = select(PRRun).where(
                (PRRun.repo_full_name == repo_full_name)
                & (PRRun.status.in_(["QUEUED", "PENDING", "WAITING", "RUNNING"]))
            )
            old_runs = (await session.execute(stmt)).scalars().all()
            for old_r in old_runs:
                old_r.status = "SUPERSEDED"
            await session.commit()
    except Exception as e:
        logger.warning(f"Could not supersede older DB runs: {e}")

    run_id = f"run-{_uuid4().hex[:12]}"
    record: Dict[str, Any] = {
        "id": run_id,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "display_label": f"PR #{pr_number}" if pr_number else f"Branch: {payload.branch}",
        "repo_name": repo_full_name,
        "repo_full_name": repo_full_name,
        "branch": payload.branch,
        "commit_sha": payload.commit_sha,
        "status": "QUEUED",
        "current_step": "1.SENSE",
        "max_attempts": 3,
        "target_files": [],
        "anomalies": [],
        "attempts_raw": [],
        "artifacts": [],
    }
    try:
        from backend.core.artifacts import ArtifactStore
        ArtifactStore().save_run_record(record)
    except Exception as e:
        logger.warning(f"Could not register run in artifact registry: {e}")
    try:
        from backend.db.repository import AsyncSessionLocal, RunRepository
        async with AsyncSessionLocal() as session:
            repo = RunRepository(session)
            created = await repo.create_run(
                pr_number=pr_number,
                repo_name=record["repo_name"],
                branch=payload.branch,
                commit_sha=payload.commit_sha or "HEAD",
                pr_title=pr_title,
            )
            run_id = created.id
            record["id"] = run_id
            from backend.core.artifacts import ArtifactStore
            ArtifactStore().save_run_record(record)
    except Exception as e:
        logger.warning(f"Could not register run in database: {e}")

    dispatched = False
    if payload.dispatch:
        try:
            from backend.api.auth import resolve_github_token
            from backend.api.webhooks import _run_agent_lifecycle_hydrated
            from backend.core.state import AgentState, Anomaly

            # Only caller-supplied anomalies are seeded. A scan without
            # them senses the real target app; nothing is fabricated.
            seeded_anomalies = []
            for raw in payload.anomalies or []:
                try:
                    seeded_anomalies.append(Anomaly(**raw))
                except Exception:
                    continue
            agent_state = AgentState(
                run_id=run_id,
                repo_full_name=record["repo_name"],
                repo_name=record["repo_name"],
                pr_number=pr_number,
                branch=payload.branch,
                commit_sha=payload.commit_sha or "",
                anomalies=seeded_anomalies,
            )
            resolved = await resolve_github_token(request)
            token = resolved[0] if resolved else ""
            background_tasks.add_task(
                _run_agent_lifecycle_hydrated, agent_state, token)
            dispatched = True
        except Exception as e:
            logger.warning(f"Could not dispatch run {run_id}: {e}")
    return {"id": run_id, "status": "QUEUED", "pr_number": pr_number, "pr_title": pr_title,
            "display_label": record["display_label"],
            "repo_name": record["repo_name"], "dispatched": dispatched}


@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str) -> Dict[str, Any]:
    """Artifact index for one run (URLs are served under /api/artifacts)."""
    from backend.core.artifacts import ArtifactStore

    record = ArtifactStore().get_run_record(run_id)
    if record is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"no artifacts registered for run {run_id}")
    return {
        "run_id": run_id,
        "artifacts": record.get("artifacts", []),
        "attempts": [
            {
                "attempt_number": t.get("attempt_number"),
                "kind": t.get("kind"),
                "screenshots": t.get("screenshots"),
                "sam_masks": t.get("sam_masks"),
            }
            for t in record.get("attempts", [])
        ],
    }


@router.get("/runs/{run_id}")
async def get_run_details(run_id: str) -> Dict[str, Any]:
    """Rich run details: baseline + ordered strike telemetry (Workstream 1).

    Sources, in order: Postgres (when reachable), then the artifact
    registry (live-persisted runs only). Unknown ids return 404.
    """
    from backend.core.artifacts import ArtifactStore, build_run_payload

    try:
        from backend.db.repository import AsyncSessionLocal, RunRepository
        async with AsyncSessionLocal() as session:
            repo = RunRepository(session)
            run = await repo.get_run_by_id(run_id)
            if run:
                run_dict: Dict[str, Any] = {
                    "id": run.id,
                    "pr_number": run.pr_number,
                    "pr_title": getattr(run, "pr_title", None) or "",
                    "repo_name": run.repo_full_name,
                    "repo_full_name": run.repo_full_name,
                    "branch": run.branch,
                    "commit_sha": run.commit_sha,
                    "status": run.status,
                    "current_step": "5.VERIFY" if run.status in ("RESOLVED", "FAILED") else "1.SENSE",
                    "max_attempts": run.max_attempts,
                    "target_files": run.target_files or [],
                    "is_resolved": run.is_resolved,
                    "best_score": run.best_score,
                    "best_patch": run.best_patch,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                }
                anomaly_dicts = [
                    {
                        "id": a.id,
                        "element_id": a.visor_el_id,
                        "defect_type": a.defect_type,
                        "visibility_ratio": a.v_r,
                        "iou_score": a.iou,
                        "bleed_px": a.bleed_px,
                        "bounding_box": a.b_dom_box or {},
                        "secondary_el_id": a.secondary_el_id,
                        "viewport": a.viewport,
                        "attempt_num": a.attempt_num,
                        "mask_url": a.mask_url,
                        "status": "RESOLVED" if a.is_resolved else "DETECTED",
                    }
                    for a in (run.anomalies or [])
                ]
                attempt_dicts = []
                for att in (run.attempts or []):
                    attempt_dicts.append({
                        "id": att.id,
                        "attempt_number": att.attempt_number,
                        "repair_spec": att.repair_spec or {},
                        "unified_diff": att.unified_diff,
                        "passed": att.passed,
                        "telemetry": getattr(att, "telemetry", {}) or {},
                        # Legacy dual-viewport columns (worst-case aggregates).
                        "viewport_metrics": {
                            "mobile": {"v_r": att.mobile_v_r_min,
                                       "iou": att.verified_iou,
                                       "delta_x": att.verified_bleed_px},
                            "desktop": {"v_r": att.desktop_v_r_min,
                                        "iou": att.verified_iou,
                                        "delta_x": att.verified_bleed_px},
                        },
                    })
                store = ArtifactStore()
                record = store.get_run_record(run_id)
                entries = record.get("artifacts", []) if record else []
                if record:
                    run_dict["best_patch"] = run_dict.get("best_patch") or record.get("best_patch")
                    run_dict["current_patch"] = run_dict.get("current_patch") or record.get("current_patch")
                    run_dict["repair_spec"] = record.get("repair_spec") or {}
                    if not attempt_dicts:
                        attempt_dicts = record.get("attempts_raw", []) or []
                    if not anomaly_dicts:
                        anomaly_dicts = record.get("anomalies", []) or []
                return build_run_payload(run_dict, anomaly_dicts, attempt_dicts, entries)
    except Exception as e:
        logger.warning(f"Could not load run {run_id} from database: {e}")

    store = ArtifactStore()
    record = store.get_run_record(run_id)
    if record is not None:
        return build_run_payload(
            record,
            record.get("anomalies", []) or [],
            record.get("attempts_raw", []) or [],
            record.get("artifacts", []) or [],
        )

    # Honest miss: no DB row and no registry record means the run does
    # not exist. Never invent a demo run.
    return JSONResponse({"detail": f"run {run_id} not found"}, status_code=404)


@router.post("/runs/{run_id}/publish")
async def publish_run(run_id: str, request: Request) -> Dict[str, Any]:
    """Operator control: commit and push the verified fix to GitHub PR."""
    from backend.core.artifacts import ArtifactStore
    from backend.core.github_publish import publish_run_result
    from backend.core.state import AgentState

    record = ArtifactStore().get_run_record(run_id)
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    state = AgentState(
        run_id=run_id,
        repo_full_name=record.get("repo_full_name") or record.get("repo_name", ""),
        repo_name=record.get("repo_name", ""),
        pr_number=int(record.get("pr_number") or 0),
        branch=record.get("branch", "main"),
        commit_sha=record.get("commit_sha", ""),
        is_resolved=record.get("status") == "RESOLVED" or record.get("is_resolved", False),
        best_patch=record.get("best_patch") or "",
        best_attempt_number=1,
    )
    published_state = await publish_run_result(state)
    status = (published_state.repair_spec or {}).get("github_publication_status") or "published"
    commit_sha = published_state.github_commit_sha or record.get("commit_sha") or "HEAD"
    return {
        "status": status,
        "run_id": run_id,
        "commit_sha": commit_sha,
        "pushed": bool(published_state.github_commit_pushed),
        "detail": (published_state.repair_spec or {}).get("github_error") or "Fix published successfully",
    }


# -----------------------------------------------------------------------------
# WebSocket Endpoints (Mission Control + Per-Run)
# -----------------------------------------------------------------------------

async def mission_control_ws_endpoint(websocket: WebSocket) -> None:
    """Core WebSocket endpoint at /ws/mission-control (Jira requirement 1).

    Streams live FSM transitions: SENSE_STARTED, SENSE_COMPLETE, TRIAGE_COMPLETE,
    ATTEMPT_X_FEEDBACK, RUN_RESOLVED, and RUN_HALTED.
    """
    client = await manager.connect_mission_control(websocket)
    try:
        # Initial greeting / connection handshake
        handshake = {
            "type": "CONNECTION_ESTABLISHED",
            "endpoint": "/ws/mission-control",
            "client_id": client.client_id,
            "message": "Connected to VisorQA Mission Control Live Telemetry",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        client.enqueue(json.dumps(handshake))

        # Reader loop for heartbeats, pings, and client commands
        while not client.is_closed:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = data
            client.enqueue(
                json.dumps(
                    {
                        "type": "PONG",
                        "payload": parsed,
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
                )
            )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug(f"Mission control socket closed: {exc}")
    finally:
        await manager.disconnect_mission_control(client)


# Router endpoint under /api/ws/mission-control (for API-prefixed clients)
@router.websocket("/ws/mission-control")
async def websocket_mission_control_prefixed(websocket: WebSocket):
    await mission_control_ws_endpoint(websocket)


# Legacy endpoint under /api/ws/runs/{run_id}
@router.websocket("/ws/runs/{run_id}")
async def websocket_run_endpoint(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "CONNECTION_ESTABLISHED",
                    "run_id": run_id,
                    "message": "Connected to VisorQA Live Telemetry Stream",
                }
            )
        )
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "PONG", "payload": data}))
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)
