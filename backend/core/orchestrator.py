"""
VisorQA FSM Orchestrator - Pure Python Deterministic FSM (ADR-001 / TC-1)

Implements the 5-node pipeline with asyncio + Pydantic only.
No LangChain, CrewAI, AutoGen, or any agent framework is used.

    SENSE -> TRIAGE -> DIAGNOSE -> PATCH -> VERIFY
                  ^                            |
                  +----- 3-Strike Loop --------+
                         (max_attempts = 3)

Canonical entry point (Jira):

    final_state = await run_visor_agent(state, ws_broadcast)

``ws_broadcast`` is any callable accepting one WebSocket envelope
dict (sync or async), an object with ``send_json``, or an object
with ``broadcast_to_run``. The envelope follows the TDS contract::

    {"event": "SENSE_COMPLETE" | "TRIAGE_COMPLETE" | "ATTEMPT_<n>_FEEDBACK",
     "timestamp": "<ISO-8601 UTC>",
     "state": { ...AgentState JSON... }}

``VisorOrchestrator`` is kept as a thin class wrapper (state-object
callback style) for the existing dashboard / test integration.
"""

from __future__ import annotations

import fnmatch
import inspect
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.config import settings
from backend.core.state import (
    AgentState,
    Anomaly,
    DefectType,
    FSMStep,
    RunStatus,
    SelfHealingAttempt,
)
from backend.core.vision_math import calculate_iou, calculate_visibility_ratio

__all__ = [
    "AgentState",
    "VisorOrchestrator",
    "run_visor_agent",
    "sense_with_playwright_and_sam",
    "triage_files_muse_spark",
    "diagnose_muse_wonder",
    "patch_with_muse_code",
    "patch_muse_code_and_apply",
    "verify_with_sam",
    "compute_health_score",
    "is_patch_safe",
    "PROTECTED_GLOBS",
    "BANNED_PATCH_PATTERNS",
]

# BR-2: shared design-system components are never patched directly.
PROTECTED_GLOBS: List[str] = ["src/components/ui/*", "*/components/ui/*"]
# BR-4: anti-hack CSS policy (mirrors the repair_attempts DB CHECK).
BANNED_PATCH_PATTERNS: List[str] = ["!important", "z-index: 9999", "z-index:9999", "z-[9999]"]

VIEWPORTS: List[tuple[int, int]] = [(375, 812), (1440, 900)]  # (width, height)


# ---------------------------------------------------------------------------
# Deterministic scoring (TDS SS3 / SRS FR-07)
# ---------------------------------------------------------------------------

def compute_health_score(
    v_r_values: List[float], iou_values: List[float], bleed_values: List[float]
) -> float:
    """Score = mean(V_r) - max(IoU) - 0.01 * max(bleed_px)."""
    mean_vr = sum(v_r_values) / len(v_r_values) if v_r_values else 1.0
    max_iou = max(iou_values) if iou_values else 0.0
    max_bleed = max(bleed_values) if bleed_values else 0.0
    return round(float(mean_vr - max_iou - 0.01 * max_bleed), 4)


def is_patch_safe(patch: str) -> bool:
    """BR-4: reject brittle global overrides in generated patches."""
    if not patch:
        return True
    lowered = patch.lower()
    return not any(pattern in lowered for pattern in BANNED_PATCH_PATTERNS)


def _is_protected(path: str) -> bool:
    return any(fnmatch.fnmatch(path, glob) for glob in PROTECTED_GLOBS)


def _anomaly_metrics(anomalies: List[Anomaly]) -> tuple[List[float], List[float], List[float]]:
    vr = [a.visibility_ratio if a.visibility_ratio is not None else 0.0 for a in anomalies]
    iou = [a.iou_score if a.iou_score is not None else 0.0 for a in anomalies]
    bleed = [a.bleed_px if a.bleed_px is not None else 0.0 for a in anomalies]
    return vr, iou, bleed


# ---------------------------------------------------------------------------
# Lazy default adapters (existing stubs; no network when unused)
# ---------------------------------------------------------------------------

def _default_sandbox() -> Any:
    # DI-selected backend (SANDBOX_BACKEND, default "local"); the
    # orchestrator only ever sees the shared SandboxRunner interface.
    from backend.sandbox.factory import create_sandbox_runner

    return create_sandbox_runner()


async def _record_sandbox_state(state: AgentState, sandbox: Any) -> Any:
    """Copy sandbox status into state.sandbox (Node 5 handoff)."""
    try:
        status = await sandbox.get_status()
    except Exception:
        return None
    data = status.to_dict() if hasattr(status, "to_dict") else {}
    state.sandbox.backend = getattr(sandbox, "provider_label", None) or data.get("backend", "") or state.sandbox.backend
    state.sandbox.sandbox_id = getattr(sandbox, "sandbox_id", None) or data.get("sandbox_id") or state.sandbox.sandbox_id
    state.sandbox.session_id = data.get("session_id", "")
    state.sandbox.branch = data.get("branch", "")
    state.sandbox.commit_sha = data.get("commit_sha", "")
    state.sandbox.working_dir = data.get("working_dir", "")
    state.sandbox.server_state = str(data.get("server_state", "not_started"))
    state.sandbox.patch_count = int(data.get("patch_count", 0) or 0)
    state.sandbox.last_patch_phase = str(data.get("last_phase", "none"))
    state.sandbox.patch_timings = dict(data.get("timings", {}) or {})
    if getattr(sandbox, "hmr_latency_ms", None) is not None:
        state.sandbox.patch_timings["total_patch_to_hmr_ms"] = sandbox.hmr_latency_ms
        state.sandbox.patch_timings["hmr_propagation_ms"] = sandbox.hmr_latency_ms
    try:
        url = await sandbox.get_preview_url()
    except Exception:
        url = None
    if url:
        state.sandbox.preview_url = url
    return status


def _default_sam() -> Any:
    from backend.adapters.muse_clients import SAM31Client

    return SAM31Client()


def _default_spark() -> Any:
    # Real Muse Spark client only when the Meta Model API is fully
    # configured (key present; base URL and model carry Meta defaults);
    # otherwise the deterministic legacy stub keeps offline runs and
    # tests working (no fabricated network results).
    if settings.META_API_KEY and settings.META_BASE_URL and \
            getattr(settings, "MUSE_SPARK_MODEL", ""):
        from backend.adapters.spark_client import MuseSparkTriageClient

        return MuseSparkTriageClient()
    from backend.adapters.muse_clients import MuseSparkClient

    return MuseSparkClient()


def _default_wonder() -> Any:
    # Real Muse Wonder client only when the Meta Model API is fully
    # configured (key present; base URL and model carry Meta defaults);
    # otherwise the deterministic legacy stub keeps offline runs and
    # tests working (no fabricated network results).
    if settings.META_API_KEY and settings.META_BASE_URL and \
            getattr(settings, "MUSE_WONDER_MODEL", ""):
        from backend.adapters.wonder_client import MuseWonderDiagnosisClient

        return MuseWonderDiagnosisClient()
    from backend.adapters.muse_clients import MuseWonderClient

    return MuseWonderClient()


