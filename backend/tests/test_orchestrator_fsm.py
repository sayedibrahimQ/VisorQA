"""Deterministic Unit Tests: 5-Node FSM & 3-Strike Guardrail

Verifies SENSE -> TRIAGE -> DIAGNOSE -> PATCH -> VERIFY transitions,
failure halting, and best-scoring patch preservation without external APIs.
"""
import pytest

from backend.core.state import (
    AgentState,
    Anomaly,
    DOMBoundingBox,
    DefectType,
    FSMStep,
    RunStatus,
    SelfHealingAttempt,
)
from backend.core.orchestrator import VisorOrchestrator, run_visor_agent
import backend.core.orchestrator as orchestrator_module


def make_sample_anomaly() -> Anomaly:
    return Anomaly(
        element_id="visor-el-sample",
        defect_type=DefectType.OCCLUSION,
        visibility_ratio=0.55,
        iou_score=0.0,
        bounding_box=DOMBoundingBox(x=0, y=0, width=100, height=50),
    )


def make_test_state(**kwargs) -> AgentState:
    defaults = {
        "run_id": "fsm-unit-test",
        "repo_name": "sayedibrahimQ/VisorQA",
        "pr_number": 42,
        "branch": "feat/fsm-test",
        "commit_sha": "a1b2c3d4",
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


@pytest.mark.asyncio
async def test_fsm_five_node_resolution_flow():
    """Verify standard 5-node progression: SENSE -> TRIAGE -> DIAGNOSE -> PATCH -> VERIFY."""
    state = make_test_state(anomalies=[make_sample_anomaly()])
    events = []

    async def broadcast(envelope):
        events.append(envelope["event"] if isinstance(envelope, dict) else str(envelope))

    final = await run_visor_agent(state, ws_broadcast=broadcast)

    assert final.is_resolved is True
    assert final.attempt == 1
    assert final.status == RunStatus.RESOLVED
    assert len(final.attempts) == 1
    assert final.attempts[0].passed is True

    # Verify event sequence
    assert "SENSE_STARTED" in events
    assert "SENSE_COMPLETE" in events
    assert "TRIAGE_COMPLETE" in events
    assert "ATTEMPT_1_FEEDBACK" in events
    assert "RUN_RESOLVED" in events


@pytest.mark.asyncio
async def test_three_strike_guardrail_halts_and_preserves_best_patch(monkeypatch):
    """Verify 3-Strike Guardrail: halts at attempt 3, marks HALTED, keeps best score patch."""
    async def stubborn_sense(state, sandbox_runner=None, sam_client=None, resense=False):
        state.transition_to(FSMStep.SENSE, RunStatus.RUNNING)
        if not state.anomalies:
            state.anomalies = [make_sample_anomaly()]
        return state

    monkeypatch.setattr(
        orchestrator_module, "sense_with_playwright_and_sam", stubborn_sense
    )

    orchestrator = VisorOrchestrator()
    scores = iter([0.45, 0.92, 0.30])  # attempt 2 has the highest score (0.92)

    async def fake_patch(state):
        state.current_patch = f"patch-attempt-{state.attempt}"
        return state

    async def fake_verify(state):
        score = next(scores)
        state.attempts.append(
            SelfHealingAttempt(
                attempt_number=state.attempt,
                patch_diff=state.current_patch,
                verified_vr=score,
                verified_iou=0.0,
                passed=False,
            )
        )
        return await orchestrator_module.verify_with_sam(state)

    orchestrator.step_4_patch = fake_patch
    orchestrator.step_5_verify = fake_verify

    events = []

    async def broadcast(envelope):
        events.append(envelope["event"] if isinstance(envelope, dict) else str(envelope))

    state = make_test_state(anomalies=[make_sample_anomaly()])
    final = await run_visor_agent(state, ws_broadcast=broadcast, orchestrator=orchestrator)

    # Assert 3-strike halt requirements
    assert final.attempt == 3
    assert final.is_resolved is False
    assert final.status == RunStatus.FAILED
    assert len(final.attempts) == 3
    assert "RUN_HALTED" in events

    # Assert best patch preserved attempt 2's highest score (0.92), not attempt 3 (0.30)
    assert final.best_score == pytest.approx(0.92)
    assert final.best_patch == "patch-attempt-2"
