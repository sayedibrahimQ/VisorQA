"""
VisorQA Core State - (State Pattern)
AgentState Pydantic Model + Domain Schemas

Canonical Jira contract:
    AgentState(pr_url, repo_full_name, pr_number, branch, commit_sha,
               attempt=0, max_attempts=3, anomalies=[], target_files=[],
               repair_spec={}, current_patch='', best_score=0.0,
               best_patch='', is_resolved=False)

Legacy construction used by the existing dashboard / repository layer
(``run_id=...``, ``repo_name=...``, ``status``, ``current_step``,
``strike_count``, ``attempts``) is kept working: ``repo_name`` and
``repo_full_name`` are synchronised, ``run_id`` auto-generates, and
``strike_count`` mirrors ``attempt``.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FSMStep(str, Enum):
    """5-Step Autonomous Visual QA Lifecycle"""

    SENSE = "1.SENSE"  # DOM geometry extraction & SAM 3.1 segmentation
    TRIAGE = "2.TRIAGE"  # Muse Spark LCA DOM hierarchy mapping
    DIAGNOSE = "3.DIAGNOSE"  # Muse Wonder multi-modal visual reasoning
    PATCH = "4.PATCH"  # Muse Code HMR patch generation
    VERIFY = "5.VERIFY"  # 3-Strike verification re-run


class RunStatus(str, Enum):
    """PR Visual QA Run Lifecycle Statuses"""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RESOLVED = "RESOLVED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class DefectType(str, Enum):
    """Visual Discrepancy Defect Categories"""

    OCCLUSION = "OCCLUSION"  # V_r < 0.85
    COLLISION = "COLLISION"  # IoU > 0.05
    VIEWPORT_OVERFLOW = "VIEWPORT_OVERFLOW"  # Bleed outside viewport bounds
    BLEED = "BLEED"  # DB / SRS spelling of viewport overflow


class DOMBoundingBox(BaseModel):
    """Expected DOM Bounding Box (B_DOM)"""

    model_config = ConfigDict(extra="allow")

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


class Anomaly(BaseModel):
    """Visual defect detected during SENSE phase.

    Accepts both the dashboard spelling (``element_id``,
    ``visibility_ratio``, ``iou_score``) and the SRS/DB spelling
    (``visor_el_id``, ``v_r``, ``iou``, ``bleed_px``, ``b_dom_box``).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    element_id: str = Field(
        default="",
        validation_alias=AliasChoices("element_id", "visor_el_id", "visor-el-id"),
        serialization_alias="element_id",
    )
    defect_type: DefectType = DefectType.OCCLUSION
    bounding_box: Optional[DOMBoundingBox] = Field(
        default=None,
        validation_alias=AliasChoices("bounding_box", "b_dom_box", "b_dom"),
        serialization_alias="bounding_box",
    )
    visibility_ratio: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("visibility_ratio", "v_r", "vr"),
        serialization_alias="visibility_ratio",
    )
    iou_score: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("iou_score", "iou"),
        serialization_alias="iou_score",
    )
    bleed_px: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("bleed_px", "bleed", "delta_x"),
        serialization_alias="bleed_px",
    )
    viewport: Optional[str] = None
    secondary_el_id: Optional[str] = None
    sam_mask_path: Optional[str] = None
    status: str = "DETECTED"

    @field_validator("defect_type", mode="before")
    @classmethod
    def _normalise_defect_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            upper = value.strip().upper()
            if upper in {"BLEED", "VIEWPORT_BLEED", "OVERFLOW"}:
                return DefectType.VIEWPORT_OVERFLOW
            if upper in DefectType.__members__:
                return DefectType[upper]
            # Unknown strings fall back to occlusion rather than crashing
            # the FSM on an upstream payload variation.
            return DefectType.OCCLUSION
        return value

    # -- SRS/DB spelling accessors -------------------------------------
    @property
    def visor_el_id(self) -> str:
        return self.element_id

    @property
    def v_r(self) -> Optional[float]:
        return self.visibility_ratio

    @property
    def iou(self) -> Optional[float]:
        return self.iou_score


class TriageCandidate(BaseModel):
    """One evidence-backed source-file candidate from Muse Spark."""

    path: str
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: str = ""
    kind: str = "direct"  # direct | parent_layout | consumer | sibling


class RejectedTarget(BaseModel):
    path: str = ""
    reason: str  # protected_shared_ui | not_in_repository_tree |
    # malformed_path | path_traversal | low_confidence |
    # insufficient_evidence | intentional_overlap_filtered


