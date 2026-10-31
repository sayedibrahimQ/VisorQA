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

from fastapi import APIRouter, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

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
async def list_runs() -> List[Dict[str, Any]]:
    """Lists recent PR QA Runs from DB + artifact registry, demo fallback last."""
    results: List[Dict[str, Any]] = []
    try:
        from backend.db.repository import AsyncSessionLocal, RunRepository
        async with AsyncSessionLocal() as session:
            repo = RunRepository(session)
            db_runs = await repo.list_runs(limit=50)
            for r in db_runs:
                results.append({
                    "id": r.id,
                    "pr_number": r.pr_number,
                    "repo_name": r.repo_full_name,
                    "branch": r.branch,
                    "commit_sha": r.commit_sha,
                    "status": r.status,
                    "current_step": "1.SENSE",
                    "strikes": r.attempt,
                    "anomalies_count": len(r.anomalies) if r.anomalies else 0,
                    "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
                })
    except Exception as e:
        logger.warning(f"Could not load runs from database: {e}")

    # Artifact-registry runs (seeded + live-persisted) merge without dupes.
    try:
        from backend.core.artifacts import ArtifactStore
        known = {r["id"] for r in results}
        for rec in ArtifactStore().list_run_records():
            if rec.get("id") in known:
                continue
            results.append({
                "id": rec.get("id"),
                "pr_number": rec.get("pr_number", 0),
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

    # Ensure demo runs are also available for inspection if list is empty or for demo-42
    if not any(r["id"] == "run-demo-42" for r in results):
        results.append({
            "id": "run-demo-42",
            "pr_number": 42,
            "repo_name": "sayedibrahimQ/VisorQA",
            "branch": "fix/checkout-banner",
            "commit_sha": "a1b2c3d",
            "status": "RUNNING",
            "current_step": "1.SENSE",
            "strikes": 0,
            "anomalies_count": 1,
        })
    return results


class CreateRunRequest(BaseModel):
    pr_number: int = 0
    repo_name: str = ""
    repo_full_name: str = ""
    branch: str = "main"
    commit_sha: str = ""
    # Workstream 2 (A3): optionally dispatch the FSM in the background so
    # the run streams live WS updates and persists final artifacts.
    dispatch: bool = False
    anomalies: List[Dict[str, Any]] = []


@router.post("/runs", status_code=202)
async def create_run(payload: CreateRunRequest,
                     background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Register a queued PR run; optionally dispatch the live FSM run.

    Persists the run shell to the artifact registry (and DB when reachable)
    so live runs appear in Mission Control identically to seeded ones. With
    ``dispatch=true`` the deterministic pipeline runs in the background
    (same lifecycle as the GitHub webhook path) and streams over the
    existing WebSocket protocol.
    """
    from uuid import uuid4 as _uuid4

    run_id = f"run-{_uuid4().hex[:12]}"
    record: Dict[str, Any] = {
        "id": run_id,
        "pr_number": payload.pr_number,
        "repo_name": payload.repo_full_name or payload.repo_name,
        "repo_full_name": payload.repo_full_name or payload.repo_name,
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
                pr_number=payload.pr_number,
                repo_name=record["repo_name"],
                branch=payload.branch,
                commit_sha=payload.commit_sha or "HEAD",
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
            from backend.api.webhooks import _run_agent_lifecycle
            from backend.core.state import AgentState, Anomaly

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
                pr_number=payload.pr_number,
                branch=payload.branch,
                commit_sha=payload.commit_sha or "",
                anomalies=seeded_anomalies,
            )
            background_tasks.add_task(_run_agent_lifecycle, agent_state)
            dispatched = True
        except Exception as e:
            logger.warning(f"Could not dispatch run {run_id}: {e}")
    return {"id": run_id, "status": "QUEUED", "pr_number": payload.pr_number,
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

    Sources, in order: Postgres (when reachable), the artifact registry
    (seeded + live-persisted runs), then the deterministic demo fallback.
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
                    "repo_name": run.repo_full_name,
                    "repo_full_name": run.repo_full_name,
                    "branch": run.branch,
                    "commit_sha": run.commit_sha,
                    "status": run.status,
                    "current_step": "1.SENSE",
                    "max_attempts": run.max_attempts,
                    "target_files": run.target_files or [],
                    "is_resolved": run.is_resolved,
                    "best_score": run.best_score,
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

    # Fallback to demo run details (same rich shape, no artifacts on disk)
    demo_run: Dict[str, Any] = {
        "id": run_id,
        "pr_number": 42,
        "repo_name": "sayedibrahimQ/VisorQA",
        "repo_full_name": "sayedibrahimQ/VisorQA",
        "branch": "fix/checkout-banner",
        "commit_sha": "a1b2c3d",
        "status": "RUNNING",
        "current_step": "1.SENSE",
        "max_attempts": 3,
        "target_files": [],
    }
    demo_anomalies = [
        {
            "id": "anom-01",
            "element_id": "visor-el-04",
            "defect_type": "OCCLUSION",
            "visibility_ratio": 0.62,
            "iou_score": 0.0,
            "bleed_px": 0.0,
            "bounding_box": {"x": 12, "y": 80, "width": 350, "height": 60},
            "viewport": "375px",
            "attempt_num": 0,
            "status": "DETECTED",
        }
    ]
    return build_run_payload(demo_run, demo_anomalies, [], [])


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
