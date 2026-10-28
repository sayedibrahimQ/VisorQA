import pytest
from backend.core.state import AgentState, FSMStep, RunStatus, Anomaly, SelfHealingAttempt, DefectType
from backend.core.orchestrator import VisorOrchestrator

@pytest.mark.asyncio
async def test_orchestrator_clean_run():
    state = AgentState(
        run_id="test-clean-01",
        repo_name="sayedibrahimQ/VisorQA",
        pr_number=1,
        branch="main",
        commit_sha="c0ffee"
    )
    orchestrator = VisorOrchestrator()
    final_state = await orchestrator.execute_run(state)
    assert final_state.current_step == FSMStep.VERIFY
    assert final_state.status == RunStatus.RESOLVED

@pytest.mark.asyncio
async def test_orchestrator_healing_loop_resolution():
    updates = []
    async def track_update(st: AgentState):
        updates.append((st.current_step, st.status))

    state = AgentState(
        run_id="test-heal-01",
        repo_name="sayedibrahimQ/VisorQA",
        pr_number=2,
        branch="fix/hero",
        commit_sha="123abc4"
    )
    state.anomalies.append(
        Anomaly(
            id="anom-test-01",
            element_id="btn-01",
            defect_type=DefectType.OCCLUSION,
            visibility_ratio=0.5,
            iou_score=0.0
        )
    )

    orchestrator = VisorOrchestrator(on_state_change=track_update)
    
    async def mock_step_4_patch(st: AgentState) -> AgentState:
        st.attempts.append(
            SelfHealingAttempt(
                attempt_number=st.strike_count + 1,
                patch_diff="--- a/btn.tsx\n+++ b/btn.tsx\n@@ -1 +1 @@\n-z-0\n+z-10",
                verified_vr=0.98,
                verified_iou=0.0,
                passed=True
            )
        )
        return st

    orchestrator.step_4_patch = mock_step_4_patch
    final_state = await orchestrator.execute_run(state)

    assert final_state.status == RunStatus.RESOLVED
    assert len(final_state.attempts) == 1
    assert final_state.attempts[0].passed is True
    assert len(updates) > 0
