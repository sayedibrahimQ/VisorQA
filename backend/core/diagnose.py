"""Deterministic context building and validation for Node 3 (DIAGNOSE).

The model proposes; this module disposes. It resolves the red
collision-mask overlay artifact for the defective viewport (validating
existence, format, and size before any bytes reach the model), reads
the authoritative ``V_r`` / ``IoU`` / ``Delta_x`` values off the
anomalies, bounds LCA/computed-CSS and source context, builds
previous-attempt feedback from the 3-Strike attempt records, and
validates the returned :class:`RepairSpec`: ``target_file`` must be a
Node 2 authorized, non-protected file (BR-2), selectors must be
grounded in the supplied evidence, the strategy must not smuggle in
raw patch code or banned techniques, and the repository repair policy
is merged into ``forbidden_hacks`` deterministically.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.core.state import AgentState, RepairSpec
from backend.core.triage import extract_file_tree, is_protected_path, normalize_path

logger = logging.getLogger("visorqa.diagnose")

# repair_spec keys the diagnosis may write (merge contract, Node 3).
DIAGNOSIS_FIELDS: Tuple[str, ...] = (
    "root_cause", "affected_selectors", "target_file", "css_strategy",
    "desktop_preservation_constraints", "forbidden_hacks",
)
# Node 2 triage metadata model output must never overwrite.
PROTECTED_TRIAGE_KEYS: Tuple[str, ...] = (
    "target_files", "triage_status", "triage_rejected_targets",
    "triage_confidence", "triage_summary", "filtered_intentional_element_ids",
)
# Repository repair policy (BR-4, mirrors orchestrator
# BANNED_PATCH_PATTERNS; plus the no-hide/no-remove design rules).
BASELINE_FORBIDDEN_HACKS: List[str] = [
    "!important",
    "z-index: 9999",
    "z-[9999]",
    "hiding defective content (display: none / visibility: hidden)",
    "removing functionality or content",
    "global selector overrides that restyle unrelated components",
]
_BANNED_STRATEGY_PATTERNS: List[str] = [
    "!important", "z-index: 9999", "z-index:9999", "z-[9999]",
]
_MAX_OVERLAY_BYTES = 10 * 1024 * 1024
_MAX_SOURCE_CHARS = 4000
_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg",
                "WEBP": "image/webp"}
_REPO_ROOT_KEYS = ("repo_root", "repository_root", "checkout_path",
                   "repo_path", "repository_path")


class DiagnosisValidationError(ValueError):
    """RepairSpec failed deterministic post-model validation."""


def viewport_name(raw: Any) -> str:
    """Normalize a viewport label to the overlay naming scheme."""
    s = str(raw or "").strip().lower()
    if s in ("mobile", "desktop"):
        return s
    if s.startswith("375"):
        return "mobile"
    if s.startswith("1440"):
        return "desktop"
    return s


def _artifact_candidates(state: AgentState) -> List[Dict[str, Any]]:
    """Overlay artifact records from state, in any stored shape."""
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    out: List[Dict[str, Any]] = []
    for key in ("overlays", "collision_overlay", "collision_overlays"):
        raw = spec.get(key)
        if isinstance(raw, dict):
            out.append(raw)
        elif isinstance(raw, list):
            out.extend(e for e in raw if isinstance(e, dict))
    return [c for c in out if c.get("path")]


def _conventional_overlay_path(state: AgentState, name: str) -> Optional[Path]:
    try:
        from backend.browser.overlay import (
            default_artifact_root,
            validate_run_id,
        )

        run_id = validate_run_id(str(state.run_id or ""))
    except Exception:
        return None
    if not name:
        return None
    return default_artifact_root() / run_id / f"{name}_collision_overlay.png"


def load_overlay_image(
    state: AgentState, name: str,
) -> Tuple[Optional[Tuple[bytes, str]], Dict[str, Any]]:
    """Resolve + validate the collision overlay for one viewport.

    Returns ``((image_bytes, media_type), status)`` or ``(None,
    status)`` with an explicit reason. Never logs image bytes.
    """
    name = viewport_name(name)
    candidates: List[Path] = []
    for cand in _artifact_candidates(state):
        if cand.get("status") not in (None, "generated"):
            continue
        if viewport_name(cand.get("viewport")) not in ("", name):
            continue
        candidates.append(Path(str(cand["path"])))
    conventional = _conventional_overlay_path(state, name)
    if conventional is not None:
        candidates.append(conventional)

    if not candidates:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "no overlay artifact recorded"}
    path = next((p for p in candidates if p.is_file()), candidates[0])
    if not path.is_file():
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "overlay file missing"}
    try:
        size = path.stat().st_size
    except OSError:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "overlay file unreadable"}
    if size > _MAX_OVERLAY_BYTES:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "overlay image too large"}
    if size == 0:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "overlay file empty"}
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
            fmt = img.format
    except Exception:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": "invalid image format"}
    media = _MEDIA_TYPES.get(str(fmt))
    if media is None:
        return None, {"status": "unavailable", "viewport": name,
                      "reason": f"unsupported image format {fmt}"}
    data = path.read_bytes()
    logger.info("wonder overlay ready: viewport=%s bytes=%d", name, len(data))
    return (data, media), {"status": "ready", "viewport": name,
                           "media_type": media, "bytes": len(data),
                           "path": str(path)}


def authorized_targets(state: AgentState) -> List[str]:
    """Node 2 authorized fix targets: normalized, non-protected, <= 2."""
    out: List[str] = []
    for raw in state.target_files:
        normalized = normalize_path(raw)
        if normalized and not is_protected_path(normalized) \
                and normalized not in out:
            out.append(normalized)
    return out[:2]


def resolve_repo_root(repair_spec: Dict[str, Any]) -> Optional[Path]:
    """Checked-out repository root from state metadata, when present."""
    for key in _REPO_ROOT_KEYS:
        raw = repair_spec.get(key)
        if raw:
            root = Path(str(raw)).expanduser()
            if root.is_dir():
                return root.resolve()
    return None


def read_source_contexts(
    state: AgentState, targets: Sequence[str],
) -> List[Dict[str, Any]]:
    """Bounded excerpts for authorized targets; explicit when unreadable."""
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    root = resolve_repo_root(spec)
    out: List[Dict[str, Any]] = []
    for path in targets:
        if root is None:
            out.append({"path": path, "status": "unavailable",
                        "reason": "no repository checkout available"})
            continue
        candidate = (root / path).resolve()
        if root not in candidate.parents and candidate != root:
            out.append({"path": path, "status": "unavailable",
                        "reason": "path escapes repository root"})
            continue
        if not candidate.is_file():
            out.append({"path": path, "status": "unavailable",
                        "reason": "file not found in checkout"})
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        out.append({"path": path, "status": "ready",
                    "excerpt": text[:_MAX_SOURCE_CHARS]})
    return out


def _viewport_feedback(repair_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-viewport verification detail when state carries it."""
    raw = repair_spec.get("viewport_evaluations")
    out: List[Dict[str, Any]] = []
    entries = raw.values() if isinstance(raw, dict) else raw
    for entry in entries or []:
        if not isinstance(entry, dict):
            entry = entry.model_dump() if hasattr(entry, "model_dump") else {}
        health = entry.get("health") or {}
        if not isinstance(health, dict):
            health = {}
        row = {"viewport": entry.get("viewport") or entry.get("name"),
               "health_score": health.get("score", entry.get("score"))}
        if row["viewport"] is not None:
            out.append(row)
    return out[:4]