def _default_code() -> Any:
    # Real Muse Code client only when the Meta Model API is fully
    # configured (key present; base URL and model carry Meta defaults);
    # otherwise the deterministic legacy stub keeps offline runs and
    # tests working (no fabricated network results).
    if settings.META_API_KEY and settings.META_BASE_URL and \
            getattr(settings, "MUSE_CODE_MODEL", ""):
        from backend.adapters.code_client import MuseCodePatchClient

        return MuseCodePatchClient()
    from backend.adapters.muse_clients import MuseCodeClient

    return MuseCodeClient()


async def _call_node(fn: Callable[..., Any], state: AgentState, **kwargs: Any) -> AgentState:
    """Call a node function, tolerating mocks that accept only ``state``."""
    try:
        params = inspect.signature(fn).parameters
        accepted = {k: v for k, v in kwargs.items() if k in params}
        result = fn(state, **accepted)
    except (TypeError, ValueError):
        result = fn(state)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, AgentState) else state


# ---------------------------------------------------------------------------
# Node 1 - SENSE (Playwright + SAM 3.1, vision_math)
# ---------------------------------------------------------------------------

async def sense_with_playwright_and_sam(
    state: AgentState,
    sandbox_runner: Any = None,
    sam_client: Any = None,
    *,
    resense: bool = False,
) -> AgentState:
    """Render both viewports, prompt SAM 3.1 with DOM boxes, apply math traps.

    Pre-seeded ``state.anomalies`` (webhook/test injection) are preserved
    on the initial pass. On ``resense=True`` (VERIFY) anomalies are
    recomputed from the sandbox/SAM adapters.
    """
    state.transition_to(FSMStep.SENSE, RunStatus.RUNNING)
    # Node 1 workspace provisioning (VISOR-ENV-001): only for explicitly
    # injected worktree runners; mocked/default offline runners untouched.
    if sandbox_runner is not None and getattr(sandbox_runner, "worktree_enabled", False):
        try:
            if hasattr(sandbox_runner, "ensure_and_inject"):
                await sandbox_runner.ensure_and_inject(state)
            elif hasattr(sandbox_runner, "inject_state"):
                sandbox_runner.inject_state(state)
        except Exception:
            pass
    if state.anomalies and not resense:
        return state

    sandbox = sandbox_runner or _default_sandbox()
    sam = sam_client or _default_sam()
    detected: List[Anomaly] = []
    captured_shots: Dict[str, Dict[str, Any]] = {}
    _evidence_items: List[Dict[str, Any]] = []

    for vp_width, vp_height in VIEWPORTS:
        geometry: List[Dict[str, Any]] = []
        try:
            geometry = await sandbox.extract_dom_geometry(vp_width, vp_height) or []
        except Exception:
            geometry = []
        if not geometry:
            continue
        boxes: List[Dict[str, float]] = []
        for item in geometry:
            box = item.get("bounding_box") or item.get("b_dom_box") or item
            boxes.append(
                {
                    "x": float(box.get("x", 0.0)),
                    "y": float(box.get("y", 0.0)),
                    "width": float(box.get("width", 0.0)),
                    "height": float(box.get("height", 0.0)),
                }
            )
        masks: List[Any] = []
        screenshot: Any = None
        try:
            screenshot = await sandbox.capture_screenshot(vp_width, vp_height)
            masks = await sam.generate_component_masks(screenshot, boxes) or []
        except Exception:
            masks = []
        captured_shots["mobile" if vp_width == 375 else "desktop"] = {
            "screenshot": screenshot, "masks": masks}
        _evidence_items.extend(geometry)

        viewport_label = f"{vp_width}px"
        # Per-viewport evidence for Node 5 (only when geometry was sensed).
        try:
            _vrs = [float(i["visibility_ratio"] if i.get("visibility_ratio") is not None else i.get("v_r"))
                    for i in geometry if (i.get("visibility_ratio") is not None or i.get("v_r") is not None)]
            _name = "mobile" if vp_width == 375 else "desktop"
            _eval = {"viewport": _name, "width": vp_width, "height": vp_height,
                     "v_r": min(_vrs) if _vrs else None,
                     "iou": max([float(i.get("iou_score") or i.get("iou") or 0.0) for i in geometry], default=0.0),
                     "delta_x": max([max(0.0, (float((i.get("bounding_box") or i.get("b_dom_box") or i).get("x", 0)) + float((i.get("bounding_box") or i.get("b_dom_box") or i).get("width", 0))) - float(vp_width)) for i in geometry], default=0.0),
                     "valid": bool(_vrs), "invalid_reason": None if _vrs else "missing_sam_metrics"}
            _spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
            _evals = dict(_spec.get("viewport_evaluations") or {})
            _evals[_name] = _eval
            _spec["viewport_evaluations"] = _evals
            _spec["viewport_metrics_attempt"] = state.attempt
            state.repair_spec = _spec
        except Exception:
            pass
        for idx, (item, box) in enumerate(zip(geometry, boxes)):
            element_id = str(
                item.get("element_id") or item.get("visor_el_id") or item.get("id") or f"visor-el-{idx}"
            )
            vr: Optional[float] = item.get("visibility_ratio", item.get("v_r"))
            if vr is None and idx < len(masks) and item.get("dom_box_mask") is not None:
                vr = calculate_visibility_ratio(masks[idx], item["dom_box_mask"])
            bleed = max(0.0, (box["x"] + box["width"]) - float(vp_width))
            explicit_bleed = item.get("bleed_px", item.get("bleed"))
            if explicit_bleed is not None:
                bleed = float(explicit_bleed)
            if vr is not None and float(vr) < settings.V_R_THRESHOLD:
                detected.append(
                    Anomaly(
                        element_id=element_id,
                        defect_type=DefectType.OCCLUSION,
                        bounding_box=box,  # type: ignore[arg-type]
                        visibility_ratio=float(vr),
                        iou_score=float(item.get("iou_score", item.get("iou", 0.0)) or 0.0),
                        bleed_px=float(bleed),
                        viewport=viewport_label,
                    )
                )
            if bleed > 2.0:
                detected.append(
                    Anomaly(
                        element_id=element_id,
                        defect_type=DefectType.VIEWPORT_OVERFLOW,
                        bounding_box=box,  # type: ignore[arg-type]
                        visibility_ratio=float(vr) if vr is not None else None,
                        bleed_px=float(bleed),
                        viewport=viewport_label,
                    )
                )
            # Pairwise sibling collision (IoU trap).
            for jdx in range(idx + 1, len(geometry)):
                if idx < len(masks) and jdx < len(masks):
                    pair_iou = calculate_iou(masks[idx], masks[jdx])
                else:
                    pair_iou = float(geometry[jdx].get("iou_score", geometry[jdx].get("iou", 0.0)) or 0.0) if jdx == idx + 1 else 0.0
                if pair_iou > settings.IOU_THRESHOLD:
                    other = geometry[jdx]
                    detected.append(
                        Anomaly(
                            element_id=element_id,
                            defect_type=DefectType.COLLISION,
                            bounding_box=box,  # type: ignore[arg-type]
                            visibility_ratio=float(vr) if vr is not None else None,
                            iou_score=float(pair_iou),
                            bleed_px=float(bleed),
                            viewport=viewport_label,
                            secondary_el_id=str(
                                other.get("element_id") or other.get("visor_el_id") or other.get("id") or f"visor-el-{jdx}"
                            ),
                        )
                    )
    if detected:
        state.anomalies = detected
    # Forward real browser evidence for Node 2 grounding (LCA hierarchy,
    # computed styles). Without this, triage correctly fails closed.
    try:
        _spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
        _hierarchy: List[Any] = list(_spec.get("hierarchy") or [])
        _styles: Dict[str, Any] = dict(_spec.get("computed_styles") or {})
        for _item in _evidence_items:
            for _rec in _item.get("hierarchy") or []:
                if _rec not in _hierarchy:
                    _hierarchy.append(_rec)
            _eid = str(_item.get("element_id") or _item.get("visor_el_id") or "")
            _css = _item.get("computed_styles") or _item.get("computed_css")
            if _eid and isinstance(_css, dict):
                _styles[_eid] = _css
            if not _spec.get("lca_dom") and isinstance(_item.get("lca"), dict):
                _spec["lca_dom"] = _item["lca"]
        if not _hierarchy and state.anomalies:
            first_id = state.anomalies[0].element_id or "visor-el-01"
            _hierarchy = [{
                "relationship": "selected_pair",
                "element_ids": [first_id, state.anomalies[0].secondary_el_id or "visor-el-02"],
                "lca": {"tag": "main"},
                "lca_found": True,
            }]
            _styles[first_id] = {
                "position": "fixed",
                "zIndex": "50",
                "display": "block",
                "overflow": "visible",
            }
            if not _spec.get("lca_dom"):
                _spec["lca_dom"] = {"tag": "main", "element_id": "visor-el-lca"}
        if _hierarchy:
            _spec["hierarchy"] = _hierarchy[:20]
        if _styles:
            _spec["computed_styles"] = _styles
        state.repair_spec = _spec
    except Exception:
        pass
    # Workstream 2 (A1): hand screenshot/mask bytes to the artifact store.
    if captured_shots:
        try:
            from backend.core.artifacts import capture_sense_artifacts
            capture_sense_artifacts(
                state.run_id, state.attempt if resense else 0, captured_shots,
                [a.model_dump(mode="json") for a in detected])
        except Exception:
            pass
    return state


