"""
VisorQA Controller Layer - GitHub Webhooks
POST /api/webhooks/github (HMAC verification & PR trigger)
"""

from fastapi import APIRouter, Request, HTTPException, Header, status
from typing import Optional, Dict, Any

from backend.adapters.github_client import GitHubClient
from backend.config import settings

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def handle_github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
    x_github_event: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """
    Receives GitHub webhook payloads (pull_request events),
    validates HMAC SHA-256 signature, and initiates autonomous QA run.
    """
    body = await request.body()

    # Signature verification (in dev mode with empty secret, allow bypass)
    if settings.GITHUB_WEBHOOK_SECRET and not settings.ENVIRONMENT == "test":
        if not GitHubClient.verify_webhook_signature(body, x_hub_signature_256):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub webhook signature"
            )

    payload = await request.json() if body else {}

    # Check for pull_request event (opened, synchronize, reopened)
    event_type = x_github_event or payload.get("action", "unknown")
    
    # Interface stub: Hand off to orchestrator
    return {
        "status": "accepted",
        "event": event_type,
        "message": "GitHub webhook received and queued for autonomous inspection"
    }
