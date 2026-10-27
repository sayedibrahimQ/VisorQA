"""Tests for the Jira contract: AgentState + run_visor_agent FSM.

Pure Python + asyncio + Pydantic only (ADR-001/TC-1).
"""
import pytest

import backend.core.orchestrator as orchestrator_module
from backend.core.orchestrator import VisorOrchestrator, run_visor_agent
from backend.core.state import AgentState, Anomaly, DefectType, FSMStep, RunStatus


def make_state(**overrides):
    kwargs = dict(
        pr_url="https://github.com/org/storefront/pull/42",
        repo_full_name="org/storefront",
        pr_number=42,
        branch="fix/checkout-banner",
        commit_sha="a1b2c3d",
    )
    kwargs.update(overrides)
    return AgentState(**kwargs)


def occluded():
    return Anomaly(
        element_id="visor-el-04",
        defect_type=DefectType.OCCLUSION,
        visibility_ratio=0.45,
        iou_score=0.16,
    )


async def test_agent_state_jira_defaults_and_mutable_isolation():
    a, b = make_state(), make_state()
    assert a.attempt == 0 and a.max_attempts == 3
    assert a.anomalies == [] and a.target_files == [] and a.repair_spec == {}
    assert a.current_patch == "" and a.best_patch == "" and a.best_score == 0.0
    assert a.is_resolved is False
    a.anomalies.append(occluded())
    a.target_files.append("src/app/CheckoutPage.tsx")
    assert b.anomalies == [] and b.target_files == []


async def test_clean_run_resolves_without_attempts():
    events = []

    async def broadcast(envelope):
        events.append(envelope)

    final = await run_visor_agent(make_state(), broadcast)
    assert final.is_resolved is True
    assert final.status == RunStatus.RESOLVED
    assert final.current_step == FSMStep.VERIFY
    assert final.attempt == 0
    assert [e["event"] for e in events] == [
        "SENSE_STARTED",
        "SENSE_COMPLETE",
        "RUN_RESOLVED",
    ]
    assert events[0]["state"]["pr_url"].endswith("/pull/42")


async def test_healing_loop_resolves_on_first_attempt_with_stub_adapters():
    events = []

    async def broadcast(envelope):
        events.append(envelope)

    final = await run_visor_agent(make_state(anomalies=[occluded()]), broadcast)
    assert final.is_resolved is True
    assert final.attempt == 1
    assert final.target_files == ["src/components/PromoBanner.tsx"]
    assert final.repair_spec["root_cause"]
    assert final.current_patch and final.best_patch == final.current_patch
    assert final.best_score == pytest.approx(1.0)
    assert [e["event"] for e in events] == [
        "SENSE_STARTED",
        "SENSE_COMPLETE",
        "TRIAGE_COMPLETE",
        "ATTEMPT_1_FEEDBACK",
        "RUN_RESOLVED",
    ]


async def test_three_strike_loop_halts_and_preserves_best_patch(monkeypatch):
    async def stubborn_sense(state, sandbox_runner=None, sam_client=None, resense=False):
        state.transition_to(FSMStep.SENSE, RunStatus.RUNNING)
        if not state.anomalies:
            state.anomalies = [occluded()]
        return state

    monkeypatch.setattr(
        orchestrator_module, "sense_with_playwright_and_sam", stubborn_sense
    )
    events = []

    async def broadcast(envelope):
        events.append(envelope)

    final = await run_visor_agent(make_state(anomalies=[occluded()]), broadcast)
    assert final.is_resolved is False
    assert final.status == RunStatus.FAILED
    assert final.attempt == 3 and len(final.attempts) == 3
    assert final.best_patch == final.current_patch
    assert [e["event"] for e in events] == [
        "SENSE_STARTED",
        "SENSE_COMPLETE",
        "TRIAGE_COMPLETE",
        "ATTEMPT_1_FEEDBACK",
        "ATTEMPT_2_FEEDBACK",
        "ATTEMPT_3_FEEDBACK",
        "RUN_HALTED",
    ]


async def test_best_patch_tracks_highest_score_not_last():
    orchestrator = VisorOrchestrator()
    scores = iter([0.6, 0.9, 0.7])

    async def fake_patch(state):
        state.current_patch = f"patch-attempt-{state.attempt}"
        return state

    async def fake_verify(state):
        from backend.core.state import SelfHealingAttempt

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
        events.append(envelope)

    final = await run_visor_agent(
        make_state(anomalies=[occluded()]), broadcast, orchestrator=orchestrator
    )
    assert final.attempt == 3 and final.is_resolved is False
    assert final.best_score == pytest.approx(0.9)
    assert final.best_patch == "patch-attempt-2"


async def test_no_agent_framework_imports():
    import pathlib

    source = pathlib.Path(orchestrator_module.__file__).read_text().lower()
    for banned in ("langchain", "crewai", "autogen"):
        assert f"import {banned}" not in source
        assert f"from {banned}" not in source
