"""GitHub publication stage: verified commit XOR unverified suggestion.

Only a Node-5-verified run commits; a 3-strike failure posts a clearly
labelled unverified suggestion containing the exact best patch. Branch
advancement, unauthorized files, and duplicate retries never push.
Supports real GitHubClient, legacy stubs, and injected test fakes.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.adapters.github_client import GitHubConflictError, GitHubError


async def _call(obj: Any, name: str, *args, **kwargs):
    fn = getattr(obj, name)
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def _call_retry(obj: Any, name: str, *args, retries: int = 2, **kwargs):
    last = None
    for attempt in range(retries + 1):
        try:
            return await _call(obj, name, *args, **kwargs)
        except Exception as exc:
            last = exc
            if not getattr(exc, "retryable", False) or attempt >= retries:
                raise
    raise last  # pragma: no cover


def _fmt(m: Optional[Dict[str, Any]]) -> str:
    if not m:
        return "unavailable"
    return f"V_r={m.get('v_r')}, IoU={m.get('iou')}, Delta_x={m.get('delta_x')}px"


def _authorized_verified_files(state: Any) -> List[str]:
    from backend.core.patch import parse_unified_diff, normalize_diff
    from backend.core.triage import is_protected_path, normalize_path
    patch = state.best_patch if state.is_resolved else state.current_patch
    patched: List[str] = []
    if patch:
        try:
            patched = [normalize_path(p.path) for p in parse_unified_diff(normalize_diff(patch))]
        except Exception:
            patched = []
    allowed = set()
    for raw in list(state.modified_files or []) + list((state.repair_spec or {}).get("patched_files") or []) + list(state.target_files or []):
        n = normalize_path(raw)
        if n and not is_protected_path(n):
            allowed.add(n)
    return [p for p in patched if p and p in allowed and not is_protected_path(p)]


def _file_contents(state: Any, files: List[str]) -> Optional[Dict[str, str]]:
    from backend.core.diagnose import resolve_repo_root
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    root = resolve_repo_root(spec)
    if root is None and state.sandbox and state.sandbox.working_dir:
        root = Path(state.sandbox.working_dir)
    if root is None or not Path(root).is_dir():
        return None
    out = {}
    for rel in files:
        p = Path(root) / rel
        if not p.is_file():
            return None
        out[rel] = p.read_text(encoding="utf-8")
    return out


def _set(state: Any, status: str, **kw) -> None:
    state.github_publication_status = status
    for k, v in kw.items():
        setattr(state, k, v)
    spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
    spec["github_publication_status"] = status
    if state.github_commit_sha:
        spec["github_commit_sha"] = state.github_commit_sha
    state.repair_spec = spec


async def publish_run_result(state: Any, github: Any = None) -> Any:
    """Publish according to verification outcome; records state, never raises."""
    if github is None:
        try:
            from backend.adapters.github_app import github_app_auth
            from backend.config import settings
            inst_id = getattr(state, "installation_id", None) or getattr(settings, "GITHUB_INSTALLATION_ID", None)
            if github_app_auth.is_configured() and inst_id:
                github = await github_app_auth.get_authenticated_client(inst_id)
            elif getattr(settings, "GITHUB_PAT", None):
                from backend.adapters.github_client import GitHubClient
                github = GitHubClient()
        except Exception:
            github = None
    if github is None:
        return state
    repo = state.repo_full_name or state.repo_name
    branch = state.branch or "main"
    expected = state.commit_sha or (state.sandbox.commit_sha if state.sandbox else "") or None
    metrics = state.best_viewport_metrics or {}
    if not metrics and state.attempts:
        metrics = state.attempts[-1].viewport_metrics or {}
    mobile, desktop = metrics.get("mobile"), metrics.get("desktop")

    try:
        # Branch-conflict pre-check (verified and suggestion paths: never force).
        if hasattr(github, "get_branch_head") and expected:
            head = await _call_retry(github, "get_branch_head", repo, branch)
            if head and str(head) != str(expected):
                _set(state, "conflict", github_error=f"branch advanced: expected {expected}, found {head}")
                return state

        if state.is_resolved:
            if state.github_commit_pushed and state.github_commit_sha:
                _set(state, "commit_pushed")
                return state
            files = _authorized_verified_files(state)
            if not files or not state.best_patch:
                _set(state, "error", github_error="no authorized verified files to commit")
                return state
            contents = _file_contents(state, files)
            marker = f"visorqa:{state.run_id}:attempt:{state.best_attempt_number}:verified"
            message = f"fix(ui): VisorQA verified visual repair (attempt {state.best_attempt_number})\n\n{marker}"
            if hasattr(github, "commit_files"):
                if contents is None:
                    _set(state, "error", github_error="verified working tree unavailable")
                    return state
                sha = await _call_retry(github, "commit_files", repo, branch, expected_head=expected,
                                        files=contents, message=message, idempotency_key=marker)
            elif hasattr(github, "commit_patch"):
                sha = None
                for path in files:
                    content = contents[path] if contents else state.best_patch
                    sha = await _call_retry(github, "commit_patch", repo, branch, path, content)
            else:
                _set(state, "error", github_error="github client has no commit method")
                return state
            state.github_commit_sha = str(sha) if sha else None
            state.github_commit_pushed = bool(sha)
            body = (f"<!-- {marker} -->\n### VisorQA verification passed\n\n"
                    f"Both viewports passed (V_r >= 0.98, IoU == 0, Delta_x <= 2px).\n\n"
                    f"- Mobile (375px): {_fmt(mobile)}\n- Desktop (1440px): {_fmt(desktop)}\n"
                    f"- Commit: {state.github_commit_sha}\n- Attempt: {state.best_attempt_number}\n")
            refs = state.best_screenshot_refs or {}
            if refs:
                body += f"- Evidence: {refs}\n"
            await _post(github, repo, state.pr_number, body, marker + ":comment", verified=True)
            state.github_review_comment_posted = True
            _set(state, "commit_pushed")
            return state

        # 3-strike failure: non-destructive suggestion only.
        if state.github_review_comment_posted:
            _set(state, "suggestion_posted")
            return state
        marker = f"visorqa:{state.run_id}:suggestion:attempt:{state.best_attempt_number}"
        reasons = []
        if state.attempts:
            reasons = state.attempts[-1].failure_reasons or []
        body = (f"<!-- {marker} -->\n### VisorQA unverified suggestion — NOT applied\n\n"
                f"This patch was **not** committed and the PR branch was not modified. "
                f"It did not meet the strict acceptance criteria.\n\n"
                f"- Best attempt: {state.best_attempt_number} (score {state.best_score})\n"
                f"- Mobile (375px): {_fmt(mobile)}\n- Desktop (1440px): {_fmt(desktop)}\n"
                f"- Failure reasons: {'; '.join(reasons) or 'criteria not met'}\n\n"
                f"Exact best patch:\n\n```diff\n{state.best_patch or '(no valid patch)'}\n```\n\n"
                f"To apply manually: review the diff, apply it locally, and re-run visual QA at 375px and 1440px.\n")
        await _post(github, repo, state.pr_number, body, marker, verified=False)
        state.github_review_comment_posted = True
        _set(state, "suggestion_posted")
        return state
    except GitHubConflictError as exc:
        _set(state, "conflict", github_error=str(exc))
        return state
    except Exception as exc:
        _set(state, "error", github_error=f"{type(exc).__name__}: {exc}")
        return state


async def _post(github: Any, repo: str, pr_number: int, body: str, marker: str, *, verified: bool) -> None:
    if verified and hasattr(github, "post_verification_comment"):
        await _call_retry(github, "post_verification_comment", repo, pr_number, body, marker=marker)
    elif not verified and hasattr(github, "post_suggested_review"):
        await _call_retry(github, "post_suggested_review", repo, pr_number, body, marker=marker)
    elif hasattr(github, "post_comment"):
        await _call_retry(github, "post_comment", repo, pr_number, body, marker=marker)
    elif hasattr(github, "post_pr_review"):
        await _call_retry(github, "post_pr_review", repo, pr_number, "", {"status": "RESOLVED" if verified else "FAILED", "body": body})
    else:
        raise GitHubError("github client has no comment method")
