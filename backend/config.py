"""
VisorQA Backend Configuration & Mathematical Constants
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core AI & Service Credentials
    META_API_KEY: str = Field(default="", description="Meta Model API key for SAM & Muse models")
    META_BASE_URL: str = Field(
        default="https://api.meta.ai/v1",
        description="Meta Model API base URL (AsyncOpenAI base_url)",
    )
    # SAM 3.1 transport (endpoint path is NOT published in project docs;
    # leave empty until the real contract is configured - never guessed)
    SAM31_ENDPOINT_PATH: str = Field(default="")
    SAM31_MAX_BATCH_SIZE: int = Field(default=40)
    SAM31_TIMEOUT_SECONDS: float = Field(default=10.0)
    MUSE_SPARK_MODEL: str = Field(
        default="muse-spark-1.3",
        description="Muse Spark triage model served by the Meta Model API",
    )
    SPARK_TIMEOUT_SECONDS: float = Field(default=15.0)
    MUSE_WONDER_MODEL: str = Field(
        default="muse-wonder-1.0",
        description="Muse Wonder diagnosis model served by the Meta Model API",
    )
    WONDER_TIMEOUT_SECONDS: float = Field(default=30.0)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://visorqa:visorqa@localhost:5432/visorqa",
        description="SQLModel Database connection URL"
    )
    GITHUB_PAT: str = Field(default="", description="GitHub Personal Access Token")
    GITHUB_WEBHOOK_SECRET: str = Field(default="", description="GitHub Webhook HMAC Secret")
    MODAL_TOKEN: str = Field(default="", description="Modal Token for sandbox runners")

    # Server Settings
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="info")
    FRONTEND_URL: str = Field(default="http://localhost:3000")

    # Mathematical Constants & QA Thresholds
    V_R_THRESHOLD: float = Field(
        default=0.85,
        description="Occlusion Threshold: Area(M_SAM) / Area(B_DOM) < 0.85 triggers occlusion defect"
    )
    IOU_THRESHOLD: float = Field(
        default=0.05,
        description="Collision Threshold: IoU(M_i, M_j) > 0.05 triggers layout collision defect"
    )
    MAX_ATTEMPTS: int = Field(
        default=3,
        description="3-Strike Self-Healing Loop limit"
    )

    # Browser Renderer (SENSE node)
    BROWSER_NAV_TIMEOUT_MS: int = Field(default=30000)
    BROWSER_ALLOWED_SCHEMES: str = Field(default="http,https")
    BROWSER_ARTIFACTS_DIR: str = Field(default="artifacts")
    STATIC_ARTIFACTS_DIR: str = Field(default="static/artifacts")


settings = Settings()
