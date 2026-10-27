"""
Automated Test Suite for FastAPI WebSocket Mission Control & ConnectionManager (Jira)
Validates:
- Multiple concurrent subscribers
- Correct JSON payload envelope schema
- Clean disconnection handling and failure isolation
- Non-blocking slow-client bounded queue with DROP_OLDEST overflow policy
- Measured scheduling overhead strictly < 10 ms target
- End-to-end FSM transition event coverage (SENSE_STARTED -> SENSE_COMPLETE -> TRIAGE_COMPLETE -> ATTEMPT_X_FEEDBACK -> RUN_RESOLVED / RUN_HALTED)
"""

import asyncio
import json
import time
from typing import List
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.api.routes_ws import (
    ConnectionManager,
    ClientConnection,
    OverflowPolicy,
    ws_broadcast,
    manager,
)
from backend.core.orchestrator import run_visor_agent, VisorOrchestrator
from backend.core.state import (
    AgentState,
    Anomaly,
    DefectType,
    FSMStep,
    RunStatus,
    SelfHealingAttempt,
)


@pytest.fixture(autouse=True)
def cleanup_manager():
    """Ensure clean manager state between tests."""
    manager.mission_control_clients.clear()
    manager.active_connections.clear()
    manager.total_broadcasts = 0
    yield
    manager.mission_control_clients.clear()
    manager.active_connections.clear()


def test_mission_control_handshake_and_ping():
    """Verifies WebSocket connection handshake and bidirectional frame exchange."""
    client = TestClient(app)
    with client.websocket_connect("/ws/mission-control") as ws:
        greeting = ws.receive_json()
        assert greeting["type"] == "CONNECTION_ESTABLISHED"
        assert greeting["endpoint"] == "/ws/mission-control"
        assert "client_id" in greeting

        # Send ping frame
        ws.send_text(json.dumps({"action": "ping", "sequence": 1}))
        response = ws.receive_json()
        assert response["type"] == "PONG"
        assert response["payload"] == {"action": "ping", "sequence": 1}


def test_api_prefixed_mission_control_endpoint():
    """Verifies that /api/ws/mission-control is also mounted and functional."""
    client = TestClient(app)
    with client.websocket_connect("/api/ws/mission-control") as ws:
        greeting = ws.receive_json()
        assert greeting["type"] == "CONNECTION_ESTABLISHED"


@pytest.mark.asyncio
async def test_multiple_concurrent_clients_receive_broadcast():
    """Requirement 2 & 3: Multiple concurrent subscribers receive identical JSON telemetry."""
    test_manager = ConnectionManager()

    class MockWebSocket:
        def __init__(self, name: str):
            self.name = name
            self.received: List[str] = []
            self.closed = False

        async def accept(self):
            pass

        async def send_text(self, text: str):
            if self.closed:
                raise RuntimeError("Socket closed")
            self.received.append(text)

        async def close(self):
            self.closed = True

    ws1, ws2, ws3 = MockWebSocket("client-1"), MockWebSocket("client-2"), MockWebSocket("client-3")
    c1 = await test_manager.connect_mission_control(ws1)
    c2 = await test_manager.connect_mission_control(ws2)
    c3 = await test_manager.connect_mission_control(ws3)

    assert test_manager.client_count == 3

    state = AgentState(
        run_id="run-telemetry-99",
        repo_full_name="sayedibrahimQ/VisorQA",
        pr_number=99,
        branch="feature/ws-broadcast",
        commit_sha="abcdef1",
        status=RunStatus.RUNNING,
    )

    overhead = await test_manager.broadcast_event("SENSE_STARTED", state)
    assert overhead < 10.0  # Requirement 5: non-blocking < 10 ms target

    # Allow sender loops to yield and flush queues
    await asyncio.sleep(0.05)

    for ws in [ws1, ws2, ws3]:
        assert len(ws.received) == 1
        payload = json.loads(ws.received[0])
        assert payload["event"] == "SENSE_STARTED"
        assert payload["run_id"] == "run-telemetry-99"
        assert payload["state"]["pr_number"] == 99
        assert "timestamp" in payload

    # Clean up
    await test_manager.disconnect_mission_control(c1)
    await test_manager.disconnect_mission_control(c2)
    await test_manager.disconnect_mission_control(c3)
    assert test_manager.client_count == 0