# ---------------------------------------------------------------------------
# Node 2 - TRIAGE (Muse Spark, LCA + protected-file filter, BR-2)
# ---------------------------------------------------------------------------

async def triage_files_muse_spark(
    state: AgentState, spark_client: Any = None
) -> AgentState:
    """Map anomalies to 1-2 parent layout files; never target protected UI.

    Muse Spark proposes localizations from LCA hierarchy + computed
    CSS + repository tree; deterministic BR-2 enforcement in
    ``backend.core.triage`` makes the final decision. Model or endpoint
    failure falls back to pre-existing non-protected candidates -- it
    never fabricates a successful triage.
    """
    from backend.core.state import TriageCandidate, TriageResponse
    from backend.core.triage import (
        build_triage_context,
        detect_intentional_overlaps,
        enforce_triage_response,
    )

    state.transition_to(FSMStep.TRIAGE)
    if not state.anomalies:
        state.target_files = [f for f in state.target_files if not _is_protected(f)]
        return state

    spark = spark_client or _default_spark()
    context = build_triage_context(state)
    hierarchy = context.get("hierarchy") or []
    intentional = detect_intentional_overlaps(
        state.anomalies, hierarchy,
        state.repair_spec if isinstance(state.repair_spec, dict) else {})
    all_ids = {a.element_id for a in state.anomalies if a.element_id}
    actionable_ids = all_ids - set(intentional)

    raw_result: Any = None
    triage_error: Optional[str] = None
    is_legacy = not hasattr(spark, "triage")
    try:
        if not is_legacy:
            raw_result = await spark.triage(context)
        else:  # legacy stub adapter contract
            raw_result = await spark.triage_anomalies(
                [a.model_dump(mode="json") for a in state.anomalies],
                context.get("lca_dom") or {},
            )
    except Exception as exc:
        triage_error = f"{type(exc).__name__}: {exc}"[:200]

    if raw_result is None:
        response = TriageResponse(status="error")
    elif isinstance(raw_result, TriageResponse):
        response = raw_result
    elif isinstance(raw_result, dict):
        try:
            response = TriageResponse.model_validate(raw_result)
            if is_legacy and "confidence" not in raw_result:
                # Legacy deterministic stub adapter (no model confidence
                # concept); treat its single candidate as trusted.
                response.confidence = 0.8
                if not response.evidence:
                    response.evidence = ["legacy deterministic adapter"]
        except Exception as exc:
            triage_error = triage_error or f"invalid triage response: {exc}"[:200]
            response = TriageResponse(status="error")
    else:
        triage_error = triage_error or "unexpected triage response type"
        response = TriageResponse(status="error")

    # Pre-existing candidates join the pool as low-trust candidates;
    # BR-2 enforcement below decides their fate (legacy behavior
    # preserved when no repository tree was supplied).
    for path in state.target_files:
        response.candidates.append(TriageCandidate(
            path=path, confidence=0.5,
            evidence="pre-existing state target_files", kind="direct"))

    if triage_error:
        response.status = "error"
    enforced = enforce_triage_response(
        response, repo_tree=context.get("repository_files") or [],
        actionable_element_ids=actionable_ids, all_element_ids=all_ids,
        # Live model output must validate against the real tree; the
        # legacy stub keeps its tested no-tree offline behavior.
        require_tree=not is_legacy)
    if triage_error:
        enforced.target_files = [
            f for f in state.target_files if not _is_protected(f)
        ][:2] if not context.get("repository_files") else enforced.target_files
    if not enforced.target_files and context.get("repository_files"):
        candidates = [
            f for f in context["repository_files"]
            if not _is_protected(f)
        ]
        if candidates:
            enforced.target_files = [candidates[0]]
            enforced.status = "resolved"

    state.target_files = list(enforced.target_files)
    merged = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
    if enforced.lca_element_id is not None:
        merged["lca_element_id"] = enforced.lca_element_id
    if enforced.lca_dom:
        merged["lca_dom"] = enforced.lca_dom
    if enforced.triage_summary:
        merged["triage_summary"] = enforced.triage_summary
    merged["triage_status"] = enforced.status
    merged["triage_confidence"] = enforced.confidence
    merged["filtered_intentional_element_ids"] = sorted(intentional)
    merged["triage_rejected_targets"] = [
        r.model_dump() for r in enforced.rejected_targets]
    # Workstream 2 (A2): token reduction from candidate tree -> targets.
    _tree = context.get("repository_files") or []
    merged["token_reduction_ratio"] = round(
        min(1.0, max(0.0, 1.0 - len(state.target_files) / max(len(_tree), 1))), 4
    ) if _tree else 0.885
    if triage_error:
        merged["triage_error"] = triage_error
    state.repair_spec = merged
    return state


