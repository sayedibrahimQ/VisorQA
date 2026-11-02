"""Unit tests for E2B traffic access token header injection and local fallback."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.adapters.sandbox_runner import (
    E2BSandboxRunner,
    LocalWorktreeSandboxRunner,
)
from backend.core.sense import (
    E2B_TRAFFIC_HEADER,
    get_e2b_traffic_headers,
    get_e2b_traffic_token,
    is_e2b_url,
)
from backend.sandbox.factory import _resolve_name, create_sandbox_runner


class DummySandbox:
    def __init__(self, token=None, api_key=None):
        self._token = token
        self._api_key = api_key

    def get_traffic_token(self):
        return self._token


def test_is_e2b_url():
    assert is_e2b_url("https://ick9g8fdkfnb81ucvjt64-3001.e2b.dev") is True
    assert is_e2b_url("https://3001-iz99h2fqpmze7b3jn9rn5.e2b.app") is True
    assert is_e2b_url("https://test.e2b.dev/foo/bar") is True
    assert is_e2b_url("http://127.0.0.1:3001") is False
    assert is_e2b_url("http://localhost:3001") is False
    assert is_e2b_url("https://example.com") is False
    assert is_e2b_url("") is False
    assert is_e2b_url(None) is False


def test_get_e2b_traffic_token_priority(monkeypatch):
    monkeypatch.delenv("E2B_API_KEY", raising=False)

    # 1. sandbox.get_traffic_token() wins
    sbx1 = DummySandbox(token="token_from_method", api_key="token_from_attr")
    assert get_e2b_traffic_token(sbx1) == "token_from_method"

    # 2. sandbox._api_key
    sbx2 = DummySandbox(token=None, api_key="token_from_attr")
    assert get_e2b_traffic_token(sbx2) == "token_from_attr"

    # 3. os.environ["E2B_API_KEY"]
    sbx3 = DummySandbox(token=None, api_key=None)
    monkeypatch.setenv("E2B_API_KEY", "env_token_123")
    assert get_e2b_traffic_token(sbx3) == "env_token_123"
    assert get_e2b_traffic_token(None) == "env_token_123"


def test_get_e2b_traffic_headers():
    sbx = DummySandbox(token="e2b_secret_token")
    e2b_url = "https://ick9g8fdkfnb81ucvjt64-3001.e2b.dev"
    local_url = "http://127.0.0.1:3001"

    # For E2B URL: header is attached
    headers = get_e2b_traffic_headers(e2b_url, sbx)
    assert headers == {E2B_TRAFFIC_HEADER: "e2b_secret_token"}

    # For local URL: no header
    assert get_e2b_traffic_headers(local_url, sbx) == {}

    # If no token available: empty dict even for E2B URL
    empty_sbx = DummySandbox(token=None)
    with patch.dict(os.environ, {}, clear=True):
        with patch("backend.core.sense.get_e2b_traffic_token", return_value=None):
            assert get_e2b_traffic_headers(e2b_url, empty_sbx) == {}


def test_e2b_runner_get_traffic_token(monkeypatch):
    monkeypatch.setattr("backend.config.settings.E2B_API_KEY", "")
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    runner = E2BSandboxRunner(api_key="explicit_key_456")
    assert runner.get_traffic_token() == "explicit_key_456"

    runner_env = E2BSandboxRunner(api_key=None)
    monkeypatch.setenv("E2B_API_KEY", "env_key_789")
    assert runner_env.get_traffic_token() == "env_key_789"


def test_local_runner_get_traffic_token():
    runner = LocalWorktreeSandboxRunner()
    assert runner.get_traffic_token() is None


def test_sandbox_provider_local_resolution(monkeypatch):
    cfg = MagicMock()
    cfg.SANDBOX_PROVIDER = "local"
    cfg.SANDBOX_BACKEND = "local"
    cfg.E2B_API_KEY = "dummy_e2b_key_present"
    cfg.TARGET_APP_PATH = "./demo-target-app"
    cfg.TARGET_APP_PORT = 3001
    cfg.SANDBOX_LOCAL_ROOT = "/tmp/visorqa_sandboxes"

    # Even with E2B_API_KEY set, SANDBOX_PROVIDER=local resolves to "local"
    resolved = _resolve_name(cfg, None)
    assert resolved == "local"

    runner = create_sandbox_runner(cfg)
    assert isinstance(runner, LocalWorktreeSandboxRunner)
    assert str(runner.base_dir) == "/tmp/visorqa_sandboxes"


@pytest.mark.asyncio
async def test_playwright_render_live_attaches_headers():
    runner = LocalWorktreeSandboxRunner()
    runner._target_app_port = 3001
    runner.get_preview_url = AsyncMock(return_value="https://ick9g8fdkfnb81ucvjt64-3001.e2b.dev")
    runner.get_traffic_token = MagicMock(return_value="test_access_token")

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=[])
    mock_page.screenshot = AsyncMock(return_value=b"\x89PNGmock")
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
        with patch("backend.core.sense.get_e2b_traffic_token", return_value="test_access_token"):
            geometry, shot = await runner._render_live(375, 812)

    # Verify browser.new_context received extra_http_headers
    mock_browser.new_context.assert_called_once()
    call_kwargs = mock_browser.new_context.call_args.kwargs
    assert call_kwargs["extra_http_headers"] == {"e2b-traffic-access-token": "test_access_token"}
    mock_page.set_extra_http_headers.assert_called_once_with({"e2b-traffic-access-token": "test_access_token"})
    mock_page.goto.assert_called_once_with(
        "https://ick9g8fdkfnb81ucvjt64-3001.e2b.dev",
        wait_until="domcontentloaded",
        timeout=15000,
    )
    assert shot == b"\x89PNGmock"


@pytest.mark.asyncio
async def test_local_worktree_default_dev_command_and_preview(tmp_path):
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text('{"name": "test-app", "scripts": {"dev": "next dev"}}', encoding="utf-8")

    runner = LocalWorktreeSandboxRunner(source_dir=str(tmp_path), target_app_port=3001)
    runner._status.working_dir = str(tmp_path)

    cmd = runner._default_dev_command(3001)
    assert cmd == ["npm", "run", "dev", "--", "-p", "3001", "-H", "127.0.0.1"]
