"""GitHub repository discovery + repo-scoped run actions.

Discovery reads the live GitHub API with the authenticated session token
(or configured App installation token / env PAT). Actions post the real
telemetry report comment and commit the verified unified diff to the PR
branch via the Contents API. Nothing here fabricates GitHub data: missing
auth or missing run artifacts produce explicit 4xx responses.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.api.auth import github_api, resolve_github_token

router = APIRouter(prefix="/api/github", tags=["GitHub Repositories"])
runs_router = APIRouter(prefix="/api/runs", tags=["GitHub Run Actions"])


async def _token_or_401(request: Request):
    resolved = await resolve_github_token(request)
    if not resolved:
        return None, JSONResponse(
            {"detail": "GitHub authentication required (login or configure GITHUB_PAT / GitHub App)"},
            status_code=401)
    return resolved[0], None


@router.get("/repos")
async def list_repos(request: Request) -> Any:
    resolved, err = await _token_or_401(request)
    if err:
        return err
    token = resolved
    # Session mode distinguishes user tokens (list own repos) from
    # installation tokens (list installation repos).
    from backend.api.auth import current_session
    session = current_session(request)
    auth_mode = session["auth_mode"] if session else "app_or_pat"
    if auth_mode in ("oauth", "pat"):
        status, body = await github_api(
            "GET", "/user/repos?per_page=100&sort=updated", token)
    else:
        status, body = await github_api("GET", "/installation/repositories", token)
        if status == 200 and isinstance(body, dict):
            body = body.get("repositories", [])
    if status != 200 or not isinstance(body, list):
        return JSONResponse({"detail": f"GitHub repos request failed ({status})"},
                            status_code=502)
    return [{
        "full_name": r.get("full_name"),
        "name": r.get("name"),
        "owner": (r.get("owner") or {}).get("login"),
        "private": bool(r.get("private")),
        "default_branch": r.get("default_branch"),
        "open_issues_count": r.get("open_issues_count"),
        "updated_at": r.get("updated_at"),
        "html_url": r.get("html_url"),
    } for r in body]


@router.get("/repos/{owner}/{repo}/pulls")
async def list_pulls(owner: str, repo: str, request: Request) -> Any:
    resolved, err = await _token_or_401(request)
    if err:
        return err
    token = resolved
    status, body = await github_api(
        "GET", f"/repos/{owner}/{repo}/pulls?state=all&per_page=50&sort=updated"
               "&direction=desc", token)
    if status != 200 or not isinstance(body, list):
        return JSONResponse({"detail": f"GitHub pulls request failed ({status})"},
                            status_code=502)
    pulls = [{
        "number": p.get("number"),
        "title": p.get("title"),
        "state": p.get("state"),
        "head_ref": (p.get("head") or {}).get("ref"),
        "head_sha": (p.get("head") or {}).get("sha"),
        "base_ref": (p.get("base") or {}).get("ref"),
        "user_login": (p.get("user") or {}).get("login"),
        "updated_at": p.get("updated_at"),
        "html_url": p.get("html_url"),
    } for p in body]
    pulls.sort(key=lambda p: (0 if p["state"] == "open" else 1, p["number"] or 0))
    return pulls


@router.get("/repos/{owner}/{repo}/branches")
async def list_branches(owner: str, repo: str, request: Request) -> Any:
    resolved, err = await _token_or_401(request)
    if err:
        return err
    token = resolved
    status, body = await github_api(
        "GET", f"/repos/{owner}/{repo}/branches?per_page=100", token)
    if status != 200 or not isinstance(body, list):
        return JSONResponse({"detail": f"GitHub branches request failed ({status})"},
                            status_code=502)
    return [{
        "name": b.get("name"),
        "sha": (b.get("commit") or {}).get("sha"),
    } for b in body]


# ---------------------------------------------------------------------------
# Run actions: comment + commit (strictly run/repo scoped)
# ---------------------------------------------------------------------------

def _load_run_record(run_id: str) -> Optional[Dict[str, Any]]:
    from backend.core.artifacts import ArtifactStore
    return ArtifactStore().get_run_record(run_id)


def _latest_diff(record: Dict[str, Any]) -> Optional[str]:
    for raw in reversed(record.get("attempts_raw", []) or []):
        diff = raw.get("unified_diff") or raw.get("patch_diff")
        if diff:
            return str(diff)
    return record.get("best_patch") or record.get("current_patch")


def apply_unified_diff(source: str, diff: str) -> str:
    """Minimal unified-diff applier (context-verified). Raises ValueError."""
    src = source.split("\n")
    out: List[str] = []
    pos = 0
    lines = diff.split("\n")
    i = 0
    applied_any = False
    while i < len(lines):
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", lines[i])
        if not m:
            i += 1
            continue
        applied_any = True
        old_start = int(m.group(1)) - 1
        if old_start < pos:
            raise ValueError("overlapping hunks")
        out.extend(src[pos:old_start])
        pos = old_start
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            line = lines[i]
            if line.startswith("+") and not line.startswith("+++"):
                out.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                if pos >= len(src) or src[pos] != line[1:]:
                    raise ValueError(f"context mismatch at source line {pos + 1}")
                pos += 1
            elif line.startswith("\\"):
                pass
            else:
                text = line[1:] if line.startswith(" ") else line
                if pos >= len(src) or src[pos] != text:
                    raise ValueError(f"context mismatch at source line {pos + 1}")
                out.append(text)
                pos += 1
            i += 1
    if not applied_any:
        raise ValueError("no hunks found in diff")
    out.extend(src[pos:])
    return "\n".join(out)


def _diff_target_files(diff: str) -> List[str]:
    files: List[str] = []
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            raw = line[4:].strip()
            if raw.startswith("b/"):
                raw = raw[2:]
            path = raw.split("\t")[0].strip()
            if path and path not in files and path != "/dev/null":
                files.append(path)
    return files


@runs_router.post("/{run_id}/github/comment")
async def post_telemetry_comment(run_id: str, request: Request) -> Any:
    resolved, err = await _token_or_401(request)
    if err:
        return err
    token = resolved
    record = _load_run_record(run_id)
    if record is None:
        return JSONResponse({"detail": f"run {run_id} not found"}, status_code=404)
    repo = record.get("repo_full_name") or record.get("repo_name")
    pr_number = record.get("pr_number")
    if not repo or not pr_number:
        return JSONResponse({"detail": "run has no repository/PR scope"}, status_code=422)

    from backend.core.artifacts import build_run_payload
    payload = build_run_payload(record, record.get("anomalies", []) or [],
                                record.get("attempts_raw", []) or [],
                                record.get("artifacts", []) or [])
    lines = [
        f"## VisorQA Optical Telemetry — run `{run_id}`",
        "",
        f"- **PR:** {repo}#{pr_number} · branch `{record.get('branch', '')}`",
        f"- **Status:** {payload.get('status')} · strikes {payload.get('strikes')}/{payload.get('max_attempts')}",
        "",
        "| Attempt | Decision | Mobile V_r | Desktop V_r |",
        "|---|---|---|---|",
    ]
    for a in payload["attempts"]:
        fb = a["verification_feedback"]
        ms = a["viewport_summary"]["mobile"]
        ds = a["viewport_summary"]["desktop"]
        lines.append(
            f"| {a['attempt_number']} ({a['kind']}) | {fb.get('strike_decision') or '—'} "
            f"| {ms.get('v_r')} | {ds.get('v_r')} |")
    diff = _latest_diff(record)
    if diff:
        from backend.core.artifacts import sha256_text
        lines += ["", f"Verified diff SHA-256: `{sha256_text(diff)}`"]
    body_md = "\n".join(lines)

    status, body = await github_api(
        "POST", f"/repos/{repo}/issues/{pr_number}/comments", token,
        json={"body": body_md})
    if status not in (200, 201) or not isinstance(body, dict):
        return JSONResponse({"detail": f"GitHub comment failed ({status})"}, status_code=502)
    return {"html_url": body.get("html_url"), "id": body.get("id")}


@runs_router.post("/{run_id}/github/commit")
async def commit_fix(run_id: str, request: Request) -> Any:
    resolved, err = await _token_or_401(request)
    if err:
        return err
    token = resolved
    record = _load_run_record(run_id)
    if record is None:
        return JSONResponse({"detail": f"run {run_id} not found"}, status_code=404)
    repo = record.get("repo_full_name") or record.get("repo_name")
    branch = (record.get("branch") or "").strip()
    diff = _latest_diff(record)
    if not repo or not branch:
        return JSONResponse({"detail": "run has no repository/branch scope"}, status_code=422)
    if not diff:
        return JSONResponse({"detail": "run has no unified diff to commit"}, status_code=422)
    targets = _diff_target_files(diff)
    if not targets:
        return JSONResponse({"detail": "diff declares no target files"}, status_code=422)

    commits: List[Dict[str, Any]] = []
    for path in targets:
        status, current = await github_api(
            "GET", f"/repos/{repo}/contents/{path}?ref={branch}", token)
        if status != 200 or not isinstance(current, dict):
            return JSONResponse(
                {"detail": f"could not read {path} on {branch} ({status})"}, status_code=502)
        try:
            source = base64.b64decode(current.get("content", "")).decode("utf-8")
            updated = apply_unified_diff(source, diff)
        except Exception as exc:
            return JSONResponse({"detail": f"diff does not apply cleanly to {path}: {exc}"},
                                status_code=422)
        status, created = await github_api(
            "PUT", f"/repos/{repo}/contents/{path}", token,
            json={
                "message": f"fix(ui): VisorQA autonomous visual repair (run {run_id})",
                "content": base64.b64encode(updated.encode("utf-8")).decode("ascii"),
                "sha": current.get("sha"),
                "branch": branch,
            })
        if status not in (200, 201) or not isinstance(created, dict):
            return JSONResponse({"detail": f"GitHub commit failed for {path} ({status})"},
                                status_code=502)
        commit = created.get("commit") or {}
        commits.append({"path": path, "sha": commit.get("sha"),
                        "html_url": commit.get("html_url")})
    head = commits[-1]
    return {"sha": head["sha"], "html_url": head["html_url"], "commits": commits,
            "branch": branch, "repo": repo}