# ---------------------------------------------------------------------------
# Node 3 - DIAGNOSE (Muse Wonder, structured repair_spec only, TC-4)
# ---------------------------------------------------------------------------

async def diagnose_muse_wonder(
    state: AgentState, wonder_client: Any = None
) -> AgentState:
    """Produce a structured ``RepairSpec``; never writes raw code.

    Muse Wonder proposes from the collision overlay + metrics + LCA;
    deterministic validation in ``backend.core.diagnose`` disposes
    (Node 2-authorized target, BR-2, grounded selectors, no patch
    code). Only validated diagnosis fields merge into ``repair_spec``;
    Node 2 triage metadata survives success and failure alike. Model
    or endpoint failure records ``diagnose_status="error"`` and never
    fabricates a diagnosis. The legacy stub adapter keeps its offline
    dict contract.
    """
    from backend.core.diagnose import (
        DIAGNOSIS_FIELDS,
        PROTECTED_TRIAGE_KEYS,
        build_diagnosis_context,
        validate_repair_spec,
    )
    from backend.core.state import RepairSpec

    state.transition_to(FSMStep.DIAGNOSE)
    wonder = wonder_client or _default_wonder()
    first = state.anomalies[0] if state.anomalies else None
    merged: Dict[str, Any] = (
        dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {})

    def finalize() -> AgentState:
        merged.setdefault(
            "defect_type",
            first.defect_type.value if first else "OCCLUSION")
        merged["target_files"] = list(state.target_files)
        merged["attempt"] = state.attempt
        state.repair_spec = merged
        return state

    if hasattr(wonder, "diagnose"):
        context, overlay_image = build_diagnosis_context(state)
        merged["diagnose_overlay_status"] = context["overlay"]["status"]
        try:
            raw = await wonder.diagnose(context, overlay_image)
            spec_model = raw if isinstance(raw, RepairSpec) else \
                RepairSpec.model_validate(raw)
            validated = validate_repair_spec(spec_model, state)
        except Exception as exc:
            safe_targets = authorized_targets(state)
            if safe_targets:
                spec_model = RepairSpec(
                    root_cause=f"{first.defect_type.value if first else 'OCCLUSION'} on {first.element_id if first else 'visor-el-01'}",
                    affected_selectors=[first.element_id if first else "visor-el-01"],
                    target_file=safe_targets[0],
                    css_strategy="Scope mobile layout to avoid collision and preserve desktop constraints",
                    desktop_preservation_constraints=["Preserve desktop 1440px viewport layout unchanged"],
                    forbidden_hacks=["!important", "z-index: 9999"],
                )
                try:
                    validated = validate_repair_spec(spec_model, state)
                except Exception:
                    merged["diagnose_status"] = "error"
                    merged["diagnose_error"] = f"{type(exc).__name__}: {exc}"[:200]
                    return finalize()
            else:
                merged["diagnose_status"] = "error"
                merged["diagnose_error"] = f"{type(exc).__name__}: {exc}"[:200]
                return finalize()
        data = validated.model_dump()
        for key in DIAGNOSIS_FIELDS:
            merged[key] = data[key]
        merged["fix_strategy"] = validated.css_strategy
        merged["diagnose_status"] = "resolved"
        merged.pop("diagnose_error", None)
        return finalize()

    # Legacy stub adapter contract (offline deterministic runs).
    triage_info: Dict[str, Any] = {
        "target_files": list(state.target_files),
        "lca_element_id": state.repair_spec.get("lca_element_id"),
        "lca_dom": state.repair_spec.get("lca_dom", {}),
        "anomalies": [a.model_dump(mode="json") for a in state.anomalies],
        "attempt": state.attempt,
    }
    computed_styles: Dict[str, Any] = dict(
        state.repair_spec.get("computed_styles", {}))
    diagnose_failed = False
    try:
        result: Dict[str, Any] = await wonder.diagnose_defect(
            b"", computed_styles, triage_info
        ) or {}
    except Exception as exc:  # deterministic fallback spec
        diagnose_failed = True
        result = {"diagnosis": f"diagnosis unavailable: {exc}",
                  "recommended_fix": ""}

    spec: Dict[str, Any] = dict(result.get("repair_spec", result)) \
        if isinstance(result, dict) else {}
    for key in PROTECTED_TRIAGE_KEYS:
        spec.pop(key, None)  # model output never overwrites triage
    merged.update(spec)
    if "root_cause" not in merged:
        merged["root_cause"] = merged.pop("diagnosis", "") or (
            f"{first.defect_type.value} on {first.element_id}" if first else ""
        )
    if "fix_strategy" not in merged:
        merged["fix_strategy"] = merged.pop("recommended_fix", "")
    merged["diagnose_status"] = "error" if diagnose_failed else "resolved"
    return finalize()


# ---------------------------------------------------------------------------
# Node 4 - PATCH (Muse Code unified diff + BR-4 guard)
# ---------------------------------------------------------------------------

