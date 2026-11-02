"""Empirical Challenger stress tests for E2B sandbox, traffic tokens, readiness probe, and local fallback.

Stress-tests:
1. Readiness probe rejection under 403, 404, 502, pseudo-200 token error pages, and acceptance of genuine 200 OK.
2. Playwright live capture guardrails preventing error screens from being captured.
3. Traffic token extraction permutations across attribute variations and None values.
4. Automatic local worktree fallback and process lifecycle termination without orphaned processes.
5. Case sensitivity and bypass vulnerability testing.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
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
)
from backend.sandbox.interface import ServerState


# ==============================================================================
# SCENARIO 1: READINESS PROBE STRESS TESTS
# ==============================================================================

class MockHttpResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _eval_readiness(status_code: int, text: str) -> bool:
    """Exact readiness probe logic implemented in E2BSandboxRunner.start_dev_server (lines 775-778)."""
    if status_code == 200:
        if not any(
            err in text
            for err in (
                "MISSING TRAFFIC ACCESS TOKEN",
                "403 Forbidden",
                "403 FORBIDDEN",
                "Bad Gateway",
            )
        ):
            return True
    return False


@pytest.mark.parametrize(
    "status_code,body,expected_ready",
    [
        (403, "403 FORBIDDEN — MISSING TRAFFIC ACCESS TOKEN — The sandbox requires a traffic access token.", False),
        (403, "Forbidden", False),
        (404, "404 Not Found - Sandbox dev server not listening", False),
        (502, "502 Bad Gateway - E2B ingress proxy unreachable", False),
        (500, "Internal Server Error", False),
        (503, "Service Unavailable", False),
        (200, "403 FORBIDDEN — MISSING TRAFFIC ACCESS TOKEN — The sandbox requires a traffic access token.", False),
        (200, "<html><head><title>403 Forbidden</title></head><body>403 Forbidden</body></html>", False),
        (200, "<html><body>502 Bad Gateway - Connection refused by upstream</body></html>", False),
        (200, "Error: MISSING TRAFFIC ACCESS TOKEN in request header", False),
        (200, '<!DOCTYPE html><html><body><div data-visor-id="visor-el-01">AETHER LABS</div></body></html>', True),
        (200, '{"status": "ok", "message": "Development server ready"}', True),
    ],
)
def test_readiness_probe_matrix(status_code: int, body: str, expected_ready: bool):
    """Assert that only genuine 200 OK without error markers evaluates to ready=True."""
    ready = _eval_readiness(status_code, body)
    assert ready == expected_ready, (
        f"Failed for status={status_code}, body={body!r}: expected ready={expected_ready}, got {ready}"
    )


def test_readiness_probe_case_sensitivity_challenge():
    """Empirical challenge: Demonstrates that lowercase error strings bypass the current probe check.

    If an upstream proxy emits lowercase 'bad gateway' or 'missing traffic access token',
    the current probe would evaluate to ready=True if status is 200.
    """
    assert _eval_readiness(200, "502 Bad Gateway") is False
    assert _eval_readiness(200, "MISSING TRAFFIC ACCESS TOKEN") is False

    # Challenge finding: Lowercase variants pass the probe if status is 200
    lowercase_bypass = _eval_readiness(200, "bad gateway error")
    assert lowercase_bypass is True, "Documenting probe case sensitivity: lowercase 'bad gateway' bypasses check"


@pytest.mark.asyncio
async def test_e2b_start_dev_server_readiness_loop_rejects_and_falls_back(tmp_path):
    """Empirically test that when E2B preview repeatedly returns 403/502/error-body,

    the readiness loop times out, calls _kill_e2b(), and cleanly falls back to the local runner.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "package.json").write_text('{"name":"test-app","scripts":{"dev":"echo ok"}}', encoding="utf-8")

    runner = E2BSandboxRunner(source_dir=str(app_dir), api_key="test-api-key")
    runner._e2b_active = True
    runner._sandbox_id = "test-sbx-999"
    runner._status.working_dir = str(app_dir)

    fake_sbx = MagicMock()
    fake_sbx.get_host.return_value = "sbx-test.e2b.dev"
    kill_called = False

    async def fake_kill():
        nonlocal kill_called
        kill_called = True

    fake_sbx.kill = AsyncMock(side_effect=fake_kill)
    runner._sandbox = fake_sbx

    # Simulate E2B returning 403 Forbidden with missing traffic token error
    error_resp = MockHttpResponse(
        403,
        "403 FORBIDDEN — MISSING TRAFFIC ACCESS TOKEN — The sandbox requires a traffic access token.",
    )

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=error_resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=None)

    async def fake_super_start():
        # Mimic LocalSandboxRunner.start_dev_server assigning localhost preview
        runner._status.preview_url = "http://127.0.0.1:3001"
        runner._status.server_state = ServerState.RUNNING
        return runner._status

    with patch("httpx.AsyncClient", return_value=client_mock):
        with patch.object(runner, "_kill_e2b", wraps=runner._kill_e2b) as spy_kill:
            with patch.object(LocalWorktreeSandboxRunner, "start_dev_server", side_effect=fake_super_start):
                with patch.object(LocalWorktreeSandboxRunner, "ensure_workspace", AsyncMock(return_value=app_dir)):
                    time_values = [0.0, 1.0, 5.0, 30.0]  # will exceed 25.0s deadline on next check
                    with patch("time.monotonic", side_effect=lambda: time_values.pop(0) if time_values else 100.0):
                        status = await runner.start_dev_server()

    # Verify fallback occurred
    assert kill_called is True
    assert spy_kill.called
    assert "E2B dev server failed" in runner._fallback_reason
    assert "did not become ready" in runner._fallback_reason
    assert status.preview_url == "http://127.0.0.1:3001"
    assert status.server_state == ServerState.RUNNING


