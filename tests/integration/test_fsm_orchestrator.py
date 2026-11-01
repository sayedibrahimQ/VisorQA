import pytest
from backend.core.state import AgentState, FSMStep, RunStatus, Anomaly, SelfHealingAttempt, DefectType
from backend.core.orchestrator import VisorOrchestrator


class CleanCaptureSandbox:
    """Test-provided capture evidence: one fully visible element, both viewports."""

    async def extract_dom_geometry(self, width, height):
        return [{
            "element_id": "visor-el-01", "visibility_ratio": 1.0, "v_r": 1.0,
            "iou_score": 0.0, "bleed_px": 0.0,
            "bounding_box": {"x": 10.0, "y": 10.0, "width": 100.0, "height": 40.0},
            "viewport": f"{width}px",
        }]

    async def capture_screenshot(self, width, height):
        return b""

@pytest.mark.asyncio
async def test_orchestrator_clean_run():
    state = AgentState(
        run_id="test-clean-01",
        repo_name="sayedibrahimQ/VisorQA",
        pr_number=1,
        branch="main",
        commit_sha="c0ffee"
    )
    orchestrator = VisorOrchestrator(sandbox_runner=CleanCaptureSandbox())
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
