"""
VisorQA Core Domain & Use-Case Layer
"""

from .state import AgentState, FSMStep, RunStatus, Anomaly, SelfHealingAttempt, DefectType, RepairSpec, TriageResponse, TriageCandidate
from .vision_math import (
    BleedResult,
    CollisionResult,
    ElementMaskInput,
    ViewportEvaluation,
    ViewportHealth,
    VisibilityResult,
    calculate_visibility_ratio,
    calculate_iou,
    detect_bleed_overflow,
    evaluate_bleed,
    evaluate_iou_pair,
    evaluate_viewport,
    evaluate_visibility,
    compute_viewport_health,
    rasterize_box,
    sibling_pairs_from_hierarchy,
)
from .orchestrator import VisorOrchestrator, run_visor_agent

__all__ = [
    "AgentState",
    "RepairSpec",
    "TriageResponse",
    "TriageCandidate",
    "FSMStep",
    "RunStatus",
    "Anomaly",
    "SelfHealingAttempt",
    "DefectType",
    "calculate_visibility_ratio",
    "calculate_iou",
    "detect_bleed_overflow",
    "evaluate_visibility",
    "evaluate_iou_pair",
    "evaluate_bleed",
    "evaluate_viewport",
    "compute_viewport_health",
    "rasterize_box",
    "sibling_pairs_from_hierarchy",
    "VisibilityResult",
    "CollisionResult",
    "BleedResult",
    "ViewportHealth",
    "ViewportEvaluation",
    "ElementMaskInput",
    "VisorOrchestrator",
    "run_visor_agent",
]
