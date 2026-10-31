"""Worktree hydration: local worktree, API materialization, hash fallback."""
import subprocess
from pathlib import Path

import pytest

import backend.api.auth as auth_mod
import backend.core.worktree as worktree
from backend.core.artifacts import record_patch_hashes
from backend.core.state import AgentState


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin-repo"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True,
                       capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "T")
    git("remote", "add", "origin", "https://github.com/octo/visor.git")
    (repo / "src").mkdir()
    (repo / "src" / "App.tsx").write_text("export const App = () => null;\n")
    (repo / "src" / "components").mkdir()
    (repo / "src" / "components" / "ui").mkdir()
    (repo / "src" / "components" / "ui" / "Button.tsx").write_text("export const B=1;\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    git("checkout", "-qb", "feat/pr-branch")
    (repo / "src" / "App.tsx").write_text("export const App = () => <div/>;\n")
    git("commit", "-qam", "pr change")
    git("checkout", "-q", "main")
    return repo


@pytest.mark.asyncio
async def test_hydrate_local_worktree(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setenv("VISORQA_SANDBOX_ROOT", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(worktree, "_local_checkout_root", lambda: repo)
    result = await worktree.hydrate_pr_workspace(
        "run-wt-1", "octo/visor", "feat/pr-branch", 7, token="")
    assert result["strategy"] == "local_worktree"
    root = Path(result["root"])
    assert (root / "src" / "App.tsx").read_text().strip().endswith("<div/>;")
    files = result["repository_files"]
    assert "src/App.tsx" in files
    # Non-protected files sort before protected shared UI.
    assert files.index("src/App.tsx") < files.index("src/components/ui/Button.tsx")


@pytest.mark.asyncio
async def test_hydrate_github_api_materialization(tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("VISORQA_SANDBOX_ROOT", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(worktree, "_local_checkout_root", lambda: None)

    async def fake_api(method, path, token, client=None, **kwargs):
        if "/pulls/" in path and path.endswith("/files?per_page=100"):
            return 200, [{"filename": "src/App.tsx"}, {"filename": "README.md"}]
        if "/contents/src/App.tsx" in path:
            body = base64.b64encode(b"export const App = 1;\n").decode()
            return 200, {"encoding": "base64", "content": body}
        return 404, {}

    monkeypatch.setattr(auth_mod, "github_api", fake_api)
    result = await worktree.hydrate_pr_workspace(
        "run-wt-2", "octo/visor", "feat/x", 3, token="tok")
    assert result["strategy"] == "github_api"
    assert result["repository_files"] == ["src/App.tsx"]
    assert (Path(result["root"]) / "src" / "App.tsx").read_text().startswith("export")


def test_patch_hashes_use_repo_root_fallback(tmp_path):
    target = tmp_path / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before")
    state = AgentState(run_id="run-h", repo_name="o/r", pr_number=1,
                       target_files=["src/App.tsx"])
    state.repair_spec = {"repo_root": str(tmp_path)}
    record_patch_hashes(state, "pre")
    target.write_text("after")
    record_patch_hashes(state, "post")
    hashes = state.repair_spec["patch_file_hashes"]["src/App.tsx"]
    assert hashes["pre_sha256"] != hashes["post_sha256"]
    assert len(hashes["pre_sha256"]) == 64
