"""GitHub auth + repo discovery + repo-scoped actions (mocked GitHub API)."""
import base64

import pytest
from fastapi.testclient import TestClient

import backend.api.auth as auth_mod
import backend.api.github_repos as repos_mod
from backend.main import app

USER = {"login": "octocat", "name": "Octo", "avatar_url": "https://x/a.png",
        "html_url": "https://github.com/octocat"}


@pytest.fixture()
def client(monkeypatch):
    async def fake_user(token, client=None):
        return dict(USER) if token == "good-token" else None

    monkeypatch.setattr(auth_mod, "fetch_github_user", fake_user)
    with TestClient(app) as c:
        yield c


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_oauth_login_unconfigured_is_honest(client, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "")
    resp = client.get("/api/auth/github/login", follow_redirects=False)
    assert resp.status_code == 503
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    resp = client.get("/api/auth/github/login", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith(
        "https://github.com/login/oauth/authorize?client_id=test-client-id")


def test_pat_login_then_me_and_logout(client):
    bad = client.post("/api/auth/github/token", json={"token": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/github/token", json={"token": "good-token"})
    assert ok.status_code == 200
    assert ok.json()["user"]["login"] == "octocat"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["auth_mode"] == "pat"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_repo_discovery_shapes(client, monkeypatch):
    async def fake_api(method, path, token, client=None, **kwargs):
        if path.startswith("/user/repos"):
            return 200, [{
                "full_name": "octocat/visor", "name": "visor",
                "owner": {"login": "octocat"}, "private": False,
                "default_branch": "main", "open_issues_count": 3,
                "updated_at": "2026-01-01T00:00:00Z",
                "html_url": "https://github.com/octocat/visor",
            }]
        if "/pulls" in path:
            return 200, [{
                "number": 7, "title": "Fix banner", "state": "open",
                "head": {"ref": "fix/banner", "sha": "abc1234567"},
                "base": {"ref": "main"}, "user": {"login": "octocat"},
                "updated_at": "2026-01-01T00:00:00Z",
                "html_url": "https://github.com/octocat/visor/pull/7",
            }]
        if "/branches" in path:
            return 200, [{"name": "main", "commit": {"sha": "deadbeefcafe"}}]
        return 404, {}

    monkeypatch.setattr(repos_mod, "github_api", fake_api)
    client.post("/api/auth/github/token", json={"token": "good-token"})
    repos = client.get("/api/github/repos")
    assert repos.status_code == 200
    assert repos.json()[0]["full_name"] == "octocat/visor"
    pulls = client.get("/api/github/repos/octocat/visor/pulls")
    assert pulls.json()[0]["head_sha"] == "abc1234567"
    branches = client.get("/api/github/repos/octocat/visor/branches")
    assert branches.json()[0]["sha"] == "deadbeefcafe"


def test_runs_repo_filter_never_falls_back(client, tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "BROWSER_ARTIFACTS_DIR", str(tmp_path))
    scoped = client.get("/api/runs?repo=octocat/visor")
    assert scoped.status_code == 200
    assert scoped.json() == []


def test_comment_and_commit_actions(client, tmp_path, monkeypatch):
    from backend.config import settings
    from backend.core.artifacts import ArtifactStore

    monkeypatch.setattr(settings, "BROWSER_ARTIFACTS_DIR", str(tmp_path))
    store = ArtifactStore(root=tmp_path)
    store.save_run_record({
        "id": "run-act", "pr_number": 7, "repo_name": "octocat/visor",
        "repo_full_name": "octocat/visor", "branch": "fix/banner",
        "status": "RESOLVED", "anomalies": [],
        "attempts_raw": [{
            "attempt_number": 1, "passed": True,
            "unified_diff": "--- a/src/App.tsx\n+++ b/src/App.tsx\n@@ -1,2 +1,2 @@\n-old\n+new\n ctx\n",
        }],
        "artifacts": [],
    })

    calls = {}

    async def fake_api(method, path, token, client=None, **kwargs):
        calls[path] = (method, kwargs)
        if "/comments" in path:
            return 201, {"id": 1, "html_url": "https://github.com/octocat/visor/pull/7#c1"}
        if "/contents/" in path and method == "GET":
            content = base64.b64encode(b"old\nctx\n").decode()
            return 200, {"content": content, "sha": "blobsha"}
        if "/contents/" in path and method == "PUT":
            return 201, {"commit": {"sha": "newcommitsha123",
                                    "html_url": "https://github.com/octocat/visor/commit/new"}}
        return 404, {}

    monkeypatch.setattr(repos_mod, "github_api", fake_api)
    client.post("/api/auth/github/token", json={"token": "good-token"})

    comment = client.post("/api/runs/run-act/github/comment")
    assert comment.status_code == 200
    assert comment.json()["html_url"].endswith("#c1")

    commit = client.post("/api/runs/run-act/github/commit")
    assert commit.status_code == 200
    assert commit.json()["sha"] == "newcommitsha123"
    put_body = calls["/repos/octocat/visor/contents/src/App.tsx"][1]["json"]
    assert base64.b64decode(put_body["content"]).decode() == "new\nctx\n"


def test_apply_unified_diff_verifies_context():
    from backend.api.github_repos import apply_unified_diff

    diff = "--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+c\n d\n"
    assert apply_unified_diff("a\nb\nd\n", diff) == "a\nc\nd\n"
    with pytest.raises(ValueError):
        apply_unified_diff("x\ny\nz\n", diff)