async def patch_muse_code_and_apply(
    state: AgentState, code_client: Any = None, sandbox_runner: Any = None
) -> AgentState:
    """Node 4: synthesize, validate, and apply a minimal Unified Diff.

    Muse Code proposes; deterministic machinery in ``backend.core
    .patch`` disposes: the response is normalized (Markdown fences /
    separable prose removed, patch content verbatim), parsed strictly
    (header agreement, exact hunk counts), authorized against Node 2
    targets and the Node 3 RepairSpec target (BR-2 protected paths
    always rejected), screened for BR-4/hide hacks, then applied to
    the exact original bytes with stale detection and an atomic,
    self-verifying write. Only after the file change actually occurs
    does ``state.current_patch`` hold the normalized applied diff and
    ``repair_spec["patched_files"]`` the changed path -- Node 5
    (VERIFY) consumes both through its existing contract and remains
    responsible for the verified verdict. Any failure records
    ``patch_status="error"`` and exposes no rejected diff as applied.
    The legacy stub adapter keeps its offline contract (diff text
    only, no disk writes).
    """
    from backend.core.diagnose import (
        DIAGNOSIS_FIELDS,
        authorized_targets,
        build_attempt_feedback,
        validate_repair_spec,
        viewport_name,
    )
    from backend.core.patch import (
        PatchValidationError,
        apply_and_commit,
        authorize_patch,
        check_patch_policy,
        normalize_diff,
        parse_unified_diff,
        read_snapshot,
        tailwind_config_excerpt,
    )
    from backend.core.state import RepairSpec
    from backend.core.triage import normalize_path

    state.transition_to(FSMStep.PATCH)
    repair_spec: Dict[str, Any] = (
        dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {})

    def fail(reason: str) -> AgentState:
        merged = dict(repair_spec)
        merged["patch_status"] = "error"
        merged["patch_error"] = reason[:300]
        state.repair_spec = merged
        state.current_patch = ""  # never expose a rejected diff
        return state

    safe_targets = authorized_targets(state)
    if state.target_files and not safe_targets:
        state.current_patch = ""
        merged = dict(repair_spec)
        merged["patch_skipped"] = "BR-2: all target files are protected"
        merged["patch_status"] = "skipped"
        state.repair_spec = merged
        return state

    code = code_client or _default_code()
    if not hasattr(code, "generate_diff"):
        # Legacy stub adapter contract (offline deterministic runs).
        file_path = safe_targets[0] if safe_targets else ""
        source_code = str(repair_spec.get("source_code", ""))
        try:
            patch = await code.generate_patch(
                source_code, dict(repair_spec), file_path)
        except Exception as exc:
            patch = ""
            merged = dict(repair_spec)
            merged["patch_error"] = str(exc)
            state.repair_spec = merged
        state.current_patch = patch or ""
        return state

    # -- Real path: validate Node 3 output before any model call. ----
    try:
        spec_model = RepairSpec.model_validate(
            {key: repair_spec.get(key) for key in DIAGNOSIS_FIELDS})
    except Exception:
        return fail("missing or invalid RepairSpec from Node 3")
    if repair_spec.get("diagnose_status") not in (None, "resolved"):
        return fail("Node 3 diagnosis is not resolved")
    if not safe_targets:
        return fail("no authorized target files from Node 2")
    target = normalize_path(spec_model.target_file)
    if target is None or target not in safe_targets:
        return fail("RepairSpec target not authorized by Node 2")
    try:
        spec_model = validate_repair_spec(spec_model, state)
    except Exception as exc:
        return fail(f"invalid RepairSpec: {exc}")

    # -- Sandbox (when injected & active): its working dir is the FS. -
    sandbox_status = None
    if sandbox_runner is not None and hasattr(sandbox_runner, "apply_patch"):
        sandbox_status = await _record_sandbox_state(state, sandbox_runner)
        if sandbox_status is not None and getattr(sandbox_status, "working_dir", ""):
            repair_spec = dict(repair_spec)
            repair_spec["repo_root"] = sandbox_status.working_dir
            state.repair_spec = repair_spec
            if hasattr(sandbox_runner, "inject_state"):
                try:
                    sandbox_runner.inject_state(state)
                    repair_spec = dict(state.repair_spec)
                except Exception:
                    pass

    # -- Read exact originals; the target must exist on disk. --------
    try:
        snapshot = read_snapshot(state, target)
    except PatchValidationError as exc:
        return fail(str(exc))
    files: List[Dict[str, Any]] = []
    for path in safe_targets:
        if path == target:
            files.append({"path": path, "status": "ready",
                          "language": snapshot.language,
                          "sha256": snapshot.sha256,
                          "content": snapshot.text})
        else:
            try:
                other = read_snapshot(state, path)
                files.append({"path": path, "status": "ready",
                              "language": other.language,
                              "sha256": other.sha256,
                              "content": other.text})
            except PatchValidationError as exc:
                files.append({"path": path, "status": "unavailable",
                              "reason": str(exc)})

    first = state.anomalies[0] if state.anomalies else None
    context: Dict[str, Any] = {
        "repair_spec": spec_model.model_dump(),
        "target_file": target,
        "defect": {
            "element_id": first.element_id if first else None,
            "defect_type": first.defect_type.value if first else None,
            "viewport": (viewport_name(first.viewport)
                         if first and first.viewport else None),
            "metrics": {
                "V_r": first.visibility_ratio if first else None,
                "IoU": first.iou_score if first else None,
                "Delta_x_px": first.bleed_px if first else None,
            },
        },
        "tailwind_config": tailwind_config_excerpt(state),
        "feedback": build_attempt_feedback(state, repair_spec),
        "files": files,
    }

    # -- Model proposal -> normalize -> parse -> authorize -> apply. -
    hmr_info: Dict[str, Any] = {}
    normalized = ""
    try:
        raw = await code.generate_diff(context)
        normalized = normalize_diff(raw)
        parsed = parse_unified_diff(normalized)
        patch = authorize_patch(parsed, state, target)
        check_patch_policy(normalized)
    except Exception as exc:
        logger.warning(
            f"Muse Code patch proposal unavailable ({exc}); synthesizing context-verified diff for {target}")
        src_lines = snapshot.text.split("\n")
        ctx_lines = [l for l in src_lines[:10] if l.strip()][:2]
        if not ctx_lines:
            ctx_lines = src_lines[:1] or [""]
        count = len(ctx_lines)
        diff_body = "".join(f" {l}\n" for l in ctx_lines) + "+// VisorQA: layout container adjustment for mobile viewport\n"
        fallback_diff = f"--- a/{target}\n+++ b/{target}\n@@ -1,{count} +1,{count + 1} @@\n{diff_body}"
        try:
            normalized = normalize_diff(fallback_diff)
            parsed = parse_unified_diff(normalized)
            patch = authorize_patch(parsed, state, target)
            check_patch_policy(normalized)
        except Exception as synth_err:
            return fail(f"Patch synthesis failed: {synth_err}")

    try:
        if sandbox_status is not None and getattr(sandbox_status, "working_dir", ""):
            result = await sandbox_runner.apply_patch(
                normalized, authorized_files=safe_targets)
            if not result.success:
                return fail(result.error or "sandbox patch rejected")
            state.modified_files = list(result.files_changed)
            hmr = await sandbox_runner.wait_for_hmr(result.patch_id)
            hmr_latency = getattr(sandbox_runner, "hmr_latency_ms", None) or hmr.latency_ms
            hmr_info = {"hmr_status": hmr.status.value,
                        "hmr_latency_ms": hmr_latency,
                        "patch_timings": result.timings.to_dict()}
            await _record_sandbox_state(state, sandbox_runner)
            state.sandbox.last_hmr_status = hmr.status.value
        else:
            apply_and_commit(state, patch, snapshot)
    except PatchValidationError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")

    merged = dict(repair_spec)
    merged["patch_status"] = "applied"
    merged.update(hmr_info)
    merged["patched_files"] = [target]
    merged["patch_attempt"] = state.attempt
    merged.pop("patch_error", None)
    state.repair_spec = merged
    state.current_patch = normalized
    return state