# ==============================================================================
# SCENARIO 2: PLAYWRIGHT LIVE CAPTURE GUARDRAILS
# ==============================================================================

@pytest.mark.asyncio
async def test_render_live_rejects_all_http_error_codes():
    """Verify Playwright navigation throws if status is 403, 404, or 502."""
    for error_code in (403, 404, 502, 500):
        runner = LocalWorktreeSandboxRunner()
        runner.get_preview_url = AsyncMock(return_value="https://test.e2b.dev")
        mock_browser = MagicMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = error_code
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
            with pytest.raises(RuntimeError, match=f"Playwright navigation received HTTP {error_code}"):
                await runner._render_live(375, 812)


@pytest.mark.asyncio
async def test_render_live_rejects_error_titles():
    """Verify Playwright throws if title indicates a gateway error even if status was 200."""
    for title in ("403 Forbidden", "502 Bad Gateway", "Forbidden - Access Denied"):
        runner = LocalWorktreeSandboxRunner()
        runner.get_preview_url = AsyncMock(return_value="https://test.e2b.dev")
        mock_browser = MagicMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_page.title = AsyncMock(return_value=title)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
            with pytest.raises(RuntimeError, match="Playwright loaded gateway error page"):
                await runner._render_live(375, 812)


@pytest.mark.asyncio
async def test_render_live_rejects_error_body_text():
    """Verify Playwright throws if body text contains traffic token error strings."""
    for err_snippet in (
        "403 FORBIDDEN — MISSING TRAFFIC ACCESS TOKEN — The sandbox requires a traffic access token.",
        "MISSING TRAFFIC ACCESS TOKEN",
        "403 Forbidden",
        "403 FORBIDDEN",
        "502 Bad Gateway: upstream connect error",
    ):
        runner = LocalWorktreeSandboxRunner()
        runner.get_preview_url = AsyncMock(return_value="https://test.e2b.dev")
        mock_browser = MagicMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_page.title = AsyncMock(return_value="VisorQA")
        mock_page.inner_text = AsyncMock(return_value=f"Error occurred: {err_snippet}")
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
            with pytest.raises(RuntimeError, match="Playwright loaded E2B missing traffic access token error screen"):
                await runner._render_live(375, 812)


@pytest.mark.asyncio
async def test_render_live_e2b_url_requires_visor_id_nodes():
    """Verify that on an E2B URL (*.e2b.dev), if no [data-visor-id] node exists, it throws."""
    runner = LocalWorktreeSandboxRunner()
    runner.get_preview_url = AsyncMock(return_value="https://test.e2b.dev")
    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_page.title = AsyncMock(return_value="VisorQA App")
    mock_page.inner_text = AsyncMock(return_value="Welcome to the application without tags")
    mock_page.evaluate = AsyncMock(return_value=False)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
        with pytest.raises(RuntimeError, match="without \\[data-visor-id\\] application nodes"):
            await runner._render_live(375, 812)


