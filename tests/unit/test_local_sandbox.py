"""LocalWorktreeSandboxRunner: VISOR-ENV-001/002 (isolated worktree + Playwright)."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

from backend.adapters.sandbox_runner import (
    LocalWorktreeSandboxRunner,
    list_repository_files,
)
from backend.config import Settings
from backend.core.state import AgentState

FAKE_SERVER = Path(__file__).parents[1] / "fixtures" / "sandbox" / "fake_dev_server.py"
TARGET = "src/components/PromoBanner.tsx"
ORIGINAL = (Path(__file__).parents[2] / "demo-target-app" / TARGET)


def _diff(path, old, new):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-{old}\n+{new}\n"


def _source(tmp_path):
    src = tmp_path / "source-app"
    (src / "src/components/ui").mkdir(parents=True)
    (src / "src/app/checkout").mkdir(parents=True)
    (src / "node_modules/pkg").mkdir(parents=True)
    (src / "node_modules/pkg/index.js").write_text("x\n")
    (src / TARGET).parent.mkdir(parents=True, exist_ok=True)
    (src / TARGET).write_text("hello v1\n")
    (src / "src/components/ui/Button.tsx").write_text("button\n")
    (src / "src/app/checkout/CheckoutPage.tsx").write_text("checkout\n")
    (src / "index.html").write_text("<html><body><button>Pay</button></body></html>\n")
    return src


async def _runner(tmp_path, source, start=False):
    r = LocalWorktreeSandboxRunner(base_dir=str(tmp_path / "sandboxes"), hmr_timeout=5)
    await r.create_or_attach("run-1", source_dir=str(source),
                             authorized_files=[TARGET],
                             dev_command=[sys.executable, str(FAKE_SERVER)])
    if start:
        await r.start_dev_server()
    return r


@pytest.mark.asyncio
async def test_isolated_workspace_repository_files_and_state_injection(tmp_path):
    src = _source(tmp_path)
    r = await _runner(tmp_path, src)
    try:
        files = r.repository_files()
        assert TARGET in files and "index.html" in files
        assert not any("node_modules" in f or f.startswith(".git") for f in files)
        state = AgentState(repo_full_name="o/r", pr_number=1, branch="main")
        state.repair_spec = {"triage_status": "resolved"}
        r.inject_state(state)
        for key in ("repo_root", "checkout_path", "workspace_dir"):
            assert state.repair_spec[key] == str(r.working_dir)
        assert state.repair_spec["repository_files"] == files
        assert state.repair_spec["triage_status"] == "resolved"  # not clobbered
        assert Path(state.repair_spec["repo_root"], TARGET).is_file()
    finally:
        await r.terminate()


@pytest.mark.asyncio
async def test_workspace_isolation_source_template_untouched(tmp_path):
    src = _source(tmp_path)
    before = hashlib.sha256((src / TARGET).read_bytes()).hexdigest()
    r = await _runner(tmp_path, src)
    try:
        res = await r.apply_patch(_diff(TARGET, "hello v1", "hello v2"))
        assert res.success
        assert (r.working_dir / TARGET).read_text() == "hello v2\n"
        assert hashlib.sha256((src / TARGET).read_bytes()).hexdigest() == before
    finally:
        await r.terminate()


@pytest.mark.asyncio
async def test_rollback_and_cleanup(tmp_path):
    src = _source(tmp_path)
    r = await _runner(tmp_path, src)
    session = r.working_dir.parent
    try:
        assert (await r.apply_patch(_diff(TARGET, "hello v1", "hello v2"))).success
        assert r.rollback("baseline")
        assert (r.working_dir / TARGET).read_text() == "hello v1\n"
    finally:
        await r.terminate()
    assert not session.exists()


@pytest.mark.asyncio
async def test_subprocess_lifecycle_no_leak(tmp_path):
    src = _source(tmp_path)
    r = await _runner(tmp_path, src, start=True)
    pid = (await r.get_status()).server_pid
    assert pid and Path(f"/proc/{pid}").exists()
    assert (await r.get_preview_url()).startswith("http://127.0.0.1:")
    await r.stop()
    assert not Path(f"/proc/{pid}").exists()


@pytest.mark.asyncio
async def test_path_containment_and_git_worktree(tmp_path):
    import subprocess as sp
    src = _source(tmp_path)
    sp.run(["git", "init", "-q", str(src)], check=True)
    sp.run(["git", "-C", str(src), "config", "user.email", "t@t.t"], check=True)
    sp.run(["git", "-C", str(src), "config", "user.name", "t"], check=True)
    sp.run(["git", "-C", str(src), "add", "-A"], check=True)
    sp.run(["git", "-C", str(src), "commit", "-qm", "init"], check=True)
    r = await _runner(tmp_path, src)
    try:
        assert r._used_worktree is True
        assert str(r.working_dir).startswith(str((tmp_path / "sandboxes").resolve())) or "sandboxes" in str(r.working_dir)
    finally:
        await r.terminate()
    assert sp.run(["git", "-C", str(src), "worktree", "list"], capture_output=True, text=True).stdout.count("\n") <= 1


def test_factory_provider_and_config_defaults():
    from backend.sandbox.factory import create_sandbox_runner
    assert Settings().SANDBOX_PROVIDER == "local"
    assert Settings().TARGET_APP_PATH == "./demo-target-app"
    assert Settings().TARGET_APP_PORT == 3001
    assert isinstance(create_sandbox_runner(Settings()), LocalWorktreeSandboxRunner)
    stub = create_sandbox_runner(Settings(SANDBOX_PROVIDER="stub"))
    assert stub.backend_name == "stub"


def test_demo_target_fixture_exists():
    root = Path(__file__).parents[2] / "demo-target-app"
    for rel in (TARGET, "src/app/checkout/CheckoutPage.tsx", "src/components/ui/Button.tsx"):
        assert (root / rel).is_file(), rel
    files = list_repository_files(root)
    assert TARGET in files and not any("node_modules" in f for f in files)


@pytest.mark.asyncio
async def test_live_playwright_dual_viewport(tmp_path):
    if not (Path("/tmp/ms-playwright").is_dir() or Path(os.path.expanduser("~/.cache/ms-playwright")).is_dir()
            or Path("/usr/bin/google-chrome").exists()):
        pytest.skip("no Chromium available")
    src = _source(tmp_path)
    r = LocalWorktreeSandboxRunner(base_dir=str(tmp_path / "sandboxes"), hmr_timeout=5)
    await r.create_or_attach("live-1", source_dir=str(src))
    try:
        await r.start_dev_server()
        result = await r.capture_dual_viewport()
        for name, size in (("mobile", (375, 812)), ("desktop", (1440, 900))):
            vp = result["viewports"][name]
            assert (vp["width"], vp["height"]) == size
            assert vp["screenshot_bytes"] > 100
            assert vp["elements"], name
            el = vp["elements"][0]
            assert el["bounding_box"]["width"] > 0
            assert el["c_x"] == pytest.approx(el["bounding_box"]["x"] + el["bounding_box"]["width"] / 2)
            assert "position" in el["computed_css"]
    finally:
        await r.terminate()


@pytest.mark.asyncio
async def test_e2e_node1_to_node5_handoff(tmp_path):
    """Node1 injects checkout, Node4 applies a real diff, Node5 verifies (no checkout error)."""
    from backend.core.orchestrator import patch_muse_code_and_apply, sense_with_playwright_and_sam, verify_with_sam

    src = _source(tmp_path)
    (src / TARGET).write_text('export const banner = "fixed";\n')
    r = LocalWorktreeSandboxRunner(base_dir=str(tmp_path / "sandboxes"), hmr_timeout=5)
    await r.create_or_attach("e2e-1", source_dir=str(src), authorized_files=[TARGET],
                             dev_command=[sys.executable, str(FAKE_SERVER)])
    await r.start_dev_server()
    try:
        state = AgentState(repo_full_name="o/r", pr_number=2, branch="main",
                           target_files=[TARGET])
        state = await sense_with_playwright_and_sam(state, sandbox_runner=r)
        assert state.repair_spec["repo_root"] == str(r.working_dir)
        assert TARGET in state.repair_spec["repository_files"]
        # Node2/3 metadata (as triage+diagnose would leave it)
        state.target_files = [TARGET]
        state.repair_spec.update({
            "diagnose_status": "resolved", "root_cause": "banner fixed",
            "affected_selectors": ["#promo"], "target_file": TARGET,
            "css_strategy": "make sticky", "desktop_preservation_constraints": ["keep desktop"],
            "forbidden_hacks": ["!important"]})

        class FakeCode:
            async def generate_diff(self, context):
                return ('--- a/src/components/PromoBanner.tsx\n+++ b/src/components/PromoBanner.tsx\n'
                        '@@ -1,1 +1,1 @@\n-export const banner = "fixed";\n+export const banner = "sticky";\n')

        state.attempt = 1
        state = await patch_muse_code_and_apply(state, code_client=FakeCode(), sandbox_runner=r)
        assert state.repair_spec["patch_status"] == "applied", state.repair_spec
        assert "repository checkout unavailable" not in str(state.repair_spec.get("patch_error", ""))
        assert (r.working_dir / TARGET).read_text() == 'export const banner = "sticky";\n'
        assert (src / TARGET).read_text() == 'export const banner = "fixed";\n'  # template untouched

        class FakeSam:
            async def generate_component_masks(self, screenshot, boxes):
                return []
        state = await verify_with_sam(state, sandbox_runner=r, sam_client=FakeSam())
        assert state.attempts and state.attempts[-1].attempt_number == 1
        assert state.sandbox.working_dir == str(r.working_dir)
    finally:
        await r.terminate()
