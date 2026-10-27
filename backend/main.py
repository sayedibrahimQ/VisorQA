"""
VisorQA Backend - FastAPI Application Entrypoint
Autonomous Visual QA & Self-Healing Frontend Agent
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from backend.config import settings
from backend.api.webhooks import router as webhooks_router
from backend.api.routes_ws import router as ws_router
from backend.db.repository import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server lifecycle events: setup DB tables and resource cleanups"""
    try:
        await init_db()
        print("✅ Database tables successfully verified/initialized.")
    except Exception as e:
        print(f"⚠️ Notice: Database initialization deferred or waiting on DB: {e}")
    yield


app = FastAPI(
    title="VisorQA API",
    description="Autonomous Visual QA & Self-Healing Frontend Agent API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware allowing Next.js frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Open for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Controller Routers
app.include_router(webhooks_router)
app.include_router(ws_router)

# Mount root WebSocket endpoint for Jira requirement /ws/mission-control
from backend.api.routes_ws import mission_control_ws_endpoint
app.add_api_websocket_route("/ws/mission-control", mission_control_ws_endpoint)


@app.get("/health", tags=["System"])
async def health_check():
    """System health check endpoint"""
    return {
        "status": "healthy",
        "service": "VisorQA Backend",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
        "math_thresholds": {
            "v_r_occlusion": settings.V_R_THRESHOLD,
            "iou_collision": settings.IOU_THRESHOLD,
            "max_attempts": settings.MAX_ATTEMPTS
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=(settings.ENVIRONMENT == "development")
    )
