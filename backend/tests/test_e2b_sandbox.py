"""E2B cloud sandbox: provider resolution, fallback, telemetry, cleanup.

The E2B SDK is faked at the module boundary — no credits are spent and no
network is used. Fallback tests assert a judge's scan never crashes when
E2B is missing a key or provisioning fails.
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.core.worktree as worktree
from backend.adapters.sandbox_runner import E2BSandboxRunner, LocalWorktreeSandboxRunner
from backend.sandbox.factory import create_sandbox_runner


def _cfg(**overrides):
    base = dict(
        SANDBOX_PROVIDER="", SANDBOX_BACKEND="", E2B_API_KEY="",
        E2B_SANDBOX_TIMEOUT_SECONDS=180, TARGET_APP_PATH="./demo-target-app",
        TARGET_APP_PORT=3001, SANDBOX_LOCAL_ROOT="", SANDBOX_HMR_TIMEOUT_SECONDS=15.0,
        SANDBOX_IDLE_TIMEOUT_SECONDS=1800.0, SANDBOX_CPU_LIMIT=None,
        SANDBOX_MEMORY_LIMIT_MB=None, MODAL_TOKEN_ID="", MODAL_TOKEN_SECRET="",
        MODAL_TOKEN="", MODAL_APP_NAME="visorqa-sandbox",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _state(run_id):
    return SimpleNamespace(run_id=run_id, repair_spec={}, sandbox=SimpleNamespace())


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "app-src"
    (src / "src").mkdir(parents=True)
    (src / "src" / "App.tsx").write_text("export const App = () => null;\n")
    (src / "index.html").write_text("<html><body>ok</body></html>\n")
    return src


class _FakeFiles:
    def __init__(self):
        self.written = []

    async def write(self, path, data):
        self.written.append(path)


class _FakeCommands:
    async def run(self, *args, **kwargs):
        return SimpleNamespace(stdout="", stderr="", exit_code=0)


class _FakeSandbox:
    sandbox_id = "sbx1234567890abcdef"
    killed = False

    def __init__(self):
        self.files = _FakeFiles()
        self.commands = _FakeCommands()

    def get_host(self, port):
        return f"port-{port}.e2b.dev"

    async def kill(self):
        _FakeSandbox.killed = True


def _install_fake_e2b(monkeypatch, create_impl):
    module = types.ModuleType("e2b")

    class _AsyncSandbox:
        @staticmethod
        async def create(**kwargs):
            return create_impl(**kwargs)

    module.AsyncSandbox = _AsyncSandbox
    monkeypatch.setitem(sys.modules, "e2b", module)


# -- provider resolution ----------------------------------------------------

def test_factory_explicit_providers():
    assert isinstance(create_sandbox_runner(_cfg(SANDBOX_PROVIDER="local")),
                      LocalWorktreeSandboxRunner)
    assert isinstance(create_sandbox_runner(_cfg(SANDBOX_PROVIDER="e2b", E2B_API_KEY="k")),
                      E2BSandboxRunner)


def test_factory_auto_provider_from_key_presence():
    assert isinstance(create_sandbox_runner(_cfg(E2B_API_KEY="k")), E2BSandboxRunner)
    local = create_sandbox_runner(_cfg())
    assert isinstance(local, LocalWorktreeSandboxRunner)
    assert not isinstance(local, E2BSandboxRunner)


# -- fallback -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_api_key_falls_back_to_local(tmp_path):
    src = _source(tmp_path)
    runner = E2BSandboxRunner(source_dir=str(src), api_key=None)
    # api_key=None resolves from settings; force the no-key branch.
    runner._api_key = None
    try:
        root = await runner.ensure_workspace(_state("run-e2b-nokey"), "run-e2b-nokey")
        assert Path(root).exists()
        assert runner.provider_label == "LOCAL WORKTREE SANDBOX"
        assert not runner.e2b_active
        assert runner.sandbox_id == ""
    finally:
        await runner.terminate()


@pytest.mark.asyncio
async def test_provisioning_failure_falls_back_to_local(tmp_path, monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("e2b down")

    _install_fake_e2b(monkeypatch, _boom)
    src = _source(tmp_path)
    runner = E2BSandboxRunner(source_dir=str(src), api_key="test-key")
    try:
        root = await runner.ensure_workspace(_state("run-e2b-fail"), "run-e2b-fail")
        assert Path(root).exists()
        assert runner.provider_label == "LOCAL WORKTREE SANDBOX"
        assert "provisioning failed" in runner._fallback_reason
    finally:
        await runner.terminate()


# -- successful mocked E2B ------------------------------------------------------

@pytest.mark.asyncio
async def test_mocked_e2b_provisioning_telemetry_and_cleanup(tmp_path, monkeypatch):
    holder = {}

    def _create(**kwargs):
        holder["kwargs"] = kwargs
        holder["sandbox"] = _FakeSandbox()
        return holder["sandbox"]

    _install_fake_e2b(monkeypatch, _create)
    _FakeSandbox.killed = False
    src = _source(tmp_path)
    runner = E2BSandboxRunner(source_dir=str(src), api_key="test-key", sandbox_timeout=180)
    try:
        await runner.ensure_workspace(_state("run-e2b-ok"), "run-e2b-ok")
        assert runner.e2b_active
        assert runner.sandbox_id == "sbx1234567890abcdef"
        assert runner.provider_label == "E2B CLOUD SANDBOX (sbx_sbx123456789)"
        assert holder["kwargs"]["timeout"] == 180
        assert holder["sandbox"].files.written, "workspace files uploaded to E2B"
        status = await runner.get_status()
        assert status.sandbox_id == "sbx1234567890abcdef"
        assert status.backend.startswith("E2B CLOUD SANDBOX")
    finally:
        await runner.terminate()
    assert _FakeSandbox.killed, "sandbox.kill() called during terminate"
    assert runner._sandbox is None


# -- hydration: backend-only PR still yields a real frontend target -------------

@pytest.mark.asyncio
async def test_api_materialize_backend_only_pr_uses_tree_frontend(tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("VISORQA_SANDBOX_ROOT", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(worktree, "_local_checkout_root", lambda: None)

    contents = {
        "frontend/src/components/ui/Button.tsx": "export const B=1;\n",
        "frontend/src/components/landing/SiteHeader.tsx": "export const H=1;\n",
    }

    async def fake_api(method, path, token, client=None, **kwargs):
        if "/pulls/" in path and path.endswith("/files?per_page=100"):
            return 200, [{"filename": "backend/main.py"}, {"filename": "README.md"}]
        if "/git/trees/" in path:
            return 200, {"tree": [
                {"type": "blob", "path": p} for p in contents
            ] + [{"type": "blob", "path": "backend/main.py"}]}
        for rel, text in contents.items():
            if f"/contents/{rel}?" in path:
                return 200, {"encoding": "base64",
                             "content": base64.b64encode(text.encode()).decode()}
        return 404, {}

    monkeypatch.setattr("backend.api.auth.github_api", fake_api)
    dest = tmp_path / "ws"
    dest.mkdir()
    written = await worktree._api_materialize(dest, "octo/visor", "main", 7, "tok")
    assert "frontend/src/components/landing/SiteHeader.tsx" in written
    # Non-protected target materialized before the protected shared UI file.
    assert written.index("frontend/src/components/landing/SiteHeader.tsx") < \
        written.index("frontend/src/components/ui/Button.tsx")
    assert (dest / "frontend/src/components/landing/SiteHeader.tsx").exists()
