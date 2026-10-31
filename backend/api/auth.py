"""GitHub authentication: OAuth web flow + PAT/App instant login.

Session model: server-side in-memory sessions keyed by an HttpOnly cookie
(`visorqa_session`). OAuth is offered only when GITHUB_CLIENT_ID/SECRET are
configured; instant login validates a supplied PAT (or the configured
GitHub App installation / env PAT) against the live GitHub API. No tokens
are ever returned to the browser beyond the session cookie.
"""
from __future__ import annotations

import secrets as _secrets
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend.config import settings

router = APIRouter(prefix="/api/auth", tags=["GitHub Auth"])

SESSION_COOKIE = "visorqa_session"
GITHUB_API = "https://api.github.com"

# sid -> {"user": {...}, "token": str, "auth_mode": str}
_sessions: Dict[str, Dict[str, Any]] = {}


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def github_api(
    method: str, path: str, token: str,
    client: Optional[httpx.AsyncClient] = None, **kwargs: Any,
) -> Tuple[int, Any]:
    """One GitHub API call. Returns (status, parsed_json_or_text)."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    if client is not None:
        resp = await client.request(method, url, headers=_headers(token), **kwargs)
    else:
        async with httpx.AsyncClient(timeout=20.0) as owned:
            resp = await owned.request(method, url, headers=_headers(token), **kwargs)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


async def fetch_github_user(token: str,
                            client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
    status, body = await github_api("GET", "/user", token, client)
    if status != 200 or not isinstance(body, dict):
        return None
    return {
        "login": body.get("login"),
        "name": body.get("name"),
        "avatar_url": body.get("avatar_url"),
        "html_url": body.get("html_url"),
    }


async def app_installation_token() -> Optional[str]:
    """Installation token from the configured GitHub App, when usable."""
    try:
        from backend.adapters.github_app import GitHubAppAuth
        auth = GitHubAppAuth()
        if not auth.is_configured():
            return None
        return await auth.get_installation_token()
    except Exception:
        return None


async def resolve_github_token(request: Optional[Request]) -> Optional[Tuple[str, str]]:
    """(token, auth_mode) for GitHub API calls: session -> App -> env PAT."""
    if request is not None:
        session = current_session(request)
        if session:
            return session["token"], session["auth_mode"]
    token = await app_installation_token()
    if token:
        return token, "github_app"
    pat = (settings.GITHUB_PAT or "").strip()
    if pat:
        return pat, "pat"
    return None


def current_session(request: Request) -> Optional[Dict[str, Any]]:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in _sessions:
        return _sessions[sid]
    return None


def _create_session(user: Dict[str, Any], token: str, auth_mode: str,
                    response: JSONResponse) -> JSONResponse:
    sid = _secrets.token_urlsafe(32)
    _sessions[sid] = {"user": user, "token": token, "auth_mode": auth_mode}
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax",
                        path="/", max_age=60 * 60 * 12)
    return response


def _public_user(session: Dict[str, Any]) -> Dict[str, Any]:
    return {**session["user"], "auth_mode": session["auth_mode"]}


# ---------------------------------------------------------------------------
# OAuth web flow
# ---------------------------------------------------------------------------

@router.get("/github/login")
async def github_login() -> Any:
    client_id = (settings.GITHUB_CLIENT_ID or "").strip()
    if not client_id:
        return JSONResponse(
            {"detail": "GitHub OAuth is not configured (GITHUB_CLIENT_ID empty). "
                       "Use POST /api/auth/github/token with a PAT or the configured GitHub App."},
            status_code=503)
    state = _secrets.token_urlsafe(16)
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}&scope=repo%20read:user&state={state}"
    )
    response = RedirectResponse(url, status_code=307)
    response.set_cookie("visorqa_oauth_state", state, httponly=True,
                        samesite="lax", path="/", max_age=600)
    return response


@router.get("/github/callback")
async def github_callback(request: Request, code: str = "", state: str = "") -> Any:
    client_id = (settings.GITHUB_CLIENT_ID or "").strip()
    client_secret = (settings.GITHUB_CLIENT_SECRET or "").strip()
    frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    if not client_id or not client_secret or not code:
        return RedirectResponse(f"{frontend}/mission-control?auth_error=oauth_not_configured",
                                status_code=307)
    if state != request.cookies.get("visorqa_oauth_state", ""):
        return RedirectResponse(f"{frontend}/mission-control?auth_error=state_mismatch",
                                status_code=307)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"})
        try:
            token_body = resp.json()
        except Exception:
            token_body = {}
        token = token_body.get("access_token")
        if not token:
            return RedirectResponse(f"{frontend}/mission-control?auth_error=token_exchange_failed",
                                    status_code=307)
        user = await fetch_github_user(token, client)
    if not user:
        return RedirectResponse(f"{frontend}/mission-control?auth_error=user_fetch_failed",
                                status_code=307)
    response = RedirectResponse(f"{frontend}/mission-control?auth=ok", status_code=307)
    return _create_session(user, token, "oauth", response)


# ---------------------------------------------------------------------------
# Instant login (PAT / GitHub App) + session endpoints
# ---------------------------------------------------------------------------

class TokenLoginRequest(BaseModel):
    token: Optional[str] = None


@router.post("/github/token")
async def github_token_login(payload: TokenLoginRequest) -> Any:
    """Login with a PAT, or with the configured App/env credentials."""
    token = (payload.token or "").strip()
    mode = "pat"
    if token:
        user = await fetch_github_user(token)
        if not user:
            return JSONResponse({"detail": "GitHub rejected the supplied token"}, status_code=401)
        response = JSONResponse({"user": {**user, "auth_mode": mode}})
        return _create_session(user, token, mode, response)

    # No token supplied: configured GitHub App installation, else env PAT.
    app_token = await app_installation_token()
    if app_token:
        user = {"login": "github-app[bot]", "name": "GitHub App Installation",
                "avatar_url": "", "html_url": ""}
        response = JSONResponse({"user": {**user, "auth_mode": "github_app"}})
        return _create_session(user, app_token, "github_app", response)

    env_pat = (settings.GITHUB_PAT or "").strip()
    if env_pat:
        user = await fetch_github_user(env_pat)
        if not user:
            return JSONResponse({"detail": "Configured GITHUB_PAT was rejected by GitHub"},
                                status_code=401)
        response = JSONResponse({"user": {**user, "auth_mode": "pat"}})
        return _create_session(user, env_pat, "pat", response)

    return JSONResponse(
        {"detail": "No GitHub credentials configured (set GITHUB_PAT or the GitHub App, "
                   "or supply a token)"}, status_code=503)


@router.get("/me")
async def me(request: Request) -> Any:
    session = current_session(request)
    if not session:
        return JSONResponse({"detail": "unauthenticated"}, status_code=401)
    return _public_user(session)


@router.post("/logout")
async def logout(request: Request) -> Any:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        _sessions.pop(sid, None)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
