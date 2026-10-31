"""
VisorQA Backend Configuration & Mathematical Constants
"""

from typing import Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
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
    SPARK_TIMEOUT_SECONDS: float = Field(default=30.0)
    MUSE_WONDER_MODEL: str = Field(
        default="muse-wonder-1.0",
        description="Muse Wonder diagnosis model served by the Meta Model API",
    )
    WONDER_TIMEOUT_SECONDS: float = Field(default=30.0)
    # Muse Code is Meta's coding agent built on Muse Spark; on the
    # Model API the same Spark model serves the code-generation role.
    MUSE_CODE_MODEL: str = Field(
        default="muse-spark-1.3",
        description="Muse Code patch model served by the Meta Model API",
    )
    CODE_TIMEOUT_SECONDS: float = Field(default=30.0)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://visorqa:visorqa@localhost:5432/visorqa",
        description="SQLModel Database connection URL"
    )
    GITHUB_PAT: str = Field(default="", description="GitHub Personal Access Token")
    GITHUB_CLIENT_ID: str = Field(default="", description="GitHub OAuth App client id")
    GITHUB_CLIENT_SECRET: str = Field(default="", description="GitHub OAuth App client secret")
    GITHUB_WEBHOOK_SECRET: str = Field(default="", description="GitHub Webhook HMAC Secret")

    # GitHub App Integration (visorqa-bot[bot])
    GITHUB_APP_ID: str = Field(default="", description="GitHub App ID (General -> App ID)")
    GITHUB_INSTALLATION_ID: Optional[str] = Field(
        default=None,
        description="Default GitHub App Installation ID (Install App -> Gear icon -> ID in URL)",
    )
    GITHUB_PRIVATE_KEY_PATH: str = Field(
        default="",
        description="Path to GitHub App .pem private key file (e.g. backend/visorqa-bot.private-key.pem)",
    )
    GITHUB_PRIVATE_KEY: str = Field(
        default="",
        description="Inline PEM private key string (alternative to file path for cloud/Docker)",
    )
    GITHUB_BOT_USERNAME: str = Field(
        default="visorqa-bot[bot]",
        description="Expected bot username for verification and comment authorship",
    )

    @field_validator("GITHUB_INSTALLATION_ID", mode="before")
    @classmethod
    def _validate_installation_id(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        return str(v).strip()
    MODAL_TOKEN: str = Field(default="", description="Legacy single Modal token (deprecated; prefer ID/SECRET)")
    MODAL_TOKEN_ID: str = Field(default="", description="Modal API token ID (modal.com -> API Tokens)")
    MODAL_TOKEN_SECRET: str = Field(default="", description="Modal API token secret")
    MODAL_APP_NAME: str = Field(default="visorqa-sandbox")

    # Sandbox backend selection: "local" (default, no credentials) | "modal"
    # SANDBOX_PROVIDER is the canonical name (VISOR-ENV-001); SANDBOX_BACKEND
    # is kept as a backward-compatible alias. Factory resolution: an explicit
    # non-default value in either wins; both default to "local".
    SANDBOX_BACKEND: str = Field(default="local", description="Sandbox backend: local | modal | stub")
    # Canonical provider: "e2b" | "local" | "modal" | "stub". Empty means
    # auto: "e2b" when E2B_API_KEY is set, else "local".
    SANDBOX_PROVIDER: str = Field(default="", description="Sandbox provider: e2b | local | modal | stub (empty = auto)")
    E2B_API_KEY: str = Field(default="", description="E2B cloud sandbox API key")
    E2B_SANDBOX_TIMEOUT_SECONDS: int = Field(default=180, description="E2B sandbox lifetime bound")
    TARGET_APP_PATH: str = Field(default="./demo-target-app", description="Source target app directory")
    TARGET_APP_PORT: int = Field(default=3001, description="Preferred target app dev-server port")
    SANDBOX_LOCAL_ROOT: str = Field(default="", description="Local sandbox root (default: /tmp/visorqa_sandboxes)")
    SANDBOX_HMR_TIMEOUT_SECONDS: float = Field(default=15.0)
    SANDBOX_IDLE_TIMEOUT_SECONDS: float = Field(default=1800.0)
    SANDBOX_CPU_LIMIT: float = Field(default=0.0, description="0 = unset")
    SANDBOX_MEMORY_LIMIT_MB: int = Field(default=0, description="0 = unset")

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
    SEED_DEMO_RUNS: bool = Field(
        default=True,
        description="Seed canonical demo runs when no GitHub auth is configured (never in live mode)")


settings = Settings()
