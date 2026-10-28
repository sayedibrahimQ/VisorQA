"""
Automated Test Suite for Autonomous GitHub Webhooks Listener (Jira)
Validates:
- Valid and invalid HMAC-SHA256 signatures (raw-bytes integrity)
- Missing or malformed signature headers
- Supported pull request actions (opened, synchronize, reopened) and push events
- Ignored event types (ping, issues) and unsupported PR actions (closed, labeled)
- Branch deletion push event filtering
- Database initialization failure handling (500 return so GitHub retries)
- X-GitHub-Delivery idempotency (duplicate deliveries prevent duplicate runs)
- SENSE_STARTED broadcast over WebSocket ConnectionManager
- Asynchronous agent dispatch without blocking request
- Task exception handling and FSM failure sync
- Response latency strictly adhering to the < 1.2s budget
"""

import asyncio
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
import httpx
from sqlmodel import select

from backend.main import app
from backend.config import settings
from backend.core.state import AgentState, RunStatus
from backend.db.repository import AsyncSessionLocal, PRRun
from backend.api.webhooks import _background_tasks, verify_github_signature


def make_signed_request(payload: dict, event: str = "pull_request", delivery_id: str = None, secret: str = None):
    """Helper creating raw request bytes, valid HMAC signature, and headers."""
    body = json.dumps(payload).encode("utf-8")
    key = secret or settings.GITHUB_WEBHOOK_SECRET
    sig = "sha256=" + hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "x-hub-signature-256": sig,
        "x-github-event": event,
        "x-github-delivery": delivery_id or str(uuid4()),
        "content-type": "application/json",
    }
    return body, headers


@pytest.mark.asyncio
async def test_valid_pull_request_opened_webhook():
    """Requirement 2, 4, 5, 6: Valid PR webhook accepted < 1.2s, persisted in DB, and dispatched."""
    broadcast_events = []

    async def mock_broadcast(event_type, state):
        broadcast_events.append({"event": event_type, "state": state})

    from backend.api import routes_ws
    original_broadcast = routes_ws.ws_broadcast
    routes_ws.ws_broadcast = mock_broadcast

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        delivery_id = str(uuid4())
        payload = {
            "action": "opened",
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
            "pull_request": {
                "number": 42,
                "head": {"ref": "fix/hero-cta", "sha": "a1b2c3d4e5f6"},
                "html_url": "https://github.com/sayedibrahimQ/VisorQA/pull/42",
            },
        }
        body, headers = make_signed_request(payload, event="pull_request", delivery_id=delivery_id)

        t0 = time.perf_counter()
        response = await client.post("/api/webhooks/github", content=body, headers=headers)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["delivery_id"] == delivery_id
        assert data["repo"] == "sayedibrahimQ/VisorQA"
        assert data["pr_number"] == 42
        assert data["branch"] == "fix/hero-cta"
        assert data["commit_sha"] == "a1b2c3d4e5f6"

        # Requirement 6: Performance target < 1.2 seconds (1200 ms)
        assert elapsed_ms < 1200.0, f"Acceptance latency {elapsed_ms:.2f}ms exceeded 1.2s budget"
        assert data["timing_ms"]["total"] < 1200.0

        run_id = data["run_id"]

        # Requirement 4: Verify persistence in PostgreSQL
        async with AsyncSessionLocal() as session:
            stmt = select(PRRun).where(PRRun.id == run_id)
            res = await session.execute(stmt)
            saved_run = res.scalars().first()
            assert saved_run is not None
            assert saved_run.github_delivery_id == delivery_id
            assert saved_run.repo_full_name == "sayedibrahimQ/VisorQA"
            assert saved_run.pr_number == 42

        # Requirement 5: SENSE_STARTED broadcast
        assert any(e["event"] == "SENSE_STARTED" and e["state"].run_id == run_id for e in broadcast_events)

    routes_ws.ws_broadcast = original_broadcast


@pytest.mark.asyncio
async def test_supported_pull_request_synchronize_and_reopened():
    """Requirement 3: pull_request actions 'synchronize' and 'reopened' are processed."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for action in ["synchronize", "reopened"]:
            payload = {
                "action": action,
                "repository": {"full_name": "sayedibrahimQ/VisorQA"},
                "pull_request": {
                    "number": 88,
                    "head": {"ref": "feature/modal", "sha": "c0ffee1234"},
                },
            }
            body, headers = make_signed_request(payload, event="pull_request")
            resp = await client.post("/api/webhooks/github", content=body, headers=headers)
            assert resp.status_code == 202
            assert resp.json()["status"] == "accepted"
            assert resp.json()["action"] == action


@pytest.mark.asyncio
async def test_supported_push_event():
    """Requirement 3: Valid push events are accepted and branch parsed correctly."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "ref": "refs/heads/feature/responsive-fix",
            "after": "deadbeef9999",
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
            "compare": "https://github.com/sayedibrahimQ/VisorQA/compare/a...b",
        }
        body, headers = make_signed_request(payload, event="push")
        resp = await client.post("/api/webhooks/github", content=body, headers=headers)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["branch"] == "feature/responsive-fix"
        assert data["commit_sha"] == "deadbeef9999"


