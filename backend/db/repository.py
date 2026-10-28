"""
VisorQA Persistence Layer — Production Repository Pattern
Combines SQLModel Asyncio speed with PostgreSQL 16 EER CHECK constraints & GIN/Covering Indexes.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker
from sqlmodel import Column, Field, Relationship, SQLModel, create_engine, select

from backend.config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# 1. DOMAIN MODELS (EER Single-Table Inheritance + Strict DB Guardrails)
# =============================================================================

class RepositoryRecord(SQLModel, table=True):
    """Multi-tenant SaaS repository configuration & shared UI protection rules"""
    __tablename__ = "repositories"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    repo_full_name: str = Field(unique=True, index=True)  # e.g. "sayedibrahimQ/storefront"
    default_branch: str = Field(default="main")
    protected_globs: List[str] = Field(
        default=["src/components/ui/*"], sa_column=Column(JSONB, nullable=False)
    )
    modal_snapshot_id: Optional[str] = Field(default=None)
    commit_mode: str = Field(default="SUGGEST_REVIEW")    # AUTO_COMMIT | SUGGEST_REVIEW
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)

    runs: List["PRRun"] = Relationship(back_populates="repository")


class PRRun(SQLModel, table=True):
    """Master FSM state for each GitHub Webhook execution"""
    __tablename__ = "pr_runs"
    __table_args__ = (
        CheckConstraint("attempt >= 0 AND attempt <= 3", name="chk_pr_runs_3_strike_cap"),
        CheckConstraint("total_cost_usd <= 0.15", name="chk_pr_runs_cost_guardrail"),
        Index(
            "idx_pr_runs_dashboard_covering",
            "repo_full_name",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    repo_id: Optional[str] = Field(default=None, foreign_key="repositories.id", index=True)
    github_delivery_id: str = Field(default_factory=lambda: str(uuid4()), unique=True)
    repo_full_name: str = Field(index=True)
    pr_number: int = Field(index=True)
    branch: str = Field(default="main")
    commit_sha: str = Field(index=True)

    # FSM State & 3-Strike Telemetry
    status: str = Field(default="QUEUED", index=True)  # QUEUED, SENSE, TRIAGE, DIAGNOSE, PATCH, VERIFY, RESOLVED, FALLBACK, FAILED
    attempt: int = Field(default=0)                    # 0..3
    max_attempts: int = Field(default=3)
    target_files: List[str] = Field(default=[], sa_column=Column(JSONB, nullable=False))

    # Scoring & Output Artifacts
    initial_score: float = Field(default=0.0)
    best_score: float = Field(default=0.0)
    best_patch: Optional[str] = Field(default=None)
    is_resolved: bool = Field(default=False, index=True)
    healed_commit_sha: Optional[str] = Field(default=None)

    # Unit Economics & Latency
    total_latency_ms: int = Field(default=0)
    total_cost_usd: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    repository: Optional[RepositoryRecord] = Relationship(back_populates="runs")
    anomalies: List["AnomalyRecord"] = Relationship(
        back_populates="run", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    attempts: List["AttemptRecord"] = Relationship(
        back_populates="run", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class AnomalyRecord(SQLModel, table=True):
    """
    EER Specialized Visual Anomalies (OCCLUSION, COLLISION, BLEED)
    Enforces subtype mathematical equations via conditional PostgreSQL CHECK constraints.
    """
    __tablename__ = "visual_anomalies"
    __table_args__ = (
        CheckConstraint(
            "(defect_type = 'OCCLUSION' AND v_r IS NOT NULL AND v_r < 0.85) OR "
            "(defect_type = 'COLLISION' AND iou IS NOT NULL AND iou > 0.05) OR "
            "(defect_type = 'BLEED' AND bleed_px IS NOT NULL AND bleed_px > 2.0)",
            name="chk_anomaly_subtype_math_equations",
        ),
        CheckConstraint("viewport IN ('375px', '1440px')", name="chk_valid_viewport"),
        Index("idx_anomalies_lca_gin", "lca_dom", postgresql_using="gin"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="pr_runs.id", index=True)
    attempt_num: int = Field(default=0, index=True)
    viewport: str = Field(default="375px", index=True)    # "375px" | "1440px"
    visor_el_id: str = Field(index=True)                  # 1:1 DOM-to-SAM binding ID
    secondary_el_id: Optional[str] = Field(default=None)  # Populated on COLLISION or OCCLUSION
    defect_type: str = Field(index=True)                  # OCCLUSION | COLLISION | BLEED

    # The 3 Mathematical Discrepancy Metrics
    v_r: Optional[float] = Field(default=None)            # Area(M_SAM) / Area(B_DOM) < 0.85
    iou: Optional[float] = Field(default=None)            # Area(M_i cap M_j) / Area(M_i cup M_j) > 0.05
    bleed_px: Optional[float] = Field(default=None)       # max(0, X_max - W_vp) > 2.0

    # Spatial & Structural Context (Native JSONB)
    b_dom_box: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False))
    lca_dom: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False))
    mask_url: Optional[str] = Field(default=None)
    is_resolved: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)

    run: Optional[PRRun] = Relationship(back_populates="anomalies")


class AttemptRecord(SQLModel, table=True):
    """
    3-Strike Closed-Loop Audit Trail (Muse Wonder Spec -> Muse Code Diff -> Dual-VP Verify)
    Enforces BR-3 (Cross-Viewport Zero Regression) and BR-4 (Anti-Hack CSS).
    """
    __tablename__ = "repair_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_run_attempt_number"),
        CheckConstraint("attempt_number BETWEEN 1 AND 3", name="chk_attempt_range_1_to_3"),
        CheckConstraint(
            "unified_diff IS NULL OR ("
            "unified_diff NOT ILIKE '%!important%' AND "
            "unified_diff NOT ILIKE '%z-index: 9999%' AND "
            "unified_diff NOT ILIKE '%z-[9999]%'"
            ")",
            name="chk_br4_anti_hack_css_policy",
        ),
        Index("idx_attempts_repair_spec_gin", "repair_spec", postgresql_using="gin"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="pr_runs.id", index=True)
    attempt_number: int = Field(default=1)

    # Architect (Muse Wonder) & Coder (Muse Code) Artifacts
    repair_spec: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False))
    unified_diff: Optional[str] = Field(default=None)

    # Dual-Viewport Verification Telemetry (BR-3)
    mobile_v_r_min: float = Field(default=0.0)
    desktop_v_r_min: float = Field(default=1.0)
    verified_iou: float = Field(default=0.0)
    verified_bleed_px: float = Field(default=0.0)
    post_score: float = Field(default=0.0)
    hmr_latency_ms: int = Field(default=0)
    passed: bool = Field(default=False)
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

    run: Optional[PRRun] = Relationship(back_populates="attempts")


# =============================================================================
# 2. ASYNC ENGINE & SESSION LIFECYCLE
# =============================================================================

db_url = settings.DATABASE_URL
async_db_url = (
    db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgresql://")
    else db_url
)
sync_db_url = (
    db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if db_url.startswith("postgresql+asyncpg://")
    else db_url
)

async_engine = create_async_engine(
    async_db_url,
    echo=False,
    future=True,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
engine = create_engine(sync_db_url, echo=False)


async def init_db() -> None:
    """Creates tables, constraints, and partial indexes automatically on startup."""
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        if "postgresql" in async_db_url:
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_pr_runs_active_queue "
                    "ON pr_runs (created_at ASC) "
                    "WHERE status NOT IN ('RESOLVED', 'FALLBACK', 'FAILED');"
                )
            )


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# =============================================================================
# 3. REPOSITORY PATTERN IMPLEMENTATION (100% Backward-Compatible + FSM Sync)
# =============================================================================

class RunRepository:
    """Decoupled persistence adapter for FastAPI endpoints and the FSM Orchestrator"""

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session

    async def create_run(
        self,
        pr_number: int,
        repo_name: str,
        branch: str = "main",
        commit_sha: str = "HEAD",
        github_delivery_id: Optional[str] = None,
        repo_id: Optional[str] = None,
    ) -> PRRun:
        run = PRRun(
            repo_id=repo_id,
            pr_number=pr_number,
            repo_full_name=repo_name,
            branch=branch,
            commit_sha=commit_sha,
            github_delivery_id=github_delivery_id or str(uuid4()),
            status="QUEUED",
            attempt=0,
        )
        if self.session:
            self.session.add(run)
            await self.session.commit()
            await self.session.refresh(run)
        return run

    async def get_run_by_id(self, run_id: str) -> Optional[PRRun]:
        """Eager-loads anomalies and attempts via selectinload to prevent MissingGreenlet crashes"""
        if not self.session:
            return None
        stmt = (
            select(PRRun)
            .where(PRRun.id == run_id)
            .options(selectinload(PRRun.anomalies), selectinload(PRRun.attempts))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_run_by_delivery_id(self, delivery_id: str) -> Optional[PRRun]:
        """Looks up a PRRun by its unique github_delivery_id for idempotency checks."""
        if not self.session:
            return None
        stmt = (
            select(PRRun)
            .where(PRRun.github_delivery_id == delivery_id)
            .options(selectinload(PRRun.anomalies), selectinload(PRRun.attempts))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_runs(self, limit: int = 20, status: Optional[str] = None) -> List[PRRun]:
        if not self.session:
            return []
        stmt = (
            select(PRRun)
            .options(selectinload(PRRun.anomalies), selectinload(PRRun.attempts))
            .order_by(PRRun.created_at.desc())
            .limit(limit)
        )
        if status and status.upper() != "ALL":
            stmt = stmt.where(PRRun.status == status.upper())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sync_agent_state(self, state: Any) -> Optional[PRRun]:
        """Atomically persists Pydantic AgentState at every FSM transition"""
        run = await self.get_run_by_id(state.run_id)
        if run and self.session:
            run.status = state.status
            run.attempt = state.attempt
            run.target_files = state.target_files
            run.best_score = state.best_score
            run.best_patch = state.best_patch
            run.is_resolved = state.is_resolved
            run.updated_at = utc_now()
            self.session.add(run)
            await self.session.commit()
            await self.session.refresh(run)
        return run

    async def add_anomaly(
        self,
        run_id: str,
        visor_el_id: str,
        defect_type: str,
        viewport: str = "375px",
        attempt_num: int = 0,
        v_r: Optional[float] = None,
        iou: Optional[float] = None,
        bleed_px: Optional[float] = None,
        b_dom_box: Optional[Dict[str, Any]] = None,
        lca_dom: Optional[Dict[str, Any]] = None,
        mask_url: Optional[str] = None,
        secondary_el_id: Optional[str] = None,
    ) -> AnomalyRecord:
        anomaly = AnomalyRecord(
            run_id=run_id,
            attempt_num=attempt_num,
            viewport=viewport,
            visor_el_id=visor_el_id,
            secondary_el_id=secondary_el_id,
            defect_type=defect_type,
            v_r=v_r,
            iou=iou,
            bleed_px=bleed_px,
            b_dom_box=b_dom_box or {},
            lca_dom=lca_dom or {},
            mask_url=mask_url,
        )
        if self.session:
            self.session.add(anomaly)
            await self.session.commit()
            await self.session.refresh(anomaly)
        return anomaly

    async def record_attempt(
        self,
        run_id: str,
        attempt_number: int,
        repair_spec: Dict[str, Any],
        unified_diff: Optional[str],
        mobile_v_r_min: float,
        desktop_v_r_min: float,
        verified_iou: float,
        post_score: float,
        hmr_latency_ms: int,
        passed: bool,
        error_message: Optional[str] = None,
    ) -> AttemptRecord:
        attempt = AttemptRecord(
            run_id=run_id,
            attempt_number=attempt_number,
            repair_spec=repair_spec,
            unified_diff=unified_diff,
            mobile_v_r_min=mobile_v_r_min,
            desktop_v_r_min=desktop_v_r_min,
            verified_iou=verified_iou,
            post_score=post_score,
            hmr_latency_ms=hmr_latency_ms,
            passed=passed,
            error_message=error_message,
        )
        if self.session:
            self.session.add(attempt)
            await self.session.commit()
            await self.session.refresh(attempt)
        return attempt
