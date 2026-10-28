import pytest
import hmac
import hashlib
import json
import httpx
from backend.main import app
from backend.config import settings

@pytest.mark.asyncio
async def test_api_health_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "VisorQA Backend"
        assert "math_thresholds" in data

@pytest.mark.asyncio
async def test_api_runs_list():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "pr_number" in data[0]

@pytest.mark.asyncio
async def test_api_run_details():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/runs/run-demo-42")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "run-demo-42"
        assert "anomalies" in data

@pytest.mark.asyncio
async def test_github_webhook_hmac_valid():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"action": "opened", "pull_request": {"number": 101}}
        body = json.dumps(payload).encode()
        
        signature = "sha256=" + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "x-hub-signature-256": signature,
            "x-github-event": "pull_request",
            "Content-Type": "application/json"
        }
        response = await client.post("/api/webhooks/github", content=body, headers=headers)
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"

@pytest.mark.asyncio
async def test_github_webhook_hmac_invalid():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"action": "opened", "pull_request": {"number": 101}}
        body = json.dumps(payload).encode()
        
        headers = {
            "x-hub-signature-256": "sha256=invalid_hash_signature",
            "x-github-event": "pull_request",
            "Content-Type": "application/json"
        }
        # In non-test mode with GITHUB_WEBHOOK_SECRET, invalid signature is rejected with 401
        saved_env = settings.ENVIRONMENT
        settings.ENVIRONMENT = "production"
        try:
            response = await client.post("/api/webhooks/github", content=body, headers=headers)
            assert response.status_code == 401
        finally:
            settings.ENVIRONMENT = saved_env