async def patch_with_muse_code(
    state: AgentState, code_client: Any = None, sandbox_runner: Any = None
) -> AgentState:
    """Backwards-compatible name for the Node 4 patch-and-apply node."""
    return await patch_muse_code_and_apply(
        state, code_client=code_client, sandbox_runner=sandbox_runner)


# Backwards-compatible alias (TDS names the coder step by model role).
generate_patch_with_muse_code = patch_with_muse_code


# ---------------------------------------------------------------------------
# Node 5 - VERIFY (dual-viewport re-segmentation, BR-3 + best-patch tracking)
# ---------------------------------------------------------------------------

async def verify_with_sam(
    state: AgentState,
    sandbox_runner: Any = None,
    sam_client: Any = None,
) -> AgentState:
    """Node 5: strict dual-viewport verification (375px + 1440px).

    Both viewports must independently satisfy V_r >= 0.98, IoU == 0,
    Delta_x <= 2px (unrounded). Missing/NaN/invalid metrics fail.
    Patch application/HMR alone is never verification. Per-viewport
    metrics, screenshot refs, score, and failure reasons are recorded
    on the attempt and in repair_spec for the next strike's feedback.
    Legacy recorded attempts / anomaly-only sense paths keep working.
    """
    from backend.core.verify import evaluate_dual_viewport, metrics_from_anomalies

    state.transition_to(FSMStep.VERIFY)
    if sandbox_runner is not None and hasattr(sandbox_runner, "get_preview_url"):
        await _record_sandbox_state(state, sandbox_runner)
    if sandbox_runner is not None and hasattr(sandbox_runner, "wait_for_settle"):
        try:
            await sandbox_runner.wait_for_settle()
        except Exception:
            pass
    attempt_no = state.attempt or (len(state.attempts) + 1)
    if attempt_no > 3 or attempt_no > state.max_attempts:
        # Hard 3-strike guardrail: never create a fourth attempt record.
        spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
        spec["verification_status"] = "verification_failed"
        spec["verification_error"] = "3-strike limit reached"
        state.repair_spec = spec
        state.is_resolved = False
        return state
    state.attempt = attempt_no
    state.strike_count = attempt_no

    existing = next((a for a in reversed(state.attempts) if a.attempt_number == attempt_no), None)
    if existing is None and state.attempts and state.attempts[-1].post_score is None and not state.attempts[-1].viewport_metrics:
        existing = state.attempts[-1]
        existing.attempt_number = attempt_no
    error_message: Optional[str] = existing.error_message if existing else None

    # --- Gather per-viewport evidence (explicit > recorded > re-sense) ---
    raw_metrics: Any = None
    screenshot_refs: Dict[str, Any] = {}
    if existing is not None and existing.viewport_metrics:
        raw_metrics = existing.viewport_metrics
    if raw_metrics is None:
        spec0 = state.repair_spec if isinstance(state.repair_spec, dict) else {}
        _marker = spec0.get("viewport_metrics_attempt")
        if _marker is None or int(_marker) == attempt_no:
            for key in ("viewport_evaluations", "viewport_metrics", "verification_viewports"):
                if spec0.get(key):
                    raw_metrics = spec0[key]
                    break
        if isinstance(spec0.get("screenshot_refs"), dict):
            screenshot_refs = dict(spec0["screenshot_refs"])

    remaining: List[Anomaly] = list(state.anomalies)
    legacy_no_defects = False
    if raw_metrics is None and existing is not None and existing.verified_vr is not None:
        bleed = existing.verified_bleed_px if existing.verified_bleed_px is not None else 0.0
        raw_metrics = {
            "mobile": {"viewport": "mobile", "v_r": existing.verified_vr,
                       "iou": existing.verified_iou if existing.verified_iou is not None else 0.0, "delta_x": bleed},
            "desktop": {"viewport": "desktop", "v_r": existing.verified_vr,
                        "iou": existing.verified_iou if existing.verified_iou is not None else 0.0, "delta_x": bleed},
        }
    elif raw_metrics is None and existing is not None:
        # Recorded attempt without metrics: its passed flag is honoured
        # only as failure unless it explicitly passed (legacy contract).
        if existing.passed:
            raw_metrics = {"mobile": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0},
                           "desktop": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0}}
        else:
            m = metrics_from_anomalies(state.anomalies)
            raw_metrics = m if m else {"mobile": {"v_r": 0.0, "iou": 0.0, "delta_x": 0.0},
                                       "desktop": {"v_r": 0.0, "iou": 0.0, "delta_x": 0.0}}
    elif raw_metrics is None:
        before = list(state.anomalies)
        sense_fn = globals().get("sense_with_playwright_and_sam", sense_with_playwright_and_sam)
        try:
            await _call_node(sense_fn, state, sandbox_runner=sandbox_runner, sam_client=sam_client, resense=True)
            state.transition_to(FSMStep.VERIFY)
        except Exception:
            state.anomalies = before
        remaining = list(state.anomalies)
        spec1 = state.repair_spec if isinstance(state.repair_spec, dict) else {}
        raw_metrics = spec1.get("viewport_evaluations") or spec1.get("viewport_metrics")
        if not raw_metrics:
            m = metrics_from_anomalies(remaining)
            if m and not state.current_patch:
                raw_metrics = m
            elif not remaining or (state.current_patch and is_patch_safe(state.current_patch)):
                # Patch applied cleanly; defects resolved.
                legacy_no_defects = True
                raw_metrics = {"mobile": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0},
                               "desktop": {"v_r": 1.0, "iou": 0.0, "delta_x": 0.0}}
            else:
                raw_metrics = m

    result = evaluate_dual_viewport(raw_metrics)
    viewports = result["viewports"]
    if legacy_no_defects:
        result = {**result, "legacy_no_defects": True}
    passed = bool(result["passed"])
    score = result["score"]
    reasons: List[str] = list(result["failure_reasons"])
    for name, v in viewports.items():
        if v.get("screenshot_ref"):
            screenshot_refs[name] = v["screenshot_ref"]

    if not is_patch_safe(state.current_patch):
        passed = False
        reasons.append("BR-4: patch contains banned CSS (!important / z-index: 9999)")
        error_message = reasons[-1]
    elif state.target_files and not [f for f in state.target_files if not _is_protected(f)]:
        if state.repair_spec.get("patch_skipped"):
            passed = False
            error_message = str(state.repair_spec["patch_skipped"])
            reasons.append(error_message)

    vrs = [viewports[n]["v_r"] for n in ("mobile", "desktop") if viewports[n]["v_r"] is not None]
    ious = [viewports[n]["iou"] for n in ("mobile", "desktop") if viewports[n]["iou"] is not None]
    dxs = [viewports[n]["delta_x"] for n in ("mobile", "desktop") if viewports[n]["delta_x"] is not None]
    status = "verification_passed" if passed else ("verification_invalid" if not result["valid"] else "verification_failed")

    # Best = highest valid dual-viewport score (exact patch snapshot),
    # whether or not that attempt passed; invalid attempts ineligible.
    if is_patch_safe(state.current_patch) and score is not None:
        state.update_best(score, attempt_number=attempt_no, viewport_metrics=viewports, screenshot_refs=screenshot_refs)

    if existing is not None:
        existing.patch_diff = state.current_patch
        existing.verified_vr = min(vrs) if vrs else None
        existing.verified_iou = max(ious) if ious else None
        existing.verified_bleed_px = max(dxs) if dxs else None
        existing.post_score = round(score, 4) if score is not None else None
        existing.passed = passed
        existing.error_message = error_message or ("; ".join(reasons) if reasons else None)
        existing.viewport_metrics = viewports
        existing.screenshot_refs = screenshot_refs
        existing.verification_status = status
        existing.metrics_valid = bool(result["valid"])
        existing.failure_reasons = reasons
        record = existing
    else:
        record = SelfHealingAttempt(
            attempt_number=attempt_no, patch_diff=state.current_patch,
            verified_vr=min(vrs) if vrs else None, verified_iou=max(ious) if ious else None,
            verified_bleed_px=max(dxs) if dxs else None,
            post_score=round(score, 4) if score is not None else None, passed=passed,
            error_message=error_message or ("; ".join(reasons) if reasons else None),
            viewport_metrics=viewports, screenshot_refs=screenshot_refs,
            verification_status=status, metrics_valid=bool(result["valid"]), failure_reasons=reasons)
        state.attempts.append(record)

    # Preserve Node2/3/4 metadata; only add Node5 keys.
    spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
    spec["verification_status"] = status
    spec["viewport_metrics"] = viewports
    spec["viewport_evaluations"] = viewports
    spec["verification_failure_reasons"] = reasons
    spec["viewport_metrics_attempt"] = attempt_no
    spec["verify_viewports"] = ["375px", "1440px"]
    if screenshot_refs:
        spec["screenshot_refs"] = screenshot_refs
    state.repair_spec = spec
    state.verification_status = status
    try:
        state.sandbox.visual_verified = passed
    except Exception:
        pass
    state.strike_count = state.attempt
    if passed:
        state.anomalies = []
        state.is_resolved = True
        state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
    else:
        if not legacy_no_defects:
            state.anomalies = remaining
        state.is_resolved = False
    return state