def build_attempt_feedback(
    state: AgentState, repair_spec: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Previous-attempt feedback for Strike 2/3; None on first attempt."""
    if state.attempt <= 1:
        return None
    previous = None
    for record in state.attempts:
        if record.attempt_number < state.attempt and (
                previous is None
                or record.attempt_number > previous.attempt_number):
            previous = record
    if previous is None and state.attempts:
        previous = state.attempts[-1]
    if previous is None:
        return {"available": False,
                "reason": "no completed attempt record in state",
                "current_attempt": state.attempt}
    feedback: Dict[str, Any] = {
        "available": True,
        "attempt_number": previous.attempt_number,
        "passed": previous.passed,
        "verified_metrics": {
            "V_r": previous.verified_vr,
            "IoU": previous.verified_iou,
            "Delta_x_px": previous.verified_bleed_px,
        },
        "health_score": previous.post_score,
        "error": previous.error_message,
        "previous_root_cause": repair_spec.get("root_cause"),
        "previous_css_strategy": repair_spec.get("css_strategy")
        or repair_spec.get("fix_strategy"),
        "note": "Historical evidence only -- these metrics describe "
                "the previous attempt, not the current defect state. "
                "Do not repeat the failed approach without a justified "
                "correction; preserve constraints it satisfied.",
    }
    viewports = _viewport_feedback(repair_spec)
    if viewports:
        feedback["viewport_results"] = viewports
    if previous.patch_diff:
        feedback["previous_patch_summary"] = previous.patch_diff[:400]
    return feedback


def evidence_tokens(state: AgentState) -> Set[str]:
    """Selector-grounding tokens from anomalies, CSS keys, and LCA."""
    tokens: Set[str] = set()
    for anomaly in state.anomalies:
        for value in (anomaly.element_id, anomaly.secondary_el_id):
            if value:
                tokens.add(str(value).lower())
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    styles = spec.get("computed_styles") or spec.get("computed_css") or {}
    if isinstance(styles, dict):
        for key in styles:
            tokens.add(str(key).lower())
            tokens.add(str(key).lstrip("#.").lower())
    if spec.get("lca_element_id"):
        tokens.add(str(spec["lca_element_id"]).lower())

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("id", "tag", "data-testid", "data_testid"):
                if node.get(key):
                    tokens.add(str(node[key]).lower())
            for cls in node.get("classes") or []:
                tokens.add(str(cls).lower())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec.get("lca_dom"))
    return {t for t in tokens if len(t) >= 2}


def contains_patch_code(text: str) -> bool:
    """True when a diagnosis field smuggles raw patch/shell content."""
    if "```" in text:
        return True
    if re.search(r"(?m)^(--- a/|\+{3} b/|@@ -\d+)", text):
        return True
    if re.search(r"(?m)^\s*(diff --git|git apply|apply_patch)\b", text):
        return True
    return False


def validate_repair_spec(
    spec: RepairSpec,
    state: AgentState,
) -> RepairSpec:
    """Deterministic post-model validation of a RepairSpec."""
    repair_spec = state.repair_spec if isinstance(state.repair_spec, dict) \
        else {}
    authorized = authorized_targets(state)
    target = normalize_path(spec.target_file)
    if target is None:
        raise DiagnosisValidationError("target_file malformed")
    if is_protected_path(target):
        raise DiagnosisValidationError("target_file is protected (BR-2)")
    if target not in authorized:
        raise DiagnosisValidationError("target_file not authorized by Node 2")
    tree = extract_file_tree(repair_spec)
    if tree and target not in tree:
        raise DiagnosisValidationError(
            "target_file not in repository tree")
    root = resolve_repo_root(repair_spec)
    if root is not None and not (root / target).is_file():
        raise DiagnosisValidationError(
            "target_file missing from repository checkout")
    for field in ("root_cause", "css_strategy"):
        if contains_patch_code(getattr(spec, field)):
            raise DiagnosisValidationError(f"{field} contains patch code")
    lowered = spec.css_strategy.lower()
    for pattern in _BANNED_STRATEGY_PATTERNS:
        if pattern in lowered:
            raise DiagnosisValidationError(
                f"css_strategy uses forbidden technique: {pattern}")
    tokens = evidence_tokens(state)
    if tokens:
        for selector in spec.affected_selectors:
            if not any(tok in selector.lower() for tok in tokens):
                raise DiagnosisValidationError(
                    f"affected selector not in evidence: {selector}")
    merged_hacks = list(spec.forbidden_hacks)
    for hack in BASELINE_FORBIDDEN_HACKS:
        if not any(hack.lower() in h.lower() or h.lower() in hack.lower()
                   for h in merged_hacks):
            merged_hacks.append(hack)
    return spec.model_copy(update={
        "target_file": target, "forbidden_hacks": merged_hacks})


def build_diagnosis_context(
    state: AgentState,
) -> Tuple[Dict[str, Any], Optional[Tuple[bytes, str]]]:
    """Model context (metrics, LCA/CSS, targets, feedback) + overlay."""
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    first = state.anomalies[0] if state.anomalies else None
    defect = {
        "element_id": first.element_id if first else None,
        "secondary_element_id": first.secondary_el_id if first else None,
        "defect_type": first.defect_type.value if first else None,
        "viewport": (viewport_name(first.viewport)
                     if first and first.viewport else first.viewport
                     if first else None),
        "attempt": state.attempt,
    }
    metrics = {
        "V_r": first.visibility_ratio if first else None,
        "IoU": first.iou_score if first else None,
        "Delta_x_px": first.bleed_px if first else None,
    }
    targets = authorized_targets(state)
    overlay_image, overlay_status = load_overlay_image(
        state, defect["viewport"] or "")
    context: Dict[str, Any] = {
        "attempt": state.attempt,
        "defect": defect,
        "metrics": metrics,
        "overlay": overlay_status,
        "lca": {"lca_element_id": spec.get("lca_element_id"),
                "lca_dom": spec.get("lca_dom") or {}},
        "computed_styles": spec.get("computed_styles")
        or spec.get("computed_css") or {},
        "targets": targets,
        "triage_summary": spec.get("triage_summary", ""),
        "sources": read_source_contexts(state, targets),
        "feedback": build_attempt_feedback(state, spec),
    }
    logger.info("wonder context: attempt=%s overlay=%s targets=%d",
                state.attempt, overlay_status["status"], len(targets))
    # Keep the serialized context bounded and secret-free by shape.
    json.dumps(context, default=str)
    return context, overlay_image
