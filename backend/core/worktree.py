"""PR worktree hydration for dispatched scans (live diff generation).

Materializes the selected repository at the PR branch into an isolated
workspace so Node 2 triage sees a real file tree, Node 3 targets a real
file, and Node 4 applies a context-verified diff to real bytes:

1. Local checkout match: `git worktree add` from the current clone when
   its origin is the requested repo (no network, no token in URLs).
2. Shallow clone with the caller's GitHub token (x-access-token).
3. GitHub API materialization: PR-changed frontend files (or the repo
   tree) fetched via contents API into the workspace.

Scratch workspaces live under /tmp/visorqa_sandboxes/{run_id} and are
never the user's own working tree.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.core.triage import is_protected_path, normalize_path

FRONTEND_EXTS = (".tsx", ".jsx", ".ts", ".js", ".css", ".scss")
MAX_FILES = 120


def sandbox_root() -> Path:
    raw = (os.environ.get("VISORQA_SANDBOX_ROOT")
           or os.environ.get("VISORQA_SANDBOX_DIR")
           or "/tmp/visorqa_sandboxes")
    return Path(raw)


def _git(args: List[str], cwd: Optional[Path] = None, timeout: int = 180) -> Tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _local_checkout_root() -> Optional[Path]:
    code, out = _git(["rev-parse", "--show-toplevel"],
                     cwd=Path(__file__).resolve().parent)
    return Path(out.splitlines()[0]) if code == 0 and out else None


def _origin_matches(root: Path, repo_full_name: str) -> bool:
    code, out = _git(["remote", "get-url", "origin"], cwd=root)
    if code != 0:
        return False
    url = out.strip().lower().removesuffix(".git")
    return url.endswith(repo_full_name.lower())


def _frontend_files(root: Path, priority: List[str]) -> List[str]:
    found: List[str] = []
    seen = set()
    for rel in priority:
        norm = normalize_path(rel)
        if norm and (root / norm).is_file() and norm not in seen:
            seen.add(norm)
            found.append(norm)
    for path in sorted(root.rglob("*")):
        if len(found) >= MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in FRONTEND_EXTS:
            continue
        rel = path.relative_to(root).as_posix()
        if "node_modules" in rel or "/.next/" in rel or rel.startswith(".git"):
            continue
        if rel not in seen:
            seen.add(rel)
            found.append(rel)
    # PR-changed, non-protected frontend files first (Node 2 input order).
    found.sort(key=lambda p: (0 if p in priority and not is_protected_path(p) else
                              1 if not is_protected_path(p) else 2, p))
    return found


async def _api_materialize(dest: Path, repo_full_name: str, branch: str,
                           pr_number: int, token: str) -> List[str]:
    """Fetch PR-changed (or tree) frontend files via the GitHub API."""
    from backend.api.auth import github_api

    priority: List[str] = []
    if pr_number:
        status, files = await github_api(
            "GET", f"/repos/{repo_full_name}/pulls/{pr_number}/files?per_page=100",
            token)
        if status == 200 and isinstance(files, list):
            priority = [str(f.get("filename")) for f in files if f.get("filename")]
    candidates = [p for p in priority if p.lower().endswith(FRONTEND_EXTS)]
    if not candidates:
        # PR touched no frontend files (backend/markdown only): fall back
        # to real frontend components from the repo tree so triage still
        # has a genuine, non-protected target. Never fabricate files.
        status, tree = await github_api(
            "GET", f"/repos/{repo_full_name}/git/trees/{branch}?recursive=1", token)
        if status == 200 and isinstance(tree, dict):
            candidates = [str(t.get("path")) for t in tree.get("tree", [])
                          if t.get("type") == "blob"
                          and str(t.get("path", "")).lower().endswith(FRONTEND_EXTS)]
            candidates.sort(key=lambda p: (
                1 if is_protected_path(normalize_path(p)) else 0, p))
    written: List[str] = []
    for rel in candidates[:MAX_FILES]:
        norm = normalize_path(rel)
        if not norm:
            continue
        status, body = await github_api(
            "GET", f"/repos/{repo_full_name}/contents/{norm}?ref={branch}", token)
        if status != 200 or not isinstance(body, dict) or body.get("encoding") != "base64":
            continue
        try:
            data = base64.b64decode(body.get("content", ""))
        except Exception:
            continue
        target = dest / norm
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(norm)
    return written


def _write_sandbox_marker(dest: Path, run_id: str, branch: str) -> None:
    try:
        marker = dest.parent / ".visor-sandbox.json"
        marker.write_text(json.dumps(
            {"session_id": run_id, "branch": branch, "commit_sha": ""}),
            encoding="utf-8")
    except Exception:
        pass


async def hydrate_pr_workspace(
    run_id: str,
    repo_full_name: str,
    branch: str,
    pr_number: int = 0,
    token: str = "",
) -> Dict[str, Any]:
    """Provision an isolated workspace for one dispatched scan.

    Returns {"root", "repository_files", "strategy"}; root is "" when no
    strategy could materialize files (pipeline then fails closed as
    before — nothing is fabricated).
    """
    dest = sandbox_root() / run_id / "app"
    dest.parent.mkdir(parents=True, exist_ok=True)
    branch = branch or "main"

    priority: List[str] = []
    if pr_number and token:
        try:
            from backend.api.auth import github_api
            status, files = await github_api(
                "GET", f"/repos/{repo_full_name}/pulls/{pr_number}/files?per_page=100", token)
            if status == 200 and isinstance(files, list):
                priority = [str(f.get("filename")) for f in files if f.get("filename")]
        except Exception:
            pass

    # 1) Local checkout match -> isolated git worktree at the PR branch.
    local = _local_checkout_root()
    if local is not None and repo_full_name and _origin_matches(local, repo_full_name):
        try:
            await asyncio.to_thread(_git, ["fetch", "--quiet", "origin", branch], local, 120)
        except Exception:
            pass
        if pr_number:
            try:
                await asyncio.to_thread(
                    _git, ["fetch", "--quiet", "origin", f"pull/{pr_number}/head:pr-{pr_number}-{run_id[:8]}"],
                    local, 120)
            except Exception:
                pass
        code, _ = await asyncio.to_thread(
            _git, ["worktree", "add", "--quiet", "--detach", str(dest),
                   f"origin/{branch}"], local, 180)
        if code != 0:
            code, _ = await asyncio.to_thread(
                _git, ["worktree", "add", "--quiet", "--detach", str(dest), branch],
                local, 180)
        if code != 0 and pr_number:
            code, _ = await asyncio.to_thread(
                _git, ["worktree", "add", "--quiet", "--detach", str(dest), f"pr-{pr_number}-{run_id[:8]}"],
                local, 180)
        if code == 0 and dest.is_dir():
            _write_sandbox_marker(dest, run_id, branch)
            return {"root": str(dest),
                    "repository_files": _frontend_files(dest, priority),
                    "strategy": "local_worktree"}

    # 2) Shallow clone with the caller's token.
    if token and repo_full_name:
        url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
        code, _ = await asyncio.to_thread(
            _git, ["clone", "--quiet", "--depth", "1", "--branch", branch, url, str(dest)],
            None, 300)
        if code != 0 and pr_number:
            code, _ = await asyncio.to_thread(
                _git, ["clone", "--quiet", "--depth", "1", url, str(dest)],
                None, 300)
            if code == 0:
                await asyncio.to_thread(
                    _git, ["fetch", "--depth", "1", "origin", f"pull/{pr_number}/head:pr-{pr_number}"],
                    dest, 180)
                await asyncio.to_thread(
                    _git, ["checkout", "--quiet", f"pr-{pr_number}"],
                    dest, 60)
        if code == 0 and dest.is_dir():
            _write_sandbox_marker(dest, run_id, branch)
            return {"root": str(dest),
                    "repository_files": _frontend_files(dest, priority),
                    "strategy": "shallow_clone"}

    # 3) GitHub API materialization (no git required).
    if token and repo_full_name:
        written = await _api_materialize(dest, repo_full_name, branch, pr_number, token)
        if written:
            _write_sandbox_marker(dest, run_id, branch)
            return {"root": str(dest), "repository_files": written,
                    "strategy": "github_api"}

    return {"root": "", "repository_files": [], "strategy": "unavailable"}