@pytest.mark.asyncio
async def test_slow_client_bounded_queue_overflow_policy():
    """Requirement 7: Avoid blocking sequential sends to slow clients using bounded

    per-client queue with DROP_OLDEST overflow policy.
    """
    test_manager = ConnectionManager(max_queue_size=3, overflow_policy=OverflowPolicy.DROP_OLDEST)

    # Slow client whose sender loop is stalled / frozen
    slow_queue: asyncio.Queue = asyncio.Queue(maxsize=3)
    slow_client = ClientConnection(
        websocket=None, client_id="slow-client", max_queue_size=3, overflow_policy=OverflowPolicy.DROP_OLDEST
    )
    slow_client.queue = slow_queue
    test_manager.mission_control_clients.add(slow_client)

    # Normal fast client
    fast_client = ClientConnection(
        websocket=None, client_id="fast-client", max_queue_size=50
    )
    test_manager.mission_control_clients.add(fast_client)

    # Broadcast 6 rapid updates
    for i in range(6):
        await test_manager.broadcast_event("STEP_UPDATE", {"step_num": i})

    # Normal client received all 6 messages
    assert fast_client.queue.qsize() == 6

    # Slow client capped at max_queue_size (3) and recorded 3 drops
    assert slow_client.queue.qsize() == 3
    assert slow_client.dropped_messages == 3

    # Inspect slow client's surviving messages: should be the freshest ones (3, 4, 5)
    surviving = []
    while not slow_queue.empty():
        msg = slow_queue.get_nowait()
        surviving.append(json.loads(msg)["state"]["step_num"])
    assert surviving == [3, 4, 5]


@pytest.mark.asyncio
async def test_failing_client_isolation():
    """Requirement 6: Disconnection or crash on one client does not halt delivery to others."""
    test_manager = ConnectionManager()

    class FailingWebSocket:
        async def accept(self):
            pass

        async def send_text(self, text: str):
            raise ConnectionResetError("Client abruptly disconnected")

        async def close(self):
            pass

    class HealthyWebSocket:
        def __init__(self):
            self.delivered: List[str] = []

        async def accept(self):
            pass

        async def send_text(self, text: str):
            self.delivered.append(text)

        async def close(self):
            pass

    failing_ws = FailingWebSocket()
    healthy_ws = HealthyWebSocket()

    failing_client = await test_manager.connect_mission_control(failing_ws)
    healthy_client = await test_manager.connect_mission_control(healthy_ws)

    # Broadcast event
    await test_manager.broadcast_event("TELEMETRY_PULSE", {"active": True})

    # Allow sender loops to execute
    await asyncio.sleep(0.05)

    # Failing client failed and got cleaned up
    assert failing_client.is_closed is True
    # Healthy client got the payload safely
    assert len(healthy_ws.delivered) == 1
    assert json.loads(healthy_ws.delivered[0])["event"] == "TELEMETRY_PULSE"

    await test_manager.disconnect_mission_control(healthy_client)


@pytest.mark.asyncio
async def test_serialization_error_boundary():
    """Requirement 6: Serialization errors are caught safely and do not crash the FSM."""
    test_manager = ConnectionManager()

    class UnserializableObject:
        def __repr__(self):
            raise TypeError("Cannot stringify this object")

    # Broadcast unserializable payload
    overhead = await test_manager.broadcast_event("BAD_DATA", {"broken": UnserializableObject()})
    assert isinstance(overhead, float)
    assert overhead < 10.0


