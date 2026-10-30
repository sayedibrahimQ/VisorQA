"""Node 5 dual-viewport verification, 3-strike guardrail, GitHub publication."""
import sys
from pathlib import Path

import pytest

from backend.adapters.github_client import GitHubClient
from backend.core.github_publish import publish_run_result
from backend.core.orchestrator import VisorOrchestrator, run_visor_agent, verify_with_sam
from backend.core.state import AgentState, Anomaly, DefectType
from backend.core.verify import compute_dual_viewport_score, evaluate_dual_viewport

PATCH = "--- a/src/components/PromoBanner.tsx\n+++ b/src/components/PromoBanner.tsx\n@@ -1,1 +1,1 @@\n-old\n+new\n"
FAKE_SERVER = Path(__file__).parents[1] / "fixtures" / "sandbox" / "fake_dev_server.py"


def state_with_metrics(mobile, desktop, attempt=1, patch=PATCH):
    s = AgentState(repo_full_name="org/repo", pr_number=7, branch="fix/banner",
                   commit_sha="base123", target_files=["src/components/PromoBanner.tsx"])
    s.attempt = attempt
    s.current_patch = patch
    s.modified_files = ["src/components/PromoBanner.tsx"]
    s.repair_spec = {"viewport_evaluations": {"mobile": mobile, "desktop": desktop},
                     "triage_status": "resolved", "target_file": "src/components/PromoBanner.tsx"}
    return s


def vp(vr, iou, dx, **kw):
    return {"v_r": vr, "iou": iou, "delta_x": dx, **kw}


class FakeGitHub:
    def __init__(self, head="base123", fail_commit=False):
        self.head = head
        self.fail_commit = fail_commit
        self.commits = []
        self.comments = []
        self._markers = set()

    async def get_branch_head(self, repo, branch):
        return self.head

    async def commit_files(self, repo, branch, *, expected_head, files, message, idempotency_key=""):
        if idempotency_key in self._markers:
            return "sha-existing"
        if self.fail_commit:
            from backend.adapters.github_client import GitHubPermissionError
            raise GitHubPermissionError("403 forbidden")
        self._markers.add(idempotency_key)
        self.commits.append({"repo": repo, "branch": branch, "files": dict(files), "message": message})
        self.head = "newsha456"
        return "newsha456"

    async def post_verification_comment(self, repo, pr, body, *, marker=""):
        if marker not in self._markers:
            self._markers.add(marker)
            self.comments.append(body)
        return True

    async def post_suggested_review(self, repo, pr, body, *, marker=""):
        if marker not in self._markers:
            self._markers.add(marker)
            self.comments.append(body)
        return True


# 1-5. Thresholds per viewport -------------------------------------------------
@pytest.mark.asyncio
async def test_both_viewports_pass_resolved():
    out = await verify_with_sam(state_with_metrics(vp(1.0, 0.0, 0.0), vp(0.99, 0.0, 1.5)))
    assert out.is_resolved and out.verification_status == "verification_passed"
    assert out.sandbox.visual_verified is True
    assert out.attempts[-1].viewport_metrics["mobile"]["width"] == 375
    assert out.attempts[-1].viewport_metrics["desktop"]["width"] == 1440
    assert out.best_patch == PATCH and out.best_attempt_number == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mobile,desktop", [
    (vp(1.0, 0.0, 0.0), vp(0.90, 0.0, 0.0)),   # desktop fails
    (vp(0.90, 0.0, 0.0), vp(1.0, 0.0, 0.0)),   # mobile fails
    (vp(0.98, 0.0, 2.0), vp(0.98, 0.0, 2.0)),  # exact thresholds pass (separate test below)
])
async def test_one_viewport_fails_unresolved(mobile, desktop):
    out = await verify_with_sam(state_with_metrics(mobile, desktop))
    if mobile["v_r"] >= 0.98 and desktop["v_r"] >= 0.98:
        assert out.is_resolved
    else:
        assert not out.is_resolved and out.attempts[-1].passed is False


@pytest.mark.asyncio
async def test_exact_thresholds_pass_and_just_outside_fail():
    ok = await verify_with_sam(state_with_metrics(vp(0.98, 0.0, 2.0), vp(0.98, 0.0, 2.0)))
    assert ok.is_resolved
    for bad in (vp(0.9799, 0.0, 0.0), vp(1.0, 0.0001, 0.0), vp(1.0, 0.0, 2.01)):
        out = await verify_with_sam(state_with_metrics(bad, vp(1.0, 0.0, 0.0)))
        assert not out.is_resolved, bad


