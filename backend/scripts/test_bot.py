#!/usr/bin/env python3
"""VisorQA GitHub App Verification & Telemetry Test Script (visorqa-bot[bot]).

Authenticates as the GitHub App via RS256 JWT, exchanges it for an installation
access token, and posts a test Optical Telemetry Report comment to a PR.

Security notes:
- Reads credentials securely from environment (.env / backend/.env) or CLI flags.
- Never hardcodes private keys, tokens, or app secrets in this file.
- Masks tokens in console logs (e.g. 'ghs_a1b2...c3d4').
- Supports --dry-run to verify authentication without modifying PR comments.

Usage:
    # 1. Using credentials configured in your .env or backend/.env:
    python -m backend.scripts.test_bot --repo sayedibrahimQ/demo-storefront --pr 1

    # 2. Dry run (verify JWT and installation token exchange only):
    python -m backend.scripts.test_bot --dry-run

    # 3. Explicit overrides via command-line arguments:
    python -m backend.scripts.test_bot \\
        --app-id 123456 \\
        --installation-id 98765432 \\
        --key-path ./backend/visorqa-bot.private-key.pem \\
        --repo sayedibrahimQ/demo-storefront \\
        --pr 1
"""
from __future__ import annotations

import argparse
import asyncio
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import jwt

from backend.config import settings
from backend.adapters.github_app import mask_token


