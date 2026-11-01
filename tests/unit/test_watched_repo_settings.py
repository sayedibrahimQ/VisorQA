"""POST /api/settings/watched-repo: private-repo token fallback.

Regression: a private repo visible via GITHUB_PAT (and via
GET /api/github/repos) but 404 for the session OAuth token must save
successfully, and a failing optional webhook registration must never
block saving.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import backend.api.settings as settings_api
from backend.config import settings


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/settings/watched-repo", "headers": []})


@pytest.fixture(autouse=True)
def _capture_save(monkeypatch):
    saved = {}

    def fake_save(repo_full_name, default_branch="main", installation_id=None,
                  webhook_active=False, auto_heal_enabled=True):
        saved.update(repo_full_name=repo_full_name, default_branch=default_branch,
                     webhook_active=webhook_active)
        return {"id": 1, "repo_full_name": repo_full_name,
                "default_branch": default_branch, "installation_id": installation_id,
                "webhook_active": webhook_active, "auto_heal_enabled": auto_heal_enabled,
                "updated_at": "2026-01-01T00:00:00Z"}

    monkeypatch.setattr(settings_api, "save_watched_repository", fake_save)
    monkeypatch.setattr(settings, "GITHUB_PAT", "pat-token")
    monkeypatch.setattr(settings, "WEBHOOK_PUBLIC_URL", "")
    return saved


async def _no_app_token():
    return None


def _install(monkeypatch, github_api):
    async def fake_resolve(request):
        return ("session-token", "oauth")

    monkeypatch.setattr(settings_api, "resolve_github_token", fake_resolve)
    monkeypatch.setattr(settings_api, "github_api", github_api)
    if hasattr(settings_api, "app_installation_token"):
        monkeypatch.setattr(settings_api, "app_installation_token", _no_app_token)


async def test_session_404_falls_back_to_pat(monkeypatch, _capture_save):
    async def fake_github_api(method, path, token, **kwargs):
        if path == "/repos/sayedibrahimQ/BM_Project":
            if token == "session-token":
                return 404, {"message": "Not Found"}
            return 200, {"default_branch": "develop"}
        if "/hooks" in path:
            return 200, []
        return 404, {}

    _install(monkeypatch, fake_github_api)
    result = await settings_api.set_watched_repo(
        settings_api.WatchedRepoRequest(repo_full_name="sayedibrahimQ/BM_Project"), _request())
    assert result["watched_repo"]["repo_full_name"] == "sayedibrahimQ/BM_Project"
    assert result["watched_repo"]["default_branch"] == "develop"
    assert _capture_save["repo_full_name"] == "sayedibrahimQ/BM_Project"


async def test_webhook_403_never_blocks_saving(monkeypatch, _capture_save):
    monkeypatch.setattr(settings, "WEBHOOK_PUBLIC_URL", "https://visorqa.sayedibrahim.com")

    async def fake_github_api(method, path, token, **kwargs):
        if path == "/repos/sayedibrahimQ/BM_Project":
            return 200, {"default_branch": "main"}
        if path.endswith("/hooks?per_page=100"):
            return 403, {"message": "Forbidden"}
        if path.endswith("/hooks"):
            return 403, {"message": "Forbidden"}
        return 404, {}

    _install(monkeypatch, fake_github_api)
    result = await settings_api.set_watched_repo(
        settings_api.WatchedRepoRequest(repo_full_name="sayedibrahimQ/BM_Project"), _request())
    assert result["watched_repo"]["repo_full_name"] == "sayedibrahimQ/BM_Project"
    assert result["webhook"]["webhook_active"] is False


async def test_repo_in_user_repo_list_validates_despite_direct_404(monkeypatch, _capture_save):
    async def fake_github_api(method, path, token, **kwargs):
        if path == "/repos/sayedibrahimQ/BM_Project":
            return 404, {"message": "Not Found"}
        if path.startswith("/user/repos"):
            return 200, [{"full_name": "sayedibrahimQ/BM_Project", "default_branch": "main"}]
        if "/hooks" in path:
            return 200, []
        return 404, {}

    _install(monkeypatch, fake_github_api)
    result = await settings_api.set_watched_repo(
        settings_api.WatchedRepoRequest(repo_full_name="sayedibrahimQ/BM_Project"), _request())
    assert result["watched_repo"]["repo_full_name"] == "sayedibrahimQ/BM_Project"


async def test_truly_inaccessible_repo_still_rejected(monkeypatch, _capture_save):
    async def fake_github_api(method, path, token, **kwargs):
        return 404, {"message": "Not Found"}

    _install(monkeypatch, fake_github_api)
    with pytest.raises(HTTPException) as exc:
        await settings_api.set_watched_repo(
            settings_api.WatchedRepoRequest(repo_full_name="ghost/nope"), _request())
    assert exc.value.status_code == 422