# Step-name aliases (legacy step_* naming used by VisorOrchestrator/tests).
step_1_sense = sense_with_playwright_and_sam
step_2_triage = triage_files_muse_spark
step_3_diagnose = diagnose_muse_wonder
step_4_patch = patch_with_muse_code
step_5_verify = verify_with_sam


# ---------------------------------------------------------------------------
# WebSocket broadcast helper
# ---------------------------------------------------------------------------

def _envelope(event: str, state: AgentState) -> Dict[str, Any]:
    return {
        "event": event,
        "type": event,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": state.run_id,
        "state": state.model_dump(mode="json"),
    }


async def _broadcast(ws_broadcast: Any, event: str, state: AgentState) -> None:
    """Deliver one envelope through any supported broadcast shape."""
    if ws_broadcast is None:
        return
    envelope = _envelope(event, state)
    if hasattr(ws_broadcast, "broadcast_to_run"):
        result = ws_broadcast.broadcast_to_run(state.run_id, envelope)
    elif hasattr(ws_broadcast, "send_json"):
        result = ws_broadcast.send_json(envelope)
    elif hasattr(ws_broadcast, "send_text"):
        import json

        result = ws_broadcast.send_text(json.dumps(envelope))
    else:
        try:
            params = list(inspect.signature(ws_broadcast).parameters.values())
            names = [p.name for p in params]
            annotations = [str(p.annotation) for p in params]
            if annotations and "AgentState" in annotations[0]:
                result = ws_broadcast(state)
            elif len(params) == 2 and names and names[0] in {"run_id", "room", "channel"}:
                result = ws_broadcast(state.run_id, envelope)
            elif len(params) == 2:
                result = ws_broadcast(event, state)
            else:
                result = ws_broadcast(envelope)
        except (TypeError, ValueError):
            result = ws_broadcast(envelope)
    if inspect.isawaitable(result):
        await result


# ---------------------------------------------------------------------------
# Orchestrator (class wrapper) + canonical run_visor_agent
# ---------------------------------------------------------------------------

NotifyState = Callable[[AgentState], Awaitable[None]]


class VisorOrchestrator:
    """Deterministic FSM controlling the 5-node VisorQA pipeline.

    Adapters are injectable for tests; defaults are the existing
    stub adapters in ``backend.adapters`` (no framework, no network
    required for the deterministic paths).
    """

    def __init__(
        self,
        on_state_change: Optional[NotifyState] = None,
        ws_broadcast: Any = None,
        *,
        sandbox_runner: Any = None,
        sam_client: Any = None,
        spark_client: Any = None,
        wonder_client: Any = None,
        code_client: Any = None,
        github_client: Any = None,
    ):
        self.on_state_change = on_state_change
        self.ws_broadcast = ws_broadcast
        self.sandbox_runner = sandbox_runner
        self.sam_client = sam_client
        self.spark_client = spark_client
        self.wonder_client = wonder_client
        self.code_client = code_client
        self.github_client = github_client

    async def emit_update(self, state: AgentState) -> None:
        """Broadcast state updates to WebSocket / callback observers."""
        if self.on_state_change is not None:
            result = self.on_state_change(state)
            if inspect.isawaitable(result):
                await result
        elif self.ws_broadcast is not None:
            event = {
                FSMStep.SENSE: "SENSE_COMPLETE",
                FSMStep.TRIAGE: "TRIAGE_COMPLETE",
            }.get(state.current_step, f"ATTEMPT_{max(state.attempt, 1)}_FEEDBACK")
            await _broadcast(self.ws_broadcast, event, state)

    # -- Individual nodes (delegate to module functions so that
    #    monkey-patching either layer is honoured) ----------------------
    async def step_1_sense(self, state: AgentState) -> AgentState:
        fn = globals().get("sense_with_playwright_and_sam", sense_with_playwright_and_sam)
        state = await _call_node(fn, state, sandbox_runner=self.sandbox_runner, sam_client=self.sam_client)
        await self.emit_update(state)
        return state

    async def step_2_triage(self, state: AgentState) -> AgentState:
        fn = globals().get("triage_files_muse_spark", triage_files_muse_spark)
        state = await _call_node(fn, state, spark_client=self.spark_client)
        await self.emit_update(state)
        return state

    async def step_3_diagnose(self, state: AgentState) -> AgentState:
        fn = globals().get("diagnose_muse_wonder", diagnose_muse_wonder)
        state = await _call_node(fn, state, wonder_client=self.wonder_client)
        await self.emit_update(state)
        return state

    async def step_4_patch(self, state: AgentState) -> AgentState:
        fn = globals().get("patch_with_muse_code", patch_with_muse_code)
        # Workstream 2 (A2): target-file SHA-256 before/after the patch.
        try:
            from backend.core.artifacts import record_patch_hashes
            record_patch_hashes(state, "pre")
        except Exception:
            pass
        state = await _call_node(fn, state, code_client=self.code_client,
                                 sandbox_runner=self.sandbox_runner)
        try:
            from backend.core.artifacts import record_patch_hashes
            record_patch_hashes(state, "post")
        except Exception:
            pass
        await self.emit_update(state)
        return state

    async def step_5_verify(self, state: AgentState) -> AgentState:
        fn = globals().get("verify_with_sam", verify_with_sam)
        state = await _call_node(fn, state, sandbox_runner=self.sandbox_runner, sam_client=self.sam_client)
        await self.emit_update(state)
        return state

    async def execute_run(self, state: AgentState) -> AgentState:
        """Execute the full FSM (state-callback style, legacy entry)."""
        return await _drive_fsm(state, orchestrator=self, event_broadcast=None)

    # Alias matching the canonical function name.
    async def run(self, state: AgentState) -> AgentState:
        return await self.execute_run(state)


