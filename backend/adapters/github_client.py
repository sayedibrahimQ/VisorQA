"""VisorQA GitHub integration (PyGithub, injectable, offline-safe).

Imports and construction never require credentials. Live methods raise
``GitHubConfigError`` without a token instead of fabricating results.
Tests inject a fake via ``github_obj=`` / orchestrator-level fakes.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
from typing import Any, Dict, Optional

from backend.config import settings


class GitHubError(RuntimeError):
    retryable = False


class GitHubConfigError(GitHubError):
    pass


class GitHubConflictError(GitHubError):
    pass


class GitHubPermissionError(GitHubError):
    pass


class GitHubAPIError(GitHubError):
    retryable = True


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


class GitHubClient:
    """GitHub adapter for verified commits and PR comments."""

    def __init__(self, token: Optional[str] = None, *, github_obj: Any = None):
        # token=None -> settings; explicit "" disables credentials (offline).
        self.token = settings.GITHUB_PAT if token is None else token
        self._gh = github_obj  # injected fake / prebuilt PyGithub object
        if self._gh is None and self.token:
            from github import Auth, Github
            self._gh = Github(auth=Auth.Token(self.token))

    @staticmethod
    def verify_webhook_signature(payload_body: bytes, signature_header: Optional[str]) -> bool:
        secret = settings.GITHUB_WEBHOOK_SECRET
        if not secret or not signature_header:
            return False
        expected = "sha256=" + hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def _repo(self, repo_name: str):
        if self._gh is None:
            raise GitHubConfigError("GITHUB_PAT not configured; GitHub publication unavailable")
        try:
            return self._gh.get_repo(repo_name)
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status in (401, 403, 404):
                raise GitHubPermissionError(f"GitHub permission/not-found error: {exc}") from exc
            raise GitHubAPIError(f"GitHub API error: {exc}") from exc

    async def get_branch_head(self, repo_name: str, branch: str) -> str:
        repo = self._repo(repo_name)
        try:
            return str(repo.get_branch(branch).commit.sha)
        except GitHubError:
            raise
        except Exception as exc:
            raise GitHubAPIError(f"cannot read branch head: {exc}") from exc

    async def find_comment(self, repo_name: str, pr_number: int, marker: str) -> Optional[Any]:
        repo = self._repo(repo_name)
        pr = repo.get_pull(int(pr_number))
        for comment in pr.get_issue_comments():
            if marker in (getattr(comment, "body", "") or ""):
                return comment
        return None

    async def commit_files(self, repo_name: str, branch: str, *, expected_head: Optional[str],
                           files: Dict[str, str], message: str, idempotency_key: str = "") -> str:
        """Commit exactly ``files``; conflict if branch moved. Returns head SHA."""
        repo = self._repo(repo_name)
        head = str(repo.get_branch(branch).commit.sha)
        if expected_head and head != expected_head:
            raise GitHubConflictError(f"branch {branch} advanced: expected {expected_head}, found {head}")
        # Idempotency: a prior commit carrying the marker is reused.
        if idempotency_key:
            try:
                for commit in repo.get_commits(sha=branch):
                    if idempotency_key in (commit.commit.message or ""):
                        return str(commit.sha)
                    break
            except Exception:
                pass
        last_sha = head
        try:
            for path in sorted(files):
                try:
                    existing = repo.get_contents(path, ref=branch)
                    result = repo.update_file(path, message, files[path], existing.sha, branch=branch)
                except Exception as exc:
                    if getattr(exc, "status", None) == 404:
                        result = repo.create_file(path, message, files[path], branch=branch)
                    else:
                        raise
                commit = result.get("commit") if isinstance(result, dict) else getattr(result, "commit", None)
                if commit is not None:
                    last_sha = str(getattr(commit, "sha", last_sha))
        except GitHubError:
            raise
        except Exception as exc:
            if getattr(exc, "status", None) in (401, 403):
                raise GitHubPermissionError(str(exc)) from exc
            raise GitHubAPIError(str(exc)) from exc
        return last_sha

    async def commit_patch(self, repo_name: str, branch: str, file_path: str,
                           patched_content: str, commit_message: str = "fix(ui): autonomous self-healing visual fix by VisorQA") -> str:
        """Legacy single-file signature; content is file content, not a diff."""
        return await self.commit_files(repo_name, branch, expected_head=None,
                                       files={file_path: patched_content}, message=commit_message)

    async def post_comment(self, repo_name: str, pr_number: int, body: str, *, marker: str = "") -> Any:
        if marker:
            existing = await self.find_comment(repo_name, pr_number, marker)
            if existing is not None:
                return existing
        repo = self._repo(repo_name)
        try:
            return repo.get_pull(int(pr_number)).create_issue_comment(body)
        except Exception as exc:
            if getattr(exc, "status", None) in (401, 403, 404):
                raise GitHubPermissionError(str(exc)) from exc
            raise GitHubAPIError(str(exc)) from exc

    async def post_pr_review(self, repo_name: str, pr_number: int, run_id: str,
                             summary: Dict[str, Any]) -> bool:
        """Legacy signature used by older callers; returns True only if posted."""
        marker = f"<!-- visorqa:run:{run_id} -->"
        body = (f"{marker}\n### VisorQA Autonomous Visual QA Report\n\n"
                f"- **Status:** {summary.get('status', 'RESOLVED')}\n"
                f"- **Strikes:** {summary.get('strikes', 1)}/3\n"
                f"- **Commit:** {summary.get('commit_sha') or 'none'}\n")
        if summary.get("body"):
            body += "\n" + str(summary["body"])
        await self.post_comment(repo_name, pr_number, body, marker=marker)
        return True

    async def post_verification_comment(self, repo_name: str, pr_number: int, body: str, *, marker: str = ""):
        return await self.post_comment(repo_name, pr_number, body, marker=marker)

    async def post_suggested_review(self, repo_name: str, pr_number: int, body: str, *, marker: str = ""):
        # Non-destructive: a plain PR comment, never an approval/review-approve.
        return await self.post_comment(repo_name, pr_number, body, marker=marker)