def generate_jwt(app_id: str, private_key_pem: str) -> str:
    """Generate RS256 JWT valid for 9 minutes to authenticate as the GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - 60,            # 60s clock skew allowance
        "exp": now + (9 * 60),      # Valid for 9 minutes
        "iss": str(app_id).strip(),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


async def get_installation_token(app_id: str, private_key_pem: str, installation_id: Any) -> str:
    """Exchange JWT for an installation token (valid for 1 hour)."""
    inst_str = str(installation_id).strip()
    if not inst_str.isdigit():
        if inst_str.startswith("Iv1.") or inst_str.startswith("Iv23") or len(inst_str) == 20:
            raise RuntimeError(
                f"Invalid GITHUB_INSTALLATION_ID '{inst_str}': This looks like a GitHub App Client ID, "
                f"not an Installation ID.\n"
                f"To find your numeric Installation ID:\n"
                f"1. In your GitHub App settings, click 'Install App' in the left sidebar.\n"
                f"2. Click the gear (⚙️) icon next to the installed account.\n"
                f"3. Look at your browser address bar: https://github.com/settings/installations/12345678\n"
                f"   The number at the very end (e.g. 12345678) is your GITHUB_INSTALLATION_ID."
            )
        raise RuntimeError(f"Installation ID must be numeric, got: '{inst_str}'")
    inst_id = int(inst_str)

    app_jwt = generate_jwt(app_id, private_key_pem)
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/app/installations/{inst_id}/access_tokens"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(url, headers=headers)
        if res.status_code == 401:
            raise RuntimeError(
                "GitHub rejected JWT with 401 Unauthorized. "
                "Check that GITHUB_APP_ID matches the App ID on GitHub and the private key is valid."
            )
        if res.status_code == 404:
            raise RuntimeError(
                f"GitHub returned 404 for installation {installation_id}. "
                "Verify that the App is installed on the target repository and the installation ID is correct."
            )
        res.raise_for_status()
        data = res.json()
        token = data.get("token")
        if not token:
            raise RuntimeError("Response missing 'token' field.")
        return token


async def post_bot_comment(token: str, repo: str, pr_num: int) -> str:
    """Post an optical telemetry report comment as visorqa-bot[bot]."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues/{pr_num}/comments"
    comment = (
        "## 👁️ VisorQA Optical Telemetry Report\n"
        "> **Runner:** `visorqa-bot[bot]` • **Status:** `TEST_OK`\n\n"
        "| Viewport | Metric | Value | Status |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| Mobile (`375x812`) | $V_r$ | `1.00` | **PASS** |\n"
        "| Desktop (`1440x900`) | $V_r$ | `1.00` | **PASS** |\n"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(url, headers=headers, json={"body": comment})
        if res.status_code in (401, 403):
            raise RuntimeError(
                f"GitHub rejected comment with HTTP {res.status_code}: {res.text}. "
                "Check that the App has 'Pull requests: Read & write' and 'Issues: Read & write' permissions."
            )
        res.raise_for_status()
        comment_url = res.json().get("html_url", "")
        return comment_url


def resolve_key_file(key_path: Optional[str]) -> Path:
    """Locate the .pem file safely and check permissions."""
    path_str = key_path or settings.GITHUB_PRIVATE_KEY_PATH or "./visorqa-bot.private-key.pem"
    candidates = [
        Path(path_str),
        Path.cwd() / path_str,
        Path(__file__).resolve().parent.parent / path_str,
        Path(__file__).resolve().parent.parent / Path(path_str).name,
    ]
    for cand in candidates:
        if cand.is_file():
            # Check permissions
            try:
                mode = cand.stat().st_mode
                if bool(mode & (stat.S_IRWXG | stat.S_IRWXO)):
                    print(f"⚠️  [SECURITY WARNING] Private key {cand} has open permissions. Run: chmod 600 {cand}")
            except Exception:
                pass
            return cand.resolve()

    print("\n❌ Error: Private key file not found!")
    print("   Checked candidates:")
    for cand in candidates:
        print(f"     - {cand}")
    print("\n   Make sure you downloaded your .pem file from GitHub App settings and placed it in:")
    print("   backend/visorqa-bot.private-key.pem (or set GITHUB_PRIVATE_KEY_PATH in .env)\n")
    sys.exit(1)


async def async_main():
    parser = argparse.ArgumentParser(description="VisorQA GitHub App Bot Verification Script")
    parser.add_argument("--app-id", default=settings.GITHUB_APP_ID, help="GitHub App ID")
    parser.add_argument("--installation-id", default=settings.GITHUB_INSTALLATION_ID, help="GitHub Installation ID")
    parser.add_argument("--key-path", default=settings.GITHUB_PRIVATE_KEY_PATH, help="Path to .pem private key file")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_TEST_REPO", "sayedibrahimQ/demo-storefront"), help="Target repository (owner/repo)")
    parser.add_argument("--pr", type=int, default=int(os.environ.get("GITHUB_TEST_PR", "1")), help="Target PR number")
    parser.add_argument("--dry-run", action="store_true", help="Authenticate only; do not post comment")

    args = parser.parse_args()

    print("=" * 60)
    print("👁️  VisorQA GitHub App (visorqa-bot[bot]) Verification")
    print("=" * 60)

    # 1. Validate App ID
    app_id = str(args.app_id or "").strip()
    if not app_id:
        print("\n❌ Error: GITHUB_APP_ID is not configured!")
        print("   Set GITHUB_APP_ID in .env or pass --app-id <ID>")
        print("   (Find this on your GitHub App settings page under General -> App ID)\n")
        sys.exit(1)

    # 2. Validate Installation ID
    installation_id = args.installation_id
    if not installation_id:
        print("\n❌ Error: GITHUB_INSTALLATION_ID is not configured!")
        print("   Set GITHUB_INSTALLATION_ID in .env or pass --installation-id <ID>")
        print("   (Find this by clicking 'Install App' in sidebar -> gear icon -> number in browser URL)\n")
        sys.exit(1)

    # 3. Resolve and read private key
    pem_path = resolve_key_file(args.key_path)
    print(f"✓ Key file located: {pem_path}")
    pem_text = pem_path.read_text(encoding="utf-8").strip()

    # 4. Generate RS256 JWT
    print("\n1. Generating RS256 JWT signed with private key...")
    try:
        generate_jwt(app_id, pem_text)
        print(f"✓ Signed JWT successfully generated (iss: {app_id}, valid for 9 min)")
    except Exception as exc:
        print(f"❌ Failed to generate JWT: {exc}")
        sys.exit(1)

    # 5. Exchange for installation access token
    print(f"\n2. Exchanging JWT for installation token (Installation ID: {installation_id})...")
    try:
        token = await get_installation_token(app_id, pem_text, installation_id)
        print(f"✓ Token acquired successfully! (Masked: {mask_token(token)})")
    except Exception as exc:
        print(f"❌ Failed to acquire installation token: {exc}")
        sys.exit(1)

    if args.dry_run:
        print("\n🏁 [DRY RUN] Authentication test passed! Comment not posted (--dry-run flag active).")
        print("   visorqa-bot[bot] is properly authenticated and ready for live webhooks.")
        return

    # 6. Post test PR comment
    print(f"\n3. Posting test optical telemetry report comment to {args.repo} PR #{args.pr}...")
    try:
        comment_url = await post_bot_comment(token, args.repo, args.pr)
        print("\n🎉 SUCCESS! Comment posted by visorqa-bot[bot]!")
        print(f"   View it on GitHub: {comment_url}")
    except Exception as exc:
        print(f"❌ Failed to post comment: {exc}")
        print("   Tip: If the repo or PR does not exist yet, you can test authentication only with:")
        print("        python -m backend.scripts.test_bot --dry-run")
        sys.exit(1)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
