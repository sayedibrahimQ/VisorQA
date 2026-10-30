"""Dual sandbox tests -- all run without Modal credentials (Sec 9)."""
import asyncio
import inspect
import os
import sys
import time
from pathlib import Path

import pytest

from backend.config import Settings
from backend.core.state import AgentState
from backend.sandbox import (
    HMRStatus,
    LocalSandboxRunner,
    ModalSandboxRunner,
    PatchPhase,
    SandboxConfigError,
    SandboxRunner,
    create_sandbox_runner,
)

FAKE_SERVER = Path(__file__).parents[1] / "fixtures" / "sandbox" / "fake_dev_server.py"


def make_diff(path, old, new):
    return (f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-{old}\n+{new}\n")


def write_source(tmp_path, content="hello v1\n"):
    src = tmp_path / "src-app"
    src.mkdir(exist_ok=True)
    (src / "page.txt").write_text(content)
    (src / "src").mkdir(exist_ok=True)
    (src / "src" / "components").mkdir(exist_ok=True)
    (src / "src" / "components" / "ui").mkdir(exist_ok=True)
    (src / "src" / "components" / "ui" / "button.tsx").write_text("button\n")
    return src


async def make_runner(tmp_path, start=True, **kw):
    src = write_source(tmp_path)
    runner = LocalSandboxRunner(base_dir=str(tmp_path / "sandboxes"), hmr_timeout=5, **kw)
    await runner.create_or_attach(
        "pr-1", source_dir=str(src), branch="main", commit_sha="abc123",
        authorized_files=["page.txt"],
        dev_command=[sys.executable, str(FAKE_SERVER)])
    if start:
        await runner.start_dev_server()
    return runner


# 1. Both adapters satisfy the shared interface
def test_both_adapters_satisfy_interface():
    for cls in (LocalSandboxRunner, ModalSandboxRunner):
        assert issubclass(cls, SandboxRunner)
        for name in ("create_or_attach", "start_dev_server", "apply_patch",
                     "wait_for_hmr", "get_status", "get_preview_url", "terminate"):
            assert inspect.iscoroutinefunction(getattr(cls, name)), (cls, name)


# 12/13. Modal imports + selection without credentials
def test_modal_import_and_selection_without_credentials(monkeypatch):
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("MODAL_TOKEN", raising=False)
    runner = ModalSandboxRunner()  # construction must not require creds
    assert runner.backend_name == "modal"


async def test_modal_without_credentials_actionable_error(monkeypatch):
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("MODAL_TOKEN", raising=False)
    runner = ModalSandboxRunner(modal_module=None)
    # Force SDK-present path to be irrelevant: credential error must name vars.
    with pytest.raises(SandboxConfigError) as exc:
        await runner.create_or_attach("s1", repo_url="https://example.com/x.git")
    assert "MODAL_TOKEN" in str(exc.value)
    assert "fallback" in str(exc.value).lower()


# 11. Backend configuration and switching
def test_backend_factory_defaults_local_and_rejects_invalid():
    assert isinstance(create_sandbox_runner(Settings(SANDBOX_BACKEND="local")), LocalSandboxRunner)
    assert isinstance(create_sandbox_runner(Settings(SANDBOX_BACKEND="modal")), ModalSandboxRunner)
    assert isinstance(create_sandbox_runner(Settings()), LocalSandboxRunner)  # default local
    with pytest.raises(SandboxConfigError, match="SANDBOX_BACKEND"):
        create_sandbox_runner(Settings(SANDBOX_BACKEND="bogus"))


# 2. Local creation and reuse
async def test_local_create_and_reuse(tmp_path):
    runner = await make_runner(tmp_path, start=False)
    status = await runner.get_status()
    assert status.working_dir and Path(status.working_dir, "page.txt").exists()
    assert status.branch == "main" and status.commit_sha == "abc123"
    again = await runner.create_or_attach("pr-1", branch="main")
    assert again.working_dir == status.working_dir  # attach, not recreate
    await runner.terminate()


# 3/4. Persistent process across multiple patches, no restart
async def test_persistent_server_multiple_patches_no_restart(tmp_path):
    runner = await make_runner(tmp_path)
    try:
        pid = (await runner.get_status()).server_pid
        url = await runner.get_preview_url()
        assert url and url.startswith("http://127.0.0.1:")
        for old, new in (("hello v1", "hello v2"), ("hello v2", "hello v3")):
            result = await runner.apply_patch(make_diff("page.txt", old, new))
            assert result.success and result.server_pid == pid and not result.server_restarted
            hmr = await runner.wait_for_hmr(result.patch_id, timeout=5)
            assert hmr.status == HMRStatus.OBSERVED, hmr
            assert (await runner.get_status()).server_pid == pid  # same process
        assert Path((await runner.get_status()).working_dir, "page.txt").read_text() == "hello v3\n"
        assert (await runner.get_status()).patch_count == 2
    finally:
        await runner.terminate()


# 5. Invalid patch rejection without filesystem changes
async def test_invalid_patch_rejected_no_fs_change(tmp_path):
    runner = await make_runner(tmp_path, start=False)
    try:
        target = Path((await runner.get_status()).working_dir, "page.txt")
        before = target.read_bytes()
        result = await runner.apply_patch("not a diff at all")
        assert not result.success and target.read_bytes() == before
    finally:
        await runner.terminate()


# 6. Unauthorized paths and traversal rejection
async def test_unauthorized_and_traversal_rejected(tmp_path):
    runner = await make_runner(tmp_path, start=False)
    try:
        workdir = Path((await runner.get_status()).working_dir)
        for bad in ("../escape.txt", "src/components/ui/button.tsx", "other.txt"):
            old = "x"
            content = (workdir / bad).read_text().strip() if (workdir / bad).exists() else old
            result = await runner.apply_patch(make_diff(bad, content, "pwned"))
            assert not result.success, bad
        assert not (workdir.parent / "escape.txt").exists()
        assert (workdir / "src/components/ui/button.tsx").read_text() == "button\n"
    finally:
        await runner.terminate()


# 7. Stale patch rejection and rollback state
async def test_stale_patch_rejected(tmp_path):
    runner = await make_runner(tmp_path, start=False)
    try:
        ok = await runner.apply_patch(make_diff("page.txt", "hello v1", "hello v2"))
        assert ok.success
        stale = await runner.apply_patch(make_diff("page.txt", "hello v1", "hello vX"))
        assert not stale.success  # context no longer matches
        workdir = Path((await runner.get_status()).working_dir)
        assert (workdir / "page.txt").read_text() == "hello v2\n"  # unchanged/rolled back
    finally:
        await runner.terminate()


# 8. Concurrent patch serialization
async def test_concurrent_patches_serialized(tmp_path):
    runner = await make_runner(tmp_path)
    try:
        r1, r2 = await asyncio.gather(
            runner.apply_patch(make_diff("page.txt", "hello v1", "hello A")),
            runner.apply_patch(make_diff("page.txt", "hello A", "hello B")),
            return_exceptions=True)
        results = [r for r in (r1, r2) if not isinstance(r, Exception)]
        assert any(r.success for r in results)  # serialized: at least first applies
        workdir = Path((await runner.get_status()).working_dir)
        assert (workdir / "page.txt").read_text() in ("hello A\n", "hello B\n")
    finally:
        await runner.terminate()


# 9. HMR success / timeout / compiler failure + stale-event guard
async def test_hmr_timeout_and_compile_failure_and_stale(tmp_path):
    runner = await make_runner(tmp_path)
    try:
        ok = await runner.apply_patch(make_diff("page.txt", "hello v1", "hello v2"))
        stale = await runner.wait_for_hmr(ok.patch_id + 99, timeout=1)
        assert stale.status == HMRStatus.STALE  # never attributed to newer patch
        bad = await runner.apply_patch(make_diff("page.txt", "hello v2", "SYNTAX_ERROR"))
        assert bad.success
        failed = await runner.wait_for_hmr(bad.patch_id, timeout=5)
        assert failed.status == HMRStatus.COMPILE_FAILED
        assert (await runner.get_status()).last_phase == PatchPhase.PATCH_APPLIED
    finally:
        await runner.terminate()


async def test_hmr_not_running():
    runner = LocalSandboxRunner(base_dir="/tmp/visorqa-test-notcreated")
    result = await runner.wait_for_hmr(timeout=0.2)
    assert result.status == HMRStatus.NOT_RUNNING


# 10. Recovery after process failure
async def test_recovery_after_crash(tmp_path):
    runner = await make_runner(tmp_path)
    try:
        pid = (await runner.get_status()).server_pid
        os.kill(pid, 9)
        for _ in range(50):
            if (await runner.get_status()).server_state.value == "crashed":
                break
            await asyncio.sleep(0.1)
        assert (await runner.get_status()).server_state.value == "crashed"
        recovered = await runner.recover()
        assert recovered.server_state.value == "running"
        assert recovered.server_pid != pid
        result = await runner.apply_patch(make_diff("page.txt", "hello v1", "hello back"))
        assert result.success
        assert (await runner.wait_for_hmr(result.patch_id, timeout=5)).observed
    finally:
        await runner.terminate()


# 14. State preservation + Node 5 handoff
async def test_state_sandbox_handoff_preserves_fields(tmp_path):
    from backend.core.orchestrator import _record_sandbox_state
    runner = await make_runner(tmp_path)
    try:
        state = AgentState(repo_full_name="o/r", pr_number=7, branch="main",
                           target_files=["page.txt"], current_patch="keepme")
        state.repair_spec = {"triage_status": "resolved", "root_cause": "x"}
        await _record_sandbox_state(state, runner)
        assert state.sandbox.preview_url and "127.0.0.1" in state.sandbox.preview_url
        assert state.sandbox.working_dir
        assert state.current_patch == "keepme"  # Node 4 patch preserved
        assert state.repair_spec["triage_status"] == "resolved"  # Node 2 preserved
        assert state.sandbox.visual_verified is False  # only Node 5 may set
    finally:
        await runner.terminate()


# 15. Cleanup and resource limits
async def test_cleanup_and_limits(tmp_path):
    runner = await make_runner(tmp_path, start=False, cpu_limit=1.0, memory_limit_mb=512)
    try:
        status = await runner.get_status()
        assert status.cpu_limit == 1.0 and status.memory_limit_mb == 512
        session_dir = Path(status.working_dir).parent
        assert session_dir.exists()
    finally:
        await runner.terminate()
    assert not session_dir.exists()  # explicit termination cleans up


# Timings are measured, not fabricated
async def test_timing_metrics_reported(tmp_path):
    runner = await make_runner(tmp_path)
    try:
        result = await runner.apply_patch(make_diff("page.txt", "hello v1", "hello v2"))
        assert result.timings.patch_validation_ms is not None
        assert result.timings.patch_apply_ms is not None
        hmr = await runner.wait_for_hmr(result.patch_id, timeout=5)
        assert hmr.latency_ms is not None and hmr.latency_ms >= 0
    finally:
        await runner.terminate()


# 14b. Node 4 -> sandbox -> Node 5 handoff through the real orchestrator node
async def test_node4_applies_via_sandbox_and_hands_to_node5(tmp_path):
    from backend.core.orchestrator import patch_muse_code_and_apply

    class FakeCode:
        async def generate_diff(self, context):
            return make_diff("page.txt", "hello v1", "hello v2")

    runner = await make_runner(tmp_path)
    try:
        state = AgentState(repo_full_name="o/r", pr_number=3, branch="main",
                           target_files=["page.txt"])
        state.repair_spec = {
            "triage_status": "resolved", "diagnose_status": "resolved",
            "root_cause": "banner overlaps", "affected_selectors": ["#x"],
            "target_file": "page.txt", "css_strategy": "adjust layout",
            "desktop_preservation_constraints": ["keep desktop"],
            "forbidden_hacks": ["!important"],
        }
        out = await patch_muse_code_and_apply(
            state, code_client=FakeCode(), sandbox_runner=runner)
        assert out.repair_spec["patch_status"] == "applied"
        assert out.repair_spec["hmr_status"] == "observed"
        assert out.current_patch  # exact normalized diff preserved
        assert out.modified_files == ["page.txt"]
        assert out.sandbox.preview_url and "127.0.0.1" in out.sandbox.preview_url
        assert out.sandbox.visual_verified is False  # Node 5 has not run
        assert out.is_resolved is False
        workdir = Path(out.sandbox.working_dir)
        assert (workdir / "page.txt").read_text() == "hello v2\n"
    finally:
        await runner.terminate()


# Modal adapter with an injected fake SDK: no credentials, no network.
async def test_modal_adapter_with_fake_sdk():
    import backend.sandbox.modal_runner as mr

    class FakeStream:
        def read(self):
            return "APPLIED compiled"

    class FakeProc:
        stdout = FakeStream()
        def wait(self):
            return 0

    class FakeTunnel:
        url = "https://fake-tunnel.example"

    class FakeSandbox:
        object_id = "sb-fake-1"
        def exec(self, *args, **kw):
            return FakeProc()
        def tunnels(self):
            return {3000: FakeTunnel()}
        def poll(self):
            return None
        def terminate(self):
            pass

    class FakeImage:
        def apt_install(self, *a):
            return self
        def run_commands(self, *a):
            return self

    class FakeModal:
        Image = type("I", (), {"debian_slim": staticmethod(lambda: FakeImage())})
        App = type("A", (), {"lookup": staticmethod(lambda name, create_if_missing=False: object())})
        Sandbox = type("S", (), {"create": staticmethod(lambda *a, **kw: FakeSandbox())})

    runner = mr.ModalSandboxRunner(modal_module=FakeModal())
    status = await runner.create_or_attach("sess", repo_url="")
    assert status.sandbox_id == "sb-fake-1"
    await runner.start_dev_server()
    assert await runner.get_preview_url() == "https://fake-tunnel.example"
    result = await runner.apply_patch(make_diff("page.txt", "a", "b"))
    assert result.success and result.files_changed == ["page.txt"]
    await runner.terminate()
    assert (await runner.get_status()).server_state.value == "stopped"