@pytest.mark.asyncio
async def test_render_live_valid_200_with_visor_id_succeeds():
    """Verify that a genuine 200 OK with [data-visor-id] nodes succeeds and extracts geometry & screenshot."""
    runner = LocalWorktreeSandboxRunner()
    runner.get_preview_url = AsyncMock(return_value="https://test.e2b.dev")
    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_page.title = AsyncMock(return_value="AETHER // LABS Storefront")
    mock_page.inner_text = AsyncMock(return_value="AETHER LABS Confirm & Pay $189.00")

    async def fake_evaluate(script):
        if "document.querySelector(" in str(script):
            return True
        # Geometry JS
        return [
            {
                "element_id": "visor-el-01",
                "visor_el_id": "visor-el-01",
                "visor_tagged": True,
                "tag": "header",
                "visibility_ratio": 1.0,
                "v_r": 1.0,
                "bounding_box": {"x": 0, "y": 0, "width": 375, "height": 60},
            }
        ]

    mock_page.evaluate = AsyncMock(side_effect=fake_evaluate)
    mock_page.screenshot = AsyncMock(return_value=b"\x89PNG_VALID_SCREENSHOT")
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    with patch("backend.adapters.sandbox_runner.launch_chromium", AsyncMock(return_value=mock_browser)):
        with patch("backend.browser.renderer.extract_hierarchy", AsyncMock(return_value=[])):
            geometry, shot = await runner._render_live(375, 812)

    assert shot == b"\x89PNG_VALID_SCREENSHOT"
    assert len(geometry) == 1
    assert geometry[0]["element_id"] == "visor-el-01"


@pytest.mark.asyncio
async def test_capture_screenshot_auto_fallback_on_render_failure():
    """Verify that if E2B screenshot capture fails due to an error screen,

    E2BSandboxRunner._kill_e2b() is called and screenshot is obtained from local fallback.
    """
    runner = E2BSandboxRunner(api_key="test-key")
    runner._e2b_active = True
    runner._sandbox_id = "sbx-active-123"
    runner._sandbox = MagicMock()
    runner._sandbox.kill = AsyncMock()

    calls = []

    async def fake_super_capture(w, h):
        calls.append("capture")
        if runner._e2b_active:
            raise RuntimeError("Playwright loaded gateway error page")
        return b"\x89PNG_LOCAL_FALLBACK_OK"

    with patch.object(LocalWorktreeSandboxRunner, "capture_screenshot", side_effect=fake_super_capture):
        with patch.object(LocalWorktreeSandboxRunner, "ensure_workspace", AsyncMock(return_value=Path("/tmp/ws"))):
            with patch.object(LocalWorktreeSandboxRunner, "start_dev_server", AsyncMock()):
                img = await runner.capture_screenshot(375, 812)

    assert img == b"\x89PNG_LOCAL_FALLBACK_OK"
    assert runner.e2b_active is False
    assert runner.sandbox_id == ""
    assert "E2B screenshot failed" in runner._fallback_reason
    assert len(calls) == 2


# ==============================================================================
# SCENARIO 3: TRAFFIC TOKEN EXTRACTION LOGIC
# ==============================================================================

class DummySandboxObj:
    pass


