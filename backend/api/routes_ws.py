"""
VisorQA Controller Layer - REST & WebSockets
GET /api/runs + WS /ws/runs/{run_id} (Observer Pattern)
"""

from typing import Dict, List, Set, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status
import json

router = APIRouter(prefix="/api", tags=["Runs & WebSockets"])


class ConnectionManager:
    """
    (Observer Pattern) Manages active WebSocket connections per PR run
    to broadcast live FSM transitions and telemetry.
    """

    def __init__(self):
        # Map run_id -> Set of active WebSockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if run_id not in self.active_connections:
            self.active_connections[run_id] = set()
        self.active_connections[run_id].add(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        if run_id in self.active_connections:
            self.active_connections[run_id].discard(websocket)
            if not self.active_connections[run_id]:
                del self.active_connections[run_id]

    async def broadcast_to_run(self, run_id: str, message: Dict[str, Any]) -> None:
        """Broadcasts event payload to all observers watching this run"""
        if run_id in self.active_connections:
            dead_sockets = set()
            for connection in self.active_connections[run_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    dead_sockets.add(connection)
            for dead in dead_sockets:
                self.disconnect(run_id, dead)


manager = ConnectionManager()


# -----------------------------------------------------------------------------
# REST Endpoints
# -----------------------------------------------------------------------------

@router.get("/runs")
async def list_runs() -> List[Dict[str, Any]]:
    """Lists recent PR QA Runs for the Mission Control dashboard"""
    # Interface stub: Mock initial runs for frontend scaffolding
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
    # Interface stub: Mock run details
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
                "status": "DETECTED"
            }
        ],
        "attempts": []
    }


# -----------------------------------------------------------------------------
# WebSocket Endpoint (Observer Pattern)
# -----------------------------------------------------------------------------

@router.websocket("/ws/runs/{run_id}")
async def websocket_run_endpoint(websocket: WebSocket, run_id: str):
    """
    WebSocket endpoint streaming live FSM node updates, SAM 3.1 masks,
    and HMR verification telemetry to connected clients.
    """
    await manager.connect(run_id, websocket)
    try:
        # Initial greeting / connection handshake
        await websocket.send_text(json.dumps({
            "type": "CONNECTION_ESTABLISHED",
            "run_id": run_id,
            "message": "Connected to VisorQA Live Telemetry Stream"
        }))

        # Keep connection open for client pings / incoming triggers
        while True:
            data = await websocket.receive_text()
            # Handle incoming client messages if any
            await websocket.send_text(json.dumps({
                "type": "PONG",
                "payload": data
            }))
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)
