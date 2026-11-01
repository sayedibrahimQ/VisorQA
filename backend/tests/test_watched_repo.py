"""Single watched repository: persistence, settings API, webhook filtering.

DB is offline in this environment, so these tests exercise the JSON
fallback persistence (VISORQA_WATCHED_REPO_JSON -> tmp) plus signed
webhook filtering against it. The E2B/GitHub network is never touched:
GitHub validation and FSM dispatch are monkeypatched at module seams.
"""
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.settings as settings_api
import backend.api.webhooks as webhooks
from backend.config import settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VISORQA_WATCHED_REPO_JSON", str(tmp_path / "watched_repo.json"))
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "test-secret", raising=False)
    app = FastAPI()
    app.include_router(settings_api.router)
    app.include_router(webhooks.router)
    return TestClient(app)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()


def _pr_payload(repo: str, number: int = 7) -> bytes:
    return json.dumps({
        "action": "opened",
        "pull_request": {
            "number": number,
            "title": "Fix banner overlap",
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "head": {"ref": "feat/fix", "sha": "abc1234deadbeef"},
        },
        "repository": {"full_name": repo},
    }).encode()


# -- settings API -------------------------------------------------------------

def test_watched_repo_persists_and_reads_back(client, tmp_path, monkeypatch):
    async def fake_resolve(request):
        return ("tok", "pat")

    async def fake_api(method, path, token, client=None, **kwargs):
        assert path == "/repos/octo/visor"
        return 200, {"default_branch": "main", "id": 42}

    monkeypatch.setattr(settings_api, "resolve_github_token", fake_resolve)
    monkeypatch.setattr(settings_api, "github_api", fake_api)

    assert client.get("/api/settings/watched-repo").json() is None

    resp = client.post("/api/settings/watched-repo", json={"repo_full_name": "octo/visor"})
    assert resp.status_code == 200, resp.text
    record = resp.json()["watched_repo"]
    assert record["repo_full_name"] == "octo/visor"
    assert record["default_branch"] == "main"
    assert record["auto_heal_enabled"] is True
    assert record["id"] == 1

    # "Restart": a fresh read goes through persisted storage again.
    got = client.get("/api/settings/watched-repo")
    assert got.status_code == 200
    assert got.json()["repo_full_name"] == "octo/visor"
    assert (tmp_path / "watched_repo.json").exists()


def test_watched_repo_rejects_bad_format_and_inaccessible_repo(client, monkeypatch):
    assert client.post("/api/settings/watched-repo",
                       json={"repo_full_name": "not-a-repo"}).status_code == 422

    async def fake_resolve(request):
        return ("tok", "pat")

    async def fake_api(method, path, token, client=None, **kwargs):
        return 404, {"message": "Not Found"}

    monkeypatch.setattr(settings_api, "resolve_github_token", fake_resolve)
    monkeypatch.setattr(settings_api, "github_api", fake_api)
    assert client.post("/api/settings/watched-repo",
                       json={"repo_full_name": "octo/missing"}).status_code == 422


# -- webhook filtering ----------------------------------------------------------

def _watch(client, monkeypatch, repo="octo/visor"):
    async def fake_resolve(request):
        return None

    monkeypatch.setattr(settings_api, "resolve_github_token", fake_resolve)
    monkeypatch.setattr(settings_api, "github_api",
                        _ok_api(repo))
    resp = client.post("/api/settings/watched-repo", json={"repo_full_name": repo})
    assert resp.status_code == 200, resp.text


def _ok_api(repo):
    async def fake_api(method, path, token, client=None, **kwargs):
        if "/hooks" in path:
            return 200, []
        return 200, {"default_branch": "main"}
    return fake_api


def test_webhook_ping_pong(client):
    body = b'{"zen":"ok"}'
    resp = client.post("/api/webhooks/github", content=body, headers={
        "X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "d-ping"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "pong"}


def test_webhook_bad_signature_rejected(client):
    body = _pr_payload("octo/visor")
    resp = client.post("/api/webhooks/github", content=body, headers={
        "X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "d-bad"})
    assert resp.status_code == 401


def test_webhook_ignores_unwatched_repo(client, monkeypatch):
    _watch(client, monkeypatch, "octo/visor")
    body = _pr_payload("someone/else")
    resp = client.post("/api/webhooks/github", content=body, headers={
        "X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "d-other"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert resp.json()["reason"] == "not_watched_repo"


def test_webhook_no_watched_repo_ignores_everything(client):
    body = _pr_payload("octo/visor")
    resp = client.post("/api/webhooks/github", content=body, headers={
        "X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "d-none"})
    assert resp.status_code == 200
    assert resp.json()["reason"] == "not_watched_repo"


def test_webhook_watched_repo_dispatches_fsm(client, monkeypatch):
    _watch(client, monkeypatch, "octo/visor")
    dispatched = {}

    async def fake_hydrated(state, token=""):
        dispatched["run_id"] = state.run_id
        dispatched["repo"] = state.repo_full_name
        dispatched["pr_number"] = state.pr_number
        dispatched["title"] = getattr(state, "pr_title", "")
        dispatched["branch"] = state.branch

    monkeypatch.setattr(webhooks, "_run_agent_lifecycle_hydrated", fake_hydrated)
    body = _pr_payload("Octo/Visor")  # case-insensitive repo match
    delivery_id = f"d-match-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/webhooks/github", content=body, headers={
        "X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id})
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "accepted"
    assert resp.json()["pr_number"] == 7
    assert dispatched["repo"] == "Octo/Visor"
    assert dispatched["pr_number"] == 7
    assert dispatched["title"] == "Fix banner overlap"
    assert dispatched["branch"] == "feat/fix"