@pytest.mark.asyncio
async def test_branch_deletion_push_ignored():
    """Requirement 3: Branch deletion push events are ignored without starting runs."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "ref": "refs/heads/deleted-branch",
            "after": "0000000000000000000000000000000000000000",
            "deleted": True,
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
        }
        body, headers = make_signed_request(payload, event="push")
        resp = await client.post("/api/webhooks/github", content=body, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "deletion" in resp.json()["reason"]


@pytest.mark.asyncio
async def test_unsupported_pr_actions_ignored():
    """Requirement 3: Unsupported PR actions (closed, labeled, assigned) return 200 ignored."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for action in ["closed", "labeled", "assigned", "unassigned", "review_requested"]:
            payload = {
                "action": action,
                "repository": {"full_name": "sayedibrahimQ/VisorQA"},
                "pull_request": {"number": 10},
            }
            body, headers = make_signed_request(payload, event="pull_request")
            resp = await client.post("/api/webhooks/github", content=body, headers=headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ignored"
            assert action in resp.json()["reason"]


@pytest.mark.asyncio
async def test_ignored_event_types():
    """Requirement 3: Unrelated events (ping, issues, star) return 200 ignored."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for event in ["ping", "issues", "star", "release", "fork"]:
            body, headers = make_signed_request({"zen": "Keep it simple"}, event=event)
            resp = await client.post("/api/webhooks/github", content=body, headers=headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ignored"
            assert event in resp.json()["reason"]


@pytest.mark.asyncio
async def test_missing_or_invalid_hmac_signatures():
    """Requirement 2: Reject missing, malformed, or invalid signatures with 401."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"action": "opened"}
        body = json.dumps(payload).encode("utf-8")

        # 1. Missing signature header
        resp = await client.post("/api/webhooks/github", content=body, headers={"x-github-event": "pull_request"})
        assert resp.status_code == 401

        # 2. Malformed signature (missing sha256= prefix)
        resp = await client.post(
            "/api/webhooks/github",
            content=body,
            headers={"x-github-event": "pull_request", "x-hub-signature-256": "abcdef123456"},
        )
        assert resp.status_code == 401

        # 3. Wrong signature hash
        resp = await client.post(
            "/api/webhooks/github",
            content=body,
            headers={"x-github-event": "pull_request", "x-hub-signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 401

        # 4. Tampered body bytes
        _, valid_headers = make_signed_request(payload, event="pull_request")
        tampered_body = json.dumps({"action": "opened", "tampered": True}).encode("utf-8")
        resp = await client.post("/api/webhooks/github", content=tampered_body, headers=valid_headers)
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_payload_too_large_rejected_413():
    """Requirement 2: Enforce request size limit."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "x-github-event": "pull_request",
            "content-length": str(10 * 1024 * 1024),  # 10 MB
        }
        resp = await client.post("/api/webhooks/github", content=b"fake", headers=headers)
        assert resp.status_code == 413


@pytest.mark.asyncio
async def test_idempotency_duplicate_delivery_id():
    """Requirement 4: Duplicate delivery IDs must not create duplicate runs."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        delivery_id = f"delivery-idemp-{uuid4().hex[:8]}"
        payload = {
            "action": "opened",
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
            "pull_request": {"number": 123, "head": {"ref": "fix/test", "sha": "123456"}},
        }
        body, headers = make_signed_request(payload, delivery_id=delivery_id)

        # First delivery -> 202 Accepted
        resp1 = await client.post("/api/webhooks/github", content=body, headers=headers)
        assert resp1.status_code == 202
        run_id1 = resp1.json()["run_id"]

        # Duplicate delivery -> 200 Duplicate with same run_id
        resp2 = await client.post("/api/webhooks/github", content=body, headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "duplicate"
        assert resp2.json()["run_id"] == run_id1


@pytest.mark.asyncio
async def test_database_initialization_failure_returns_500(monkeypatch):
    """Requirement 4 & 6: Database failure returns 500 without agent dispatch or broadcast."""
    from backend.db.repository import RunRepository

    async def fail_create_run(*args, **kwargs):
        raise ConnectionRefusedError("PostgreSQL connection lost")

    monkeypatch.setattr(RunRepository, "create_run", fail_create_run)

    broadcast_called = False

    async def mock_bc(*args, **kwargs):
        nonlocal broadcast_called
        broadcast_called = True

    from backend.api import routes_ws
    monkeypatch.setattr(routes_ws, "ws_broadcast", mock_bc)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "action": "opened",
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
            "pull_request": {"number": 999},
        }
        body, headers = make_signed_request(payload)
        resp = await client.post("/api/webhooks/github", content=body, headers=headers)

        assert resp.status_code == 500
        assert "database" in resp.json()["detail"].lower()
        # Verify no broadcast was dispatched
        assert broadcast_called is False


@pytest.mark.asyncio
async def test_agent_dispatch_is_non_blocking_and_async(monkeypatch):
    """Requirement 5 & 6: Webhook returns immediately (< 1.2s) while agent runs asynchronously in background."""
    agent_completed = asyncio.Event()

    async def slow_agent_lifecycle(state: AgentState):
        await asyncio.sleep(0.3)
        agent_completed.set()

    import backend.api.webhooks as webhooks_module
    monkeypatch.setattr(webhooks_module, "_run_agent_lifecycle", slow_agent_lifecycle)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "action": "opened",
            "repository": {"full_name": "sayedibrahimQ/VisorQA"},
            "pull_request": {"number": 77},
        }
        body, headers = make_signed_request(payload)

        t0 = time.perf_counter()
        resp = await client.post("/api/webhooks/github", content=body, headers=headers)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        assert resp.status_code == 202
        # Fast HTTP return: well below 1.2 seconds, and agent hasn't finished yet
        assert latency_ms < 300.0, f"HTTP return took {latency_ms:.2f}ms, expected non-blocking < 300ms"
        assert not agent_completed.is_set(), "Agent should execute in background, not block HTTP response"

        # Wait for background task to complete
        await asyncio.wait_for(agent_completed.wait(), timeout=1.0)
        assert agent_completed.is_set()


@pytest.mark.asyncio
async def test_background_agent_task_exception_handling():
    """Requirement 5: Background agent task catches exceptions, marks run FAILED, and broadcasts RUN_HALTED."""
    import backend.api.webhooks as webhooks_module

    broadcasts = []

    async def mock_ws_broadcast(event_type, state):
        broadcasts.append((event_type, state.status))

    from backend.api import routes_ws
    routes_ws.ws_broadcast = mock_ws_broadcast

    # Create run in DB
    async with AsyncSessionLocal() as session:
        from backend.db.repository import RunRepository
        repo = RunRepository(session)
        run = await repo.create_run(pr_number=555, repo_name="sayedibrahimQ/VisorQA", commit_sha="fail_sha")

    failing_state = AgentState(
        run_id=run.id,
        repo_full_name="sayedibrahimQ/VisorQA",
        pr_number=555,
        commit_sha="fail_sha",
    )

    # Monkeypatch run_visor_agent to raise unexpected error
    import backend.core.orchestrator as orch_module
    async def crash_agent(state, ws_broadcast=None):
        raise RuntimeError("Unexpected container crash")

    orch_module.run_visor_agent = crash_agent

    # Run background worker directly
    await webhooks_module._run_agent_lifecycle(failing_state)

    # Assert broadcast RUN_HALTED
    assert any(event == "RUN_HALTED" for event, _ in broadcasts)

    # Assert DB was updated to FAILED
    async with AsyncSessionLocal() as session:
        stmt = select(PRRun).where(PRRun.id == run.id)
        res = await session.execute(stmt)
        saved = res.scalars().first()
        assert saved.status == "FAILED"


@pytest.mark.asyncio
async def test_response_latency_benchmark_under_1200ms():
    """Requirement 6: Benchmark measuring 10 sequential webhook deliveries,

    all strictly completing in < 1200 ms.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        latencies = []
        for i in range(10):
            payload = {
                "action": "opened",
                "repository": {"full_name": "sayedibrahimQ/VisorQA"},
                "pull_request": {"number": 1000 + i, "head": {"ref": f"branch-{i}", "sha": f"sha-{i}"}},
            }
            body, headers = make_signed_request(payload, delivery_id=str(uuid4()))

            t0 = time.perf_counter()
            resp = await client.post("/api/webhooks/github", content=body, headers=headers)
            elapsed = (time.perf_counter() - t0) * 1000.0

            assert resp.status_code == 202
            latencies.append(elapsed)
            assert elapsed < 1200.0, f"Delivery {i} latency {elapsed:.2f}ms exceeded 1.2s budget"

        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        min_lat = min(latencies)
        print(f"\n[LATENCY BENCHMARK] 10 Deliveries: min={min_lat:.2f}ms, avg={avg_lat:.2f}ms, max={max_lat:.2f}ms (Budget: 1200ms)")
        assert max_lat < 1200.0
        # Normal execution without network overhead should comfortably be < 200 ms
        assert avg_lat < 300.0, f"Average latency {avg_lat:.2f}ms higher than expected"