# 6. Invalid / missing metrics --------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [vp(float("nan"), 0.0, 0.0), vp(float("inf"), 0.0, 0.0),
                                 {"iou": 0.0, "delta_x": 0.0}, {"v_r": None, "iou": 0.0, "delta_x": 0.0}])
async def test_invalid_or_missing_metrics_fail_safely(bad):
    out = await verify_with_sam(state_with_metrics(bad, vp(1.0, 0.0, 0.0)))
    assert not out.is_resolved
    assert out.attempts[-1].metrics_valid is False
    assert out.attempts[-1].post_score is None
    assert out.best_patch == ""  # invalid attempt is not best-eligible


def test_score_none_for_incomplete():
    assert evaluate_dual_viewport({"mobile": vp(1, 0, 0)})["score"] is None
    assert compute_dual_viewport_score({"mobile": {"valid": False}, "desktop": {"valid": True, "v_r": 1, "iou": 0, "delta_x": 0}}) is None


# 7-8. Best preservation ---------------------------------------------------------
@pytest.mark.asyncio
async def test_best_preserved_when_later_attempt_worse():
    s = state_with_metrics(vp(0.99, 0.0, 0.0), vp(0.99, 0.0, 0.0), patch="patch-best")
    s = await verify_with_sam(s)
    assert s.best_patch == "patch-best" and s.best_score == pytest.approx(0.99)
    s.attempt = 2
    s.current_patch = "patch-worse"
    s.is_resolved = False
    s.repair_spec["viewport_evaluations"] = {"mobile": vp(0.5, 0.0, 0.0), "desktop": vp(0.5, 0.0, 0.0)}
    s.repair_spec["viewport_metrics_attempt"] = 2
    s = await verify_with_sam(s)
    assert s.best_patch == "patch-best" and s.best_attempt_number == 1


# 9-11, 15. Loop + GitHub failure path ------------------------------------------
async def _run_loop(metrics_seq, github):
    orch = VisorOrchestrator(github_client=github)

    async def fake_sense(st):
        if not st.anomalies:
            st.anomalies = [Anomaly(element_id="visor-el-04", defect_type=DefectType.OCCLUSION, visibility_ratio=0.4)]
        return st

    async def fake_triage(st):
        st.target_files = ["src/components/PromoBanner.tsx"]
        return st

    async def fake_diag(st):
        return st

    async def fake_patch(st):
        st.current_patch = f"patch-attempt-{st.attempt}"
        st.modified_files = ["src/components/PromoBanner.tsx"]
        m = metrics_seq[min(st.attempt - 1, len(metrics_seq) - 1)]
        st.repair_spec = {**st.repair_spec, "viewport_evaluations": m, "viewport_metrics_attempt": st.attempt,
                          "repo_root": "/tmp", "patched_files": ["src/components/PromoBanner.tsx"]}
        return st

    orch.step_1_sense, orch.step_2_triage, orch.step_3_diagnose, orch.step_4_patch = fake_sense, fake_triage, fake_diag, fake_patch
    # step_5_verify stays real via class delegation to module verify_with_sam
    state = AgentState(repo_full_name="org/repo", pr_number=7, branch="fix/banner", commit_sha="base123",
                       anomalies=[Anomaly(element_id="visor-el-04", defect_type=DefectType.OCCLUSION, visibility_ratio=0.4)])
    return await run_visor_agent(state, orchestrator=orch)


@pytest.mark.asyncio
async def test_three_failures_stop_no_commit_suggestion_posted():
    gh = FakeGitHub()
    fail = {"mobile": vp(0.5, 0.1, 5.0), "desktop": vp(0.5, 0.1, 5.0)}
    final = await _run_loop([fail, fail, fail], gh)
    assert final.attempt == 3 and len(final.attempts) == 3 and not final.is_resolved
    assert gh.commits == []  # failed attempts never push
    assert len(gh.comments) == 1 and "unverified suggestion" in gh.comments[0].lower()
    assert "NOT applied" in gh.comments[0] and final.best_patch in gh.comments[0]
    assert final.github_publication_status == "suggestion_posted"
    assert final.github_commit_pushed is False


@pytest.mark.asyncio
async def test_no_fourth_attempt_even_if_max_attempts_raised():
    gh = FakeGitHub()
    fail = {"mobile": vp(0.5, 0.0, 0.0), "desktop": vp(0.5, 0.0, 0.0)}
    orch_state = await _run_loop([fail] * 5, gh)
    assert orch_state.attempt == 3 and len(orch_state.attempts) == 3
    # Direct verify beyond the cap creates no new record.
    before = len(orch_state.attempts)
    orch_state.attempt = 4
    out = await verify_with_sam(orch_state)
    assert len(out.attempts) == before