class TriageResponse(BaseModel):
    """Muse Spark source-localization contract (Node 2 TRIAGE).

    Consumed by ``triage_files_muse_spark`` (which enforces BR-2 and
    copies ``target_files`` onto ``AgentState``) and by DIAGNOSE via
    ``repair_spec`` (``lca_element_id`` / ``lca_dom`` / ``triage_summary``).
    ``status="unresolved"`` is the supported low-confidence outcome: it
    must carry no direct fix targets rather than an invented file.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    target_files: List[str] = Field(default_factory=list, max_length=2)
    candidates: List[TriageCandidate] = Field(default_factory=list)
    candidate_source_file: Optional[str] = None  # legacy single-file field
    lca_element_id: Optional[str] = None
    lca_dom: Dict[str, Any] = Field(default_factory=dict)
    triage_summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = "unresolved"  # resolved | unresolved |
    # no_actionable_defects | error
    evidence: List[str] = Field(default_factory=list)
    filtered_intentional_element_ids: List[str] = Field(default_factory=list)
    rejected_targets: List[RejectedTarget] = Field(default_factory=list)


class RepairSpec(BaseModel):
    """Muse Wonder diagnosis contract (Node 3 DIAGNOSE).

    A declarative repair specification, never a code patch: Node 4
    (PATCH) turns this into a diff. Consumed by ``diagnose_muse_wonder``
    (which validates target authorization and merges only these fields
    into ``AgentState.repair_spec``, preserving Node 2 triage metadata)
    and by PATCH via ``repair_spec`` (``target_file`` / ``css_strategy``).
    Strict-clean for Meta structured output: no extra properties, no
    free-form dicts, no recursion.
    """

    model_config = ConfigDict(extra="forbid")

    root_cause: str = Field(min_length=1)
    affected_selectors: List[str] = Field(min_length=1)
    target_file: str = Field(min_length=1)
    css_strategy: str = Field(min_length=1)
    desktop_preservation_constraints: List[str] = Field(min_length=1)
    forbidden_hacks: List[str] = Field(min_length=1)


class SelfHealingAttempt(BaseModel):
    """Single cycle within the 3-Strike Self-Healing Loop"""

    attempt_number: int
    patch_diff: Optional[str] = None
    verified_vr: Optional[float] = None
    verified_iou: Optional[float] = None
    verified_bleed_px: Optional[float] = None
    post_score: Optional[float] = None
    passed: bool = False
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utc_now)


class AgentState(BaseModel):
    """
    (State Pattern) Encapsulates the entire state of an autonomous
    Visual QA run. Passed between orchestrator nodes and emitted
    across WebSockets. Mutated in place by the deterministic FSM.
    """

    model_config = ConfigDict(extra="allow", validate_assignment=True)

    # --- Identity (Jira contract) ------------------------------------
    pr_url: str = ""
    repo_full_name: str = ""
    pr_number: int = 0
    branch: str = "main"
    commit_sha: str = ""

    # --- 3-Strike loop (Jira contract) -------------------------------
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)

    # --- FSM payload (Jira contract) ---------------------------------
    anomalies: List[Anomaly] = Field(default_factory=list)
    target_files: List[str] = Field(default_factory=list)
    repair_spec: Dict[str, Any] = Field(default_factory=dict)
    current_patch: str = ""
    best_score: float = 0.0
    best_patch: str = ""
    is_resolved: bool = False

    # --- Legacy / dashboard compatibility ----------------------------
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    repo_name: str = ""
    status: RunStatus = RunStatus.PENDING
    current_step: FSMStep = FSMStep.SENSE
    strike_count: int = Field(default=0, ge=0)
    attempts: List[SelfHealingAttempt] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("anomalies", mode="before")
    @classmethod
    def _coerce_anomalies(cls, value: Any) -> Any:
        """Accept Anomaly objects, dicts, or plain element-id strings."""
        if not value:
            return []
        coerced: List[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append(
                    {"id": str(uuid4()), "element_id": item,
                     "defect_type": DefectType.OCCLUSION}
                )
            else:
                coerced.append(item)
        return coerced

    @model_validator(mode="after")
    def _sync_legacy_fields(self) -> "AgentState":
        # repo_name <-> repo_full_name
        if not self.repo_full_name and self.repo_name:
            object.__setattr__(self, "repo_full_name", self.repo_name)
        if not self.repo_name and self.repo_full_name:
            object.__setattr__(self, "repo_name", self.repo_full_name)
        # Derive the canonical PR URL when only repo + number are known.
        if not self.pr_url and self.repo_full_name and self.pr_number:
            object.__setattr__(
                self, "pr_url",
                f"https://github.com/{self.repo_full_name}/pull/{self.pr_number}",
            )
        # attempt <-> strike_count (attempt is the canonical counter).
        if self.attempt != self.strike_count:
            synced = max(self.attempt, self.strike_count)
            object.__setattr__(self, "attempt", synced)
            object.__setattr__(self, "strike_count", synced)
        if self.status == RunStatus.RESOLVED and not self.is_resolved:
            object.__setattr__(self, "is_resolved", True)
        return self

    # -- FSM helpers ----------------------------------------------------
    def transition_to(
        self, next_step: FSMStep, status: Optional[RunStatus] = None
    ) -> None:
        """Advance agent FSM step"""
        self.current_step = next_step
        if status is not None:
            self.status = status
            if status == RunStatus.RESOLVED:
                self.is_resolved = True
        self.updated_at = _utc_now()

    def record_strike(self, attempt: SelfHealingAttempt) -> None:
        """Record a self-healing attempt and increment strike count"""
        self.attempts.append(attempt)
        self.attempt = max(self.attempt, attempt.attempt_number)
        self.strike_count = self.attempt
        self.updated_at = _utc_now()

    def update_best(self, score: float) -> bool:
        """Snapshot ``current_patch`` when ``score`` beats ``best_score``."""
        if score > self.best_score:
            self.best_score = round(float(score), 4)
            self.best_patch = self.current_patch
            self.updated_at = _utc_now()
            return True
        return False