def test_traffic_token_extraction_permutations(monkeypatch):
    """Test all attribute conventions, nested objects, and edge cases."""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.setattr("backend.config.settings.E2B_API_KEY", "")

    # 1. snake_case
    s1 = DummySandboxObj()
    s1.traffic_access_token = "tok_snake_123"
    assert get_e2b_traffic_token(s1) == "tok_snake_123"

    # 2. camelCase
    s2 = DummySandboxObj()
    s2.trafficAccessToken = "tok_camel_456"
    assert get_e2b_traffic_token(s2) == "tok_camel_456"

    # 3. leading underscore
    s3 = DummySandboxObj()
    s3._traffic_access_token = "tok_private_789"
    assert get_e2b_traffic_token(s3) == "tok_private_789"

    # 4. Whitespace trimming in runner.get_traffic_token()
    runner = E2BSandboxRunner(api_key="base-key")
    runner._sandbox = DummySandboxObj()
    runner._sandbox.traffic_access_token = "   trimmed_tok_abc   "
    assert runner.get_traffic_token() == "trimmed_tok_abc"

    # 5. Empty string attribute -> falls back gracefully
    s5 = DummySandboxObj()
    s5.traffic_access_token = ""
    s5._api_key = "fallback_api_key"
    assert get_e2b_traffic_token(s5) == "fallback_api_key"

    # 6. Nested _sandbox attribute
    s6 = DummySandboxObj()
    s6._sandbox = DummySandboxObj()
    s6._sandbox.trafficAccessToken = "nested_tok_999"
    assert get_e2b_traffic_token(s6) == "nested_tok_999"

    # 7. get_traffic_token() method raising exception -> does not crash, falls back
    s7 = DummySandboxObj()
    def failing_fn():
        raise RuntimeError("boom")
    s7.get_traffic_token = failing_fn
    s7._api_key = "surviving_key"
    assert get_e2b_traffic_token(s7) == "surviving_key"

    # 8. Sandbox is None -> falls back to env or settings
    monkeypatch.setenv("E2B_API_KEY", "env_e2b_key")
    assert get_e2b_traffic_token(None) == "env_e2b_key"

    # 9. Header generation across various domains
    assert get_e2b_traffic_headers("https://test.e2b.dev", s1) == {E2B_TRAFFIC_HEADER: "tok_snake_123"}
    assert get_e2b_traffic_headers("https://test.e2b.app", s1) == {E2B_TRAFFIC_HEADER: "tok_snake_123"}
    assert get_e2b_traffic_headers("http://127.0.0.1:3001", s1) == {}
    assert get_e2b_traffic_headers("http://localhost:3000", s1) == {}
    assert get_e2b_traffic_headers("", s1) == {}
    assert get_e2b_traffic_headers(None, s1) == {}


# ==============================================================================
# SCENARIO 4: LOCAL WORKTREE FALLBACK & PROCESS LIFECYCLE (ZERO ORPHANED PROCESSES)
# ==============================================================================

@pytest.mark.asyncio
async def test_process_lifecycle_terminate_cleans_process_group(tmp_path):
    """Empirically test that LocalSandboxRunner spawns a process in a new session

    and terminate() cleanly kills the process group without orphaned processes.
    """
    runner = LocalWorktreeSandboxRunner(source_dir=str(tmp_path), target_app_port=3001)
    runner._status.working_dir = str(tmp_path)

    # Spawn a real long-running sleep process in its own session to verify process group killing
    proc = subprocess.Popen(
        ["sleep", "120"],
        cwd=str(tmp_path),
        start_new_session=True,
    )
    runner._proc = proc
    runner._status.server_pid = proc.pid

    pid = proc.pid
    pgid = os.getpgid(pid)
    assert pgid == pid  # confirmed leader of own session/process group

    # Verify process is actively running in OS
    assert os.kill(pid, 0) is None  # no error = alive

    # Terminate runner
    await runner.terminate()

    # Assert runner state is cleared
    assert runner._proc is None
    assert runner._status.server_state == ServerState.STOPPED
    assert runner._status.server_pid is None

    # Assert the OS process is actually dead (poll / wait)
    await asyncio.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_e2b_kill_lifecycle_cleanup():
    """Verify _kill_e2b() resets all active E2B state and calls sandbox.kill()."""
    runner = E2BSandboxRunner(api_key="test-key")
    runner._e2b_active = True
    runner._sandbox_id = "sbx-to-kill"
    runner._status.preview_url = "https://sbx-to-kill.e2b.dev"
    runner._status.working_dir = "/tmp/fake-dir"

    mock_sbx = MagicMock()
    kill_called = False

    async def mock_kill():
        nonlocal kill_called
        kill_called = True

    mock_sbx.kill = AsyncMock(side_effect=mock_kill)
    runner._sandbox = mock_sbx

    await runner._kill_e2b()

    assert kill_called is True
    assert runner._sandbox is None
    assert runner._e2b_active is False
    assert runner._sandbox_id == ""
    assert runner._status.preview_url is None
    assert runner._status.working_dir == ""
