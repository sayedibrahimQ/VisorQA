"""
VisorQA Core State - (State Pattern)
AgentState Pydantic Model + Domain Schemas
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class FSMStep(str, Enum):
    """5-Step Autonomous Visual QA Lifecycle"""
    SENSE = "1.SENSE"         # DOM geometry extraction & SAM 3.1 segmentation
    TRIAGE = "2.TRIAGE"       # Muse Spark LCA DOM hierarchy mapping
    DIAGNOSE = "3.DIAGNOSE"   # Muse Wonder multi-modal visual reasoning
    PATCH = "4.PATCH"         # Muse Code HMR patch generation
    VERIFY = "5.VERIFY"       # 3-Strike verification re-run


class RunStatus(str, Enum):
    """PR Visual QA Run Lifecycle Statuses"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class DefectType(str, Enum):
    """Visual Discrepancy Defect Categories"""
    OCCLUSION = "OCCLUSION"                   # V_r < 0.85
    COLLISION = "COLLISION"                   # IoU > 0.05
    VIEWPORT_OVERFLOW = "VIEWPORT_OVERFLOW"   # Bleed outside viewport bounds


class DOMBoundingBox(BaseModel):
    """Expected DOM Bounding Box (B_DOM)"""
    x: float
    y: float
    width: float
    height: float


class Anomaly(BaseModel):
    """Visual defect detected during SENSE phase"""
    id: str
    element_id: str
    defect_type: DefectType
    bounding_box: Optional[DOMBoundingBox] = None
    visibility_ratio: Optional[float] = None
    iou_score: Optional[float] = None
    sam_mask_path: Optional[str] = None
    status: str = "DETECTED"


class SelfHealingAttempt(BaseModel):
    """Single cycle within the 3-Strike Self-Healing Loop"""
    attempt_number: int
    patch_diff: Optional[str] = None
    verified_vr: Optional[float] = None
    verified_iou: Optional[float] = None
    passed: bool = False
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentState(BaseModel):
    """
    (State Pattern) Encapsulates the entire state of an autonomous Visual QA run.
    Passed between orchestrator nodes and emitted across WebSockets.
    """
    run_id: str
    pr_number: int
    repo_name: str
    branch: str = "main"
    commit_sha: str
    status: RunStatus = RunStatus.PENDING
    current_step: FSMStep = FSMStep.SENSE
    strike_count: int = 0
    anomalies: List[Anomaly] = Field(default_factory=list)
    attempts: List[SelfHealingAttempt] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, next_step: FSMStep, status: Optional[RunStatus] = None) -> None:
        """Advance agent FSM step"""
        self.current_step = next_step
        if status:
            self.status = status
        self.updated_at = datetime.now(timezone.utc)

    def record_strike(self, attempt: SelfHealingAttempt) -> None:
        """Record a self-healing attempt and increment strike count"""
        self.attempts.append(attempt)
        self.strike_count = len(self.attempts)
        self.updated_at = datetime.now(timezone.utc)