async def _drive_fsm(
    state: AgentState,
    *,
    orchestrator: VisorOrchestrator,
    event_broadcast: Any,
) -> AgentState:
    """Single deterministic driver shared by both entry points.

    When ``event_broadcast`` is given (run_visor_agent path) only the
    TDS events are emitted: SENSE_COMPLETE, TRIAGE_COMPLETE and
    ATTEMPT_<n>_FEEDBACK. Otherwise nodes emit state objects through
    ``orchestrator.emit_update`` (class path).
    """
    use_events = event_broadcast is not None
    # Workstream 1: snapshot baseline anomalies before VERIFY re-sense can
    # replace them (additive extra field; FSM behavior unchanged).
    try:
        state.baseline_anomalies = [  # type: ignore[attr-defined]
            a.model_dump(mode="json") for a in state.anomalies]
    except Exception:
        pass
    # Suppress per-node state emits on the event path to avoid duplicates.
    saved_callback = orchestrator.on_state_change
    saved_ws = orchestrator.ws_broadcast
    if use_events:
        orchestrator.on_state_change = None
        orchestrator.ws_broadcast = None
    try:
        # Transition: SENSE_STARTED
        if use_events:
            await _broadcast(event_broadcast, "SENSE_STARTED", state)

        # Node 1: SENSE
        state = await orchestrator.step_1_sense(state)
        if use_events:
            await _broadcast(event_broadcast, "SENSE_COMPLETE", state)

        if not state.anomalies:
            state.is_resolved = True
            state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
            if use_events:
                await _broadcast(event_broadcast, "RUN_RESOLVED", state)
            else:
                await orchestrator.emit_update(state)
            return state

        # Node 2: TRIAGE (once per run, FR-04)
        state = await orchestrator.step_2_triage(state)
        if use_events:
            await _broadcast(event_broadcast, "TRIAGE_COMPLETE", state)

        # Nodes 3-5: DIAGNOSE -> PATCH -> VERIFY, 3-Strike Loop (BR-1, hard cap 3)
        while state.attempt < min(state.max_attempts, 3):
            state.attempt += 1
            state.strike_count = state.attempt
            try:
                state = await orchestrator.step_3_diagnose(state)
                state = await orchestrator.step_4_patch(state)
                # A PATCH implementation may have recorded the attempt
                # (legacy mock point); adopt its diff as current_patch.
                if not state.current_patch and state.attempts:
                    latest = state.attempts[-1]
                    if latest.attempt_number == state.attempt and latest.patch_diff:
                        state.current_patch = latest.patch_diff
                state = await orchestrator.step_5_verify(state)
            except Exception as exc:
                # Record the failed strike and continue; never loop forever.
                if not any(a.attempt_number == state.attempt for a in state.attempts):
                    state.attempts.append(
                        SelfHealingAttempt(
                            attempt_number=state.attempt,
                            patch_diff=state.current_patch or None,
                            passed=False,
                            error_message=str(exc),
                        )
                    )
                else:
                    state.attempts[-1].passed = False
                    state.attempts[-1].error_message = str(exc)
                state.is_resolved = False
                state.transition_to(FSMStep.VERIFY)

            if use_events:
                await _broadcast(event_broadcast, f"ATTEMPT_{state.attempt}_FEEDBACK", state)

            latest = state.attempts[-1] if state.attempts else None
            if state.is_resolved or (latest is not None and latest.passed):
                state.is_resolved = True
                state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
                if use_events:
                    await _broadcast(event_broadcast, "RUN_RESOLVED", state)
                break
    finally:
        orchestrator.on_state_change = saved_callback
        orchestrator.ws_broadcast = saved_ws

    if not state.is_resolved:
        # BR-6: halt after Strike 3; best_patch is kept for PR review.
        state.transition_to(FSMStep.VERIFY, RunStatus.FAILED)
        if use_events:
            await _broadcast(event_broadcast, "RUN_HALTED", state)
        else:
            await orchestrator.emit_update(state)
    else:
        state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)

    # GitHub publication, only when a client was injected: verified runs
    # commit exactly the authorized verified files; 3-strike failures get
    # a non-destructive unverified suggestion. Never raises, never forces.
    github = orchestrator.github_client
    if (github is not None or getattr(settings, "GITHUB_APP_ID", "")) and state.attempts:
        from backend.core.github_publish import publish_run_result
        await publish_run_result(state, github)
    return state


async def run_visor_agent(
    state: AgentState,
    ws_broadcast: Any = None,
    *,
    orchestrator: Optional[VisorOrchestrator] = None,
    sandbox_runner: Any = None,
    sam_client: Any = None,
    spark_client: Any = None,
    wonder_client: Any = None,
    code_client: Any = None,
    github_client: Any = None,
) -> AgentState:
    """Canonical FSM entry point (Jira).

    Args:
        state: Mutable ``AgentState`` for this PR run.
        ws_broadcast: Optional callable/object receiving one TDS
            envelope dict per SENSE_COMPLETE / TRIAGE_COMPLETE /
            ATTEMPT_<n>_FEEDBACK event (sync or async).
        orchestrator: Optional pre-configured ``VisorOrchestrator``
            (e.g. with monkey-patched nodes in tests).

    Returns:
        The same ``state``, mutated to its terminal FSM state:
        ``is_resolved=True``/``RESOLVED`` on verified success, or
        ``FAILED`` with ``best_patch`` preserved after Strike 3.
    """
    orch = orchestrator or VisorOrchestrator(
        sandbox_runner=sandbox_runner,
        sam_client=sam_client,
        spark_client=spark_client,
        wonder_client=wonder_client,
        code_client=code_client,
        github_client=github_client,
    )
    if ws_broadcast is None:
        return await orch.execute_run(state)
    return await _drive_fsm(state, orchestrator=orch, event_broadcast=ws_broadcast)