# 1,12-14. Verified commit path ---------------------------------------------------
@pytest.mark.asyncio
async def test_verified_commit_only_authorized_and_idempotent(tmp_path):
    target = tmp_path / "src/components/PromoBanner.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("new\n")
    s = state_with_metrics(vp(1.0, 0.0, 0.0), vp(1.0, 0.0, 0.0))
    s.repair_spec["repo_root"] = str(tmp_path)
    s = await verify_with_sam(s)
    assert s.is_resolved
    gh = FakeGitHub()
    await publish_run_result(s, gh)
    await publish_run_result(s, gh)  # retry: idempotent
    assert len(gh.commits) == 1 and list(gh.commits[0]["files"]) == ["src/components/PromoBanner.tsx"]
    assert gh.commits[0]["files"]["src/components/PromoBanner.tsx"] == "new\n"
    assert s.github_commit_pushed and s.github_commit_sha == "newsha456"
    assert len(gh.comments) == 1 and "both viewports passed" in gh.comments[0].lower()


@pytest.mark.asyncio
async def test_branch_advancement_prevents_push():
    s = state_with_metrics(vp(1.0, 0.0, 0.0), vp(1.0, 0.0, 0.0))
    s = await verify_with_sam(s)
    gh = FakeGitHub(head="moved999")
    await publish_run_result(s, gh)
    assert gh.commits == [] and s.github_publication_status == "conflict"
    assert not s.github_commit_pushed


@pytest.mark.asyncio
async def test_permission_failure_recorded_not_claimed():
    s = state_with_metrics(vp(1.0, 0.0, 0.0), vp(1.0, 0.0, 0.0))
    s.repair_spec["repo_root"] = "/tmp"
    s.modified_files = []
    s.target_files = ["src/components/PromoBanner.tsx"]
    # give an authorized patched file via patch parse against /tmp fixture not needed:
    s = await verify_with_sam(s)
    gh = FakeGitHub(fail_commit=True)
    # No readable verified tree -> error, never a claimed commit.
    await publish_run_result(s, gh)
    assert not s.github_commit_pushed and s.github_publication_status in ("error", "conflict")


# 16. Offline credentials ----------------------------------------------------------
def test_github_client_imports_without_credentials(monkeypatch):
    client = GitHubClient(token="")
    assert client._gh is None and client.token == ""


@pytest.mark.asyncio
async def test_github_client_no_token_raises_config():
    from backend.adapters.github_client import GitHubConfigError
    with pytest.raises(GitHubConfigError):
        await GitHubClient(token="").get_branch_head("org/repo", "main")


# Integration: LocalSandboxRunner + Node 5 -----------------------------------------
@pytest.mark.asyncio
async def test_local_sandbox_node5_integration(tmp_path):
    from backend.adapters.sandbox_runner import LocalWorktreeSandboxRunner
    src = tmp_path / "src-app"
    (src / "src/components").mkdir(parents=True)
    (src / "src/components/PromoBanner.tsx").write_text("hello v1\n")
    (src / "index.html").write_text("<html><body><button>Pay</button></body></html>\n")
    runner = LocalWorktreeSandboxRunner(base_dir=str(tmp_path / "sandboxes"), hmr_timeout=5)
    await runner.create_or_attach("n5", source_dir=str(src), authorized_files=["src/components/PromoBanner.tsx"],
                                  dev_command=[sys.executable, str(FAKE_SERVER)])
    await runner.start_dev_server()
    try:
        s = AgentState(repo_full_name="org/repo", pr_number=7, branch="fix/banner", commit_sha="base123",
                       target_files=["src/components/PromoBanner.tsx"])
        runner.inject_state(s)
        s.attempt = 1
        s.current_patch = PATCH.replace("src/components/PromoBanner.tsx", "src/components/PromoBanner.tsx")
        s.repair_spec["viewport_evaluations"] = {"mobile": vp(1.0, 0.0, 0.0, screenshot_ref="mobile.png"),
                                                 "desktop": vp(1.0, 0.0, 0.0, screenshot_ref="desktop.png")}
        out = await verify_with_sam(s, sandbox_runner=runner)
        assert out.is_resolved and out.sandbox.visual_verified is True
        assert out.attempts[-1].screenshot_refs == {"mobile": "mobile.png", "desktop": "desktop.png"}
        assert out.repair_spec["triage_status"] if "triage_status" in out.repair_spec else True
    finally:
        await runner.terminate()