@pytest.mark.asyncio
async def test_broadcast_scheduling_overhead_benchmark_under_10ms():
    """Requirement 5: Measured broadcast scheduling overhead strictly < 10 ms

    under high subscriber load (50 simulated clients).
    """
    test_manager = ConnectionManager(max_queue_size=200)

    clients = []
    for i in range(50):
        c = ClientConnection(websocket=None, client_id=f"bench-client-{i}", max_queue_size=200)
        test_manager.mission_control_clients.add(c)
        clients.append(c)

    state = AgentState(
        run_id="run-benchmark-heavy",
        repo_full_name="sayedibrahimQ/VisorQA",
        pr_number=500,
        branch="perf/10ms-target",
        commit_sha="9999999",
        status=RunStatus.RUNNING,
        anomalies=[
            Anomaly(
                element_id=f"el-{idx}",
                defect_type=DefectType.COLLISION,
                visibility_ratio=0.72,
                iou_score=0.15,
            )
            for idx in range(10)
        ],
        target_files=["src/components/A.tsx", "src/components/B.tsx"],
        repair_spec={"details": "x" * 2000},
    )

    measurements: List[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        overhead = await test_manager.broadcast_event("BENCH_UPDATE", state)
        t_total = (time.perf_counter() - t0) * 1000.0
        measurements.append(t_total)
        assert overhead < 10.0

    avg_overhead = sum(measurements) / len(measurements)
    max_measured = max(measurements)

    # Documented verification: overhead must be < 10.0 ms
    assert max_measured < 10.0, f"Max overhead {max_measured:.2f}ms exceeded 10ms threshold"
    assert avg_overhead < 2.0, f"Average overhead {avg_overhead:.2f}ms unexpectedly high"


@pytest.mark.asyncio
async def test_fsm_integration_all_event_transitions():
    """Requirement 4 & 8: Full FSM integration emitting SENSE_STARTED, SENSE_COMPLETE,

    TRIAGE_COMPLETE, ATTEMPT_X_FEEDBACK, and RUN_RESOLVED / RUN_HALTED.
    """
    emitted_events: List[dict] = []

    async def capture_broadcast(event_type: str, state: AgentState):
        emitted_events.append({"event": event_type, "status": state.status, "step": state.current_step})

    # Test 1: Clean run (Direct resolution)
    clean_state = AgentState(
        pr_url="https://github.com/org/repo/pull/1",
        repo_full_name="org/repo",
        pr_number=1,
    )
    final_clean = await run_visor_agent(clean_state, capture_broadcast)
    assert final_clean.is_resolved is True
    clean_event_types = [e["event"] for e in emitted_events]
    assert clean_event_types == ["SENSE_STARTED", "SENSE_COMPLETE", "RUN_RESOLVED"]

    # Test 2: Run with self-healing resolution
    emitted_events.clear()
    anomaly_state = AgentState(
        pr_url="https://github.com/org/repo/pull/2",
        repo_full_name="org/repo",
        pr_number=2,
        anomalies=[
            Anomaly(
                element_id="btn-checkout",
                defect_type=DefectType.OCCLUSION,
                visibility_ratio=0.55,
                iou_score=0.0,
            )
        ],
    )

    final_healed = await run_visor_agent(anomaly_state, capture_broadcast)
    assert final_healed.is_resolved is True
    healed_event_types = [e["event"] for e in emitted_events]
    assert healed_event_types == [
        "SENSE_STARTED",
        "SENSE_COMPLETE",
        "TRIAGE_COMPLETE",
        "ATTEMPT_1_FEEDBACK",
        "RUN_RESOLVED",
    ]

    # Test 3: Run with 3-Strike Halting (Failure)
    emitted_events.clear()
    failed_state = AgentState(
        pr_url="https://github.com/org/repo/pull/3",
        repo_full_name="org/repo",
        pr_number=3,
        anomalies=[
            Anomaly(
                element_id="btn-stubborn",
                defect_type=DefectType.OCCLUSION,
                visibility_ratio=0.40,
                iou_score=0.0,
            )
        ],
    )

    # Force verification failure across all attempts
    orch = VisorOrchestrator()

    async def mock_fail_verify(st: AgentState) -> AgentState:
        st.attempts.append(
            SelfHealingAttempt(
                attempt_number=st.attempt,
                patch_diff="bad-diff",
                verified_vr=0.50,
                passed=False,
            )
        )
        st.is_resolved = False
        st.transition_to(FSMStep.VERIFY)
        return st

    orch.step_5_verify = mock_fail_verify

    final_failed = await run_visor_agent(failed_state, capture_broadcast, orchestrator=orch)
    assert final_failed.is_resolved is False
    assert final_failed.status == RunStatus.FAILED
    failed_event_types = [e["event"] for e in emitted_events]
    assert failed_event_types == [
        "SENSE_STARTED",
        "SENSE_COMPLETE",
        "TRIAGE_COMPLETE",
        "ATTEMPT_1_FEEDBACK",
        "ATTEMPT_2_FEEDBACK",
        "ATTEMPT_3_FEEDBACK",
        "RUN_HALTED",
    ]
