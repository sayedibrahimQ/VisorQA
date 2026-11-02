"""Regressions: wrapper collisions, PATCH->VERIFY healing, auto-publish."""
import io

import pytest
from PIL import Image

from backend.core.sense import combine_sam_metrics, render_sam_mask_overlay
from backend.core.state import AgentState, Anomaly, DefectType

TARGET = "src/components/CheckoutPage.tsx"
ORIGINAL = (
    'export function CheckoutPage(){return(<div>'
    '<div id="promo-banner" data-visor-id="visor-el-04" className="fixed bottom-0 z-50">SALE</div>'
    '<button id="checkout-submit-btn" data-visor-id="visor-el-09">CONFIRM & PAY $189.00</button>'
    '</div>)}\n')
DIFF = (
    f"--- a/{TARGET}\n+++ b/{TARGET}\n@@ -1,1 +1,1 @@\n"
    f"-{ORIGINAL.rstrip()}\n"
    '+' + ORIGINAL.rstrip().replace('className="fixed bottom-0 z-50"', 'className="relative z-10 mb-3"') + "\n")


def _geo(eid, x, y, w, h, vr=1.0, **kw):
    return {"element_id": eid, "visor_el_id": eid, "visor_tagged": True,
            "visibility_ratio": vr, "bounding_box": {"x": x, "y": y, "width": w, "height": h}, **kw}


def test_wrapper_container_never_collides_only_leaf_pair():
    geo = [
        _geo("visor-el-03", 0, 0, 375, 812),  # outer wrapper encloses everything
        _geo("visor-el-04", 0, 700, 375, 80, dom_id="promo-banner"),
        _geo("visor-el-09", 20, 720, 335, 56, vr=0.4, dom_id="checkout-submit-btn"),
    ]
    out = combine_sam_metrics(geo, [], 375, 812)
    # Leaf pair 04/09 overlaps: inter=335*56, union=30000+18760-inter
    assert out["iou"] == pytest.approx(18760 / 30000, abs=1e-3)
    assert set(out.get("colliding_ids") or []) == {"visor-el-04", "visor-el-09"}


def test_contained_leaf_inside_wrapper_is_not_collision():
    geo = [_geo("visor-el-03", 0, 0, 375, 812), _geo("visor-el-09", 20, 720, 335, 56)]
    out = combine_sam_metrics(geo, [], 375, 812)
    assert out["iou"] == 0.0


def test_mask_highlights_only_colliding_leaves():
    shot = Image.new("RGB", (375, 812), (255, 255, 255))
    buf = io.BytesIO()
    shot.save(buf, format="PNG")
    elements = [_geo("visor-el-03", 0, 0, 375, 812), _geo("visor-el-04", 0, 700, 375, 80),
                _geo("visor-el-09", 20, 720, 335, 56)]
    anomalies = [{"element_id": "visor-el-03", "secondary_el_id": "visor-el-09"},
                 {"element_id": "visor-el-04", "secondary_el_id": "visor-el-09"}]
    out = Image.open(io.BytesIO(render_sam_mask_overlay(buf.getvalue(), elements, anomalies, 375, 812))).convert("RGB")
    assert out.getpixel((10, 10)) == (255, 255, 255)  # wrapper-only area untouched
    r, g, b = out.getpixel((10, 710))  # inside promo banner only
    assert g < 230 and b < 230  # crimson fill blended over white


def _state(tmp_path):
    p = tmp_path / TARGET
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ORIGINAL)
    return AgentState(run_id="run-x", repo_full_name="sayedibrahimQ/aether-hardware", pr_number=2,
        branch="feat/mobile", attempt=1, target_files=[TARGET],
        anomalies=[Anomaly(element_id="visor-el-09", defect_type=DefectType.COLLISION,
                           visibility_ratio=0.4, iou_score=0.6, viewport="375px", secondary_el_id="visor-el-04")],
        repair_spec={"repo_root": str(tmp_path), "repository_files": [TARGET], "diagnose_status": "resolved",
                     "root_cause": "fixed banner occludes CTA", "affected_selectors": ["#promo-banner"],
                     "target_file": TARGET, "css_strategy": "relative z-10 mb-3",
                     "desktop_preservation_constraints": ["keep desktop"], "forbidden_hacks": ["!important"]})


class _FakeCode:
    async def generate_diff(self, ctx): return DIFF


@pytest.mark.asyncio
async def test_patch_detects_lying_sandbox_and_mutates_serving_file(tmp_path):
    from backend.core.orchestrator import patch_muse_code_and_apply
    from backend.sandbox.interface import HMRResult, HMRStatus, PatchResult, SandboxStatus

    class LyingSandbox:
        working_dir = tmp_path
        async def get_status(self): return SandboxStatus(working_dir=str(tmp_path))
        async def get_preview_url(self): return "http://127.0.0.1:9"
        async def apply_patch(self, text, *, authorized_files=None):
            return PatchResult(success=True, patch_id=1, files_changed=[TARGET])  # does NOT write
        async def wait_for_hmr(self, pid=None): return HMRResult(status=HMRStatus.OBSERVED, patch_id=1, latency_ms=1)

    out = await patch_muse_code_and_apply(_state(tmp_path), code_client=_FakeCode(), sandbox_runner=LyingSandbox())
    assert out.repair_spec["patch_status"] == "applied", out.repair_spec
    assert 'className="relative z-10 mb-3"' in (tmp_path / TARGET).read_text()
    assert out.repair_spec.get("patch_verified_on_disk") is True


@pytest.mark.asyncio
async def test_publish_commits_exact_message_and_saves_urls(tmp_path):
    from backend.core.github_publish import publish_run_result
    (tmp_path / TARGET).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / TARGET).write_text(ORIGINAL.replace("fixed bottom-0 z-50", "relative z-10 mb-3"))
    s = _state(tmp_path)
    s.is_resolved = True
    s.current_patch = DIFF
    s.best_patch = DIFF
    s.best_attempt_number = 1
    s.modified_files = [TARGET]
    s.commit_sha = "base123"
    s.best_viewport_metrics = {"mobile": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0},
                               "desktop": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0}}
    s.repair_spec.update({"repo_root": str(tmp_path),
        "baseline_viewport_evaluations": {"mobile": {"v_r": 0.4, "iou": 0.62, "delta_x": 0.0},
                                          "desktop": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0}}})

    class Comment:
        html_url = "https://github.com/sayedibrahimQ/aether-hardware/issues/2#issuecomment-9"

    class GH:
        async def get_branch_head(self, r, b):
            return "base123"

        async def commit_files(self, repo, branch, *, expected_head, files, message, idempotency_key=""):
            self.message = message
            self.files = files
            return "newsha456"

        async def post_verification_comment(self, repo, pr, body, *, marker=""):
            self.body = body
            return Comment()

    gh = GH()
    out = await publish_run_result(s, gh)
    assert gh.message.startswith("fix(visorqa): resolve mobile promo banner z-index occlusion")
    assert out.github_commit_sha == "newsha456"
    assert out.github_commit_url.endswith("/commit/newsha456")
    assert out.pr_comment_url.endswith("#issuecomment-9")
    for needle in ("RESOLVED on Strike 1/3", "375x812", "1440x900", "V_r", TARGET, "Button.tsx", "BR-2", "```diff", "newsha456"):
        assert needle in gh.body, needle
