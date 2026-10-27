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
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
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

        return {
            "event": event_type,
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    """Lists recent PR QA Runs for the Mission Control dashboard"""
    return [
        {
            "id": "run-demo-42",
            "pr_number": 42,
            "repo_name": "sayedibrahimQ/VisorQA",
            "branch": "fix/checkout-banner",
            "commit_sha": "a1b2c3d",
            "status": "RUNNING",
            "current_step": "1.SENSE",
            "strikes": 0,
            "anomalies_count": 1,
        }
    ]


@router.get("/runs/{run_id}")
async def get_run_details(run_id: str) -> Dict[str, Any]:
    """Retrieves deep-link run details for Inspector permalink view"""
    return {
        "id": run_id,
        "pr_number": 42,
        "repo_name": "sayedibrahimQ/VisorQA",
        "branch": "fix/checkout-banner",
        "commit_sha": "a1b2c3d",
        "status": "RUNNING",
        "current_step": "1.SENSE",
        "strikes": 0,
        "anomalies": [
            {
                "id": "anom-01",
                "element_id": "visor-el-04",
                "defect_type": "OCCLUSION",
                "visibility_ratio": 0.62,
                "iou_score": 0.0,
                "bounding_box": {"x": 12, "y": 80, "width": 350, "height": 60},
                "status": "DETECTED",
            }
        ],
        "attempts": [],
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
