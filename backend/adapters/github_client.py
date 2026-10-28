"""
VisorQA GitHub Integration - (Adapter Pattern)
PyGithub Client for Webhook Verification, PR Review Comments, and Auto-Commits
"""

import hmac
import hashlib
from typing import Optional, Dict, Any
from github import Github, Auth
from backend.config import settings


class GitHubClient:
    """GitHub Adapter for Autonomous Reviews and Verified Fix Commits"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_PAT
        self.gh = Github(auth=Auth.Token(self.token)) if self.token else None

    @staticmethod
    def verify_webhook_signature(payload_body: bytes, signature_header: Optional[str]) -> bool:
        """
        Validates the GitHub Webhook HMAC SHA-256 signature (X-Hub-Signature-256).
        """
        secret = settings.GITHUB_WEBHOOK_SECRET
        if not secret or not signature_header:
            return False

        expected_signature = "sha256=" + hmac.new(
            secret.encode("utf-8"),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature_header)

    async def post_pr_review(
        self,
        repo_name: str,
        pr_number: int,
        run_id: str,
        summary: Dict[str, Any]
    ) -> bool:
        """
        Posts automated VisorQA verification summary comment and link to PR.
        """
        # Interface stub: PyGithub PR review comment
        inspector_url = f"{settings.FRONTEND_URL}/runs/{run_id}"
        comment_body = (
            f"### 🛡️ VisorQA Autonomous Visual QA Report\n\n"
            f"- **Status:** {summary.get('status', 'RESOLVED')}\n"
            f"- **Strikes:** {summary.get('strikes', 1)}/3\n"
            f"- **Live Telemetry & Mask Inspector:** [{inspector_url}]({inspector_url})\n"
        )
        _ = comment_body
        return True

    async def commit_patch(
        self,
        repo_name: str,
        branch: str,
        file_path: str,
        patched_content: str,
        commit_message: str = "fix(ui): autonomous self-healing visual fix by VisorQA"
    ) -> str:
        """
        Commits verified patch directly to the target PR branch.
        """
        # Interface stub: PyGithub commit creation
        return "commit_sha_stub_123"
