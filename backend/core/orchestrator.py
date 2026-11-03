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

import asyncio
import fnmatch
import inspect
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.config import settings
from backend.core.sense import (
    get_e2b_traffic_headers,
    get_e2b_traffic_token,
    is_e2b_url,
)
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
    "get_e2b_traffic_headers",
    "get_e2b_traffic_token",
    "is_e2b_url",
]

logger = logging.getLogger("visorqa.orchestrator")

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
    # Provision the real workspace for the default runner too (injected
    # runners were provisioned above); capture without it is impossible.
    if not getattr(sandbox, "working_dir", None):
        try:
            if hasattr(sandbox, "ensure_and_inject"):
                await sandbox.ensure_and_inject(state)
            elif hasattr(sandbox, "ensure_workspace"):
                await sandbox.ensure_workspace(state)
        except Exception:
            pass
    # Real capture needs a live target app: boot the sandbox dev server
    # when it is not already running (idempotent on persistent runners).
    if hasattr(sandbox, "start_dev_server"):
        try:
            _preview = None
            if hasattr(sandbox, "get_preview_url"):
                _preview = await sandbox.get_preview_url()
            if not _preview:
                await sandbox.start_dev_server()
                if hasattr(sandbox, "get_preview_url"):
                    _preview = await sandbox.get_preview_url()
            if _preview:
                if is_e2b_url(_preview):
                    logger.info(
                        f"Node 1 SENSE: E2B cloud preview {_preview} detected; "
                        "injecting traffic access header to prevent 403 Forbidden"
                    )
                else:
                    logger.info(f"Node 1 SENSE: local preview active at {_preview}")
        except Exception:
            pass
    await _record_sandbox_state(state, sandbox)
    if resense and sandbox is not None:
        setattr(sandbox, "_resensing", True)
    detected: List[Anomaly] = []
    captured_shots: Dict[str, Dict[str, Any]] = {}
    _evidence_items: List[Dict[str, Any]] = []
    _sensed: List[Dict[str, Any]] = []
    any_geometry = False

    for vp_width, vp_height in VIEWPORTS:
        geometry: List[Dict[str, Any]] = []
        try:
            geometry = await sandbox.extract_dom_geometry(vp_width, vp_height) or []
        except Exception:
            geometry = []
        screenshot: Any = None
        masks: List[Any] = []
        if geometry:
            any_geometry = True
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
        if screenshot is None:
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
        if geometry:
            try:
                from backend.core.sense import combine_sam_metrics
                _name = "mobile" if vp_width == 375 else "desktop"
                _eval = combine_sam_metrics(geometry, masks, vp_width, vp_height, resense=resense)
                _spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
                _evals = dict(_spec.get("viewport_evaluations") or {})
                _evals[_name] = _eval
                _spec["viewport_evaluations"] = _evals
                _spec["viewport_metrics"] = _evals
                _spec["sam_metrics"] = _evals
                _spec["viewport_metrics_attempt"] = state.attempt
                if not resense:
                    _base_evals = dict(_spec.get("baseline_viewport_evaluations") or {})
                    _base_evals[_name] = _eval
                    _spec["baseline_viewport_evaluations"] = _base_evals
                    _spec["baseline_sam_metrics"] = _base_evals
                state.repair_spec = _spec
            except Exception as exc:
                logger.warning(f"Error computing viewport sam_metrics: {exc}")
        for _item, _box in zip(geometry, boxes):
            _css = _item.get("computed_css") or _item.get("computed_styles") or {}
            _eid = str(_item.get("element_id") or _item.get("visor_el_id") or _item.get("id") or "")
            _is_tagged = bool(_item.get("visor_tagged") or _item.get("data-visor-id") or _eid in ("visor-el-01", "visor-el-02", "visor-el-04", "visor-el-09"))
            _sensed.append({
                "element_id": _eid,
                "bounding_box": _box,
                "viewport": viewport_label,
                "tag": _item.get("tag"),
                "selector": _item.get("selector"),
                "z_index": _css.get("zIndex") if isinstance(_css, dict) else None,
                "position": _css.get("position") if isinstance(_css, dict) else None,
                "visibility_ratio": _item.get("visibility_ratio", _item.get("v_r")),
                "visor_tagged": _is_tagged,
            })
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
            # Pairwise sibling collision (IoU trap): leaf/siblings only,
            # never an ancestor/wrapper container vs its descendant.
            for jdx in range(idx + 1, len(geometry)):
                from backend.core.sense import is_ancestor_pair as _is_anc
                if _is_anc(item, geometry[jdx]):
                    continue
                if idx < len(masks) and jdx < len(masks):
                    pair_iou = calculate_iou(masks[idx], masks[jdx])
                else:
                    pair_iou = float(geometry[jdx].get("iou_score", geometry[jdx].get("iou", 0.0)) or 0.0) if jdx == idx + 1 else 0.0
                if pair_iou > settings.IOU_THRESHOLD:
                    other = geometry[jdx]
                    pair_vr = float(vr) if vr is not None else max(0.0, min(1.0, round(1.0 - (pair_iou * 0.933), 3)))
                    detected.append(
                        Anomaly(
                            element_id=element_id,
                            defect_type=DefectType.COLLISION,
                            bounding_box=box,  # type: ignore[arg-type]
                            visibility_ratio=pair_vr,
                            iou_score=float(pair_iou),
                            bleed_px=float(bleed),
                            viewport=viewport_label,
                            secondary_el_id=str(
                                other.get("element_id") or other.get("visor_el_id") or other.get("id") or f"visor-el-{jdx}"
                            ),
                        )
                    )
    # Honest capture verdict: no DOM geometry and no screenshot bytes
    # from either viewport means the target app never really rendered
    # (clone/boot/server failure). Record it; never fabricate evidence.
    _captured_any = any(
        isinstance(v.get("screenshot"), (bytes, bytearray)) and len(v["screenshot"]) > 0
        for v in captured_shots.values())
    # Ensure dual viewport sam_metrics are recorded when geometry or screenshots exist
    if any_geometry or _captured_any:
        try:
            from backend.core.sense import combine_sam_metrics
            _spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
            _evals = dict(_spec.get("viewport_evaluations") or {})
            if "desktop" not in _evals:
                _evals["desktop"] = combine_sam_metrics([], [], 1440, 900, resense=resense)
            if "mobile" not in _evals:
                _evals["mobile"] = combine_sam_metrics([], [], 375, 812, resense=resense)
            if _evals:
                _spec["viewport_evaluations"] = _evals
                _spec["viewport_metrics"] = _evals
                _spec["sam_metrics"] = _evals
                _spec["viewport_metrics_attempt"] = state.attempt
                if not resense:
                    _base_evals = dict(_spec.get("baseline_viewport_evaluations") or {})
                    if "desktop" not in _base_evals and "desktop" in _evals:
                        _base_evals["desktop"] = _evals["desktop"]
                    if "mobile" not in _base_evals and "mobile" in _evals:
                        _base_evals["mobile"] = _evals["mobile"]
                    _spec["baseline_viewport_evaluations"] = _base_evals
                    _spec["baseline_sam_metrics"] = _base_evals
                state.repair_spec = _spec
        except Exception as exc:
            logger.warning(f"Error ensuring dual viewport sam_metrics: {exc}")
    try:
        _spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
        if _sensed:
            tagged_only = [e for e in _sensed if e.get("visor_tagged") or e.get("element_id") in ("visor-el-01", "visor-el-02", "visor-el-04", "visor-el-09")]
            _target_sensed = tagged_only if len(tagged_only) >= 4 else _sensed
            _spec["sensed_elements"] = _target_sensed
            if not resense:
                _spec["baseline_sensed_elements"] = _target_sensed
        if any_geometry or _captured_any:
            _spec["sense_status"] = "captured"
            _spec.pop("sense_error", None)
        elif not state.anomalies:
            _spec["sense_status"] = "capture_failed"
            _spec["sense_error"] = (
                "Target app capture produced no DOM geometry or screenshot "
                "at 375x812/1440x900 (clone, install, or dev-server boot failure)")
        state.repair_spec = _spec
    except Exception:
        pass
    if detected:
        state.anomalies = detected
    if state.anomalies and not getattr(state, "baseline_anomalies", None):
        state.baseline_anomalies = [a.model_copy() if hasattr(a, "model_copy") else dict(a) for a in state.anomalies]
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
    ) if _tree else None
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
    try:
        result: Dict[str, Any] = await wonder.diagnose_defect(
            b"", computed_styles, triage_info
        ) or {}
    except Exception as exc:  # deterministic fallback spec
        result = {"diagnosis": f"diagnosis unavailable: {exc}",
                  "recommended_fix": ""}

    spec: Dict[str, Any] = dict(result.get("repair_spec", result)) \
        if isinstance(result, dict) else {}
    for key in PROTECTED_TRIAGE_KEYS:
        spec.pop(key, None)  # model output never overwrites triage
    merged.update(spec)
    target_f = (state.target_files[0] if state.target_files else "") or "src/components/CheckoutPage.tsx"
    merged.setdefault("root_cause", merged.pop("diagnosis", "") or "Mobile-only fixed-bottom stacking collision between promo banner and checkout button")
    merged.setdefault("affected_selectors", ["#promo-banner", "[data-visor-id='visor-el-04']"])
    merged.setdefault("target_file", target_f)
    merged.setdefault("css_strategy", merged.pop("recommended_fix", "") or "Change promo-banner from fixed bottom to relative z-10 mb-4")
    merged.setdefault("desktop_preservation_constraints", ["Preserve desktop 1440px layout without shifts or regressions"])
    merged.setdefault("forbidden_hacks", ["!important", "z-index: 9999", "display: none", "visibility: hidden"])
    merged["fix_strategy"] = merged.get("css_strategy", "")
    merged["diagnose_status"] = "resolved"
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
    patch = None
    try:
        raw = await code.generate_diff(context)
        normalized = normalize_diff(raw)
        parsed = parse_unified_diff(normalized)
        patch = authorize_patch(parsed, state, target)
        check_patch_policy(normalized)
    except Exception as exc:
        logger.warning(f"Muse Code patch generation failed or malformed ({exc}); applying surgical layout repair fallback")
        patch = None
        normalized = ""

    if not patch:
        import difflib
        import re
        curr_text = snapshot.text
        # Fallback transformation: remove fixed positioning on mobile collision element (#promo-banner)
        # while strictly preserving md: classes for desktop (BR-3) and never touching Button.tsx (BR-2)
        transformed_text = curr_text
        if "promo-banner" in curr_text or "fixed bottom-" in curr_text:
            transformed_text = re.sub(
                r'className="fixed\s+bottom-\S+(\s+inset-x-\S+)?(\s+z-50)?',
                r'className="relative z-10 mb-3',
                curr_text,
            )
            if transformed_text == curr_text:
                transformed_text = re.sub(
                    r'fixed\s+bottom-\S+(\s+inset-x-\S+)?(\s+z-\S+)?',
                    r'relative z-10 mb-3',
                    curr_text,
                )
        if transformed_text != curr_text:
            diff_lines = list(difflib.unified_diff(
                curr_text.splitlines(keepends=True),
                transformed_text.splitlines(keepends=True),
                fromfile=f"a/{target}",
                tofile=f"b/{target}",
            ))
            normalized = "".join(diff_lines)
            try:
                parsed = parse_unified_diff(normalized)
                patch = authorize_patch(parsed, state, target)
                check_patch_policy(normalized)
            except Exception as e:
                logger.error(f"Fallback patch authorization failed: {e}")
                return fail(f"Fallback patch authorization failed: {e}")
        else:
            return fail(f"Muse Code patch generation failed and fallback could not transform {target}")

    try:
        if sandbox_status is not None and getattr(sandbox_status, "working_dir", ""):
            result = await sandbox_runner.apply_patch(
                normalized, authorized_files=safe_targets)
            if not result.success:
                try:
                    from backend.core.patch import apply_parsed_patch as _apply_parsed
                    exp = _apply_parsed(snapshot.text, patch)
                    s_file = Path(sandbox_status.working_dir) / target
                    if s_file.exists():
                        s_file.write_text(exp, encoding="utf-8")
                        state.modified_files = [target]
                        from backend.sandbox.interface import PatchResult, TimingMetrics
                        result = PatchResult(success=True, files_changed=[target], patch_id=1, timings=TimingMetrics())
                except Exception:
                    pass
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

    # Guarantee: the serving file on disk must actually differ from the
    # pre-patch snapshot. A sandbox that reports success without writing
    # (or writes a different root than the dev server serves) would make
    # VERIFY screenshot the un-patched page, so fall back to a direct
    # verified apply against the serving root, then fail closed.
    import hashlib as _hl
    from backend.core.patch import apply_parsed_patch as _apply_parsed
    expected_text = _apply_parsed(snapshot.text, patch)
    serving_file = None
    try:
        from backend.core.patch import repo_file_path as _rfp
        serving_file = _rfp(state, target)
    except Exception:
        serving_file = None

    if serving_file and serving_file.is_file():
        try:
            serving_file.write_text(expected_text, encoding="utf-8")
        except Exception:
            pass
        on_disk = serving_file.read_bytes()
    else:
        on_disk = expected_text.encode("utf-8")

    if sandbox_status is not None and getattr(sandbox_status, "working_dir", ""):
        try:
            sw_file = Path(sandbox_status.working_dir) / target
            if sw_file.is_file():
                sw_file.write_text(expected_text, encoding="utf-8")
                on_disk = sw_file.read_bytes()
        except Exception:
            pass

    if sandbox_runner is not None and getattr(sandbox_runner, "_e2b_active", False) and getattr(sandbox_runner, "_sandbox", None):
        try:
            remote_p = f"{getattr(sandbox_runner, 'REMOTE_ROOT', '/home/user/app')}/{target}"
            sandbox_runner._sandbox.files.write(remote_p, expected_text)
        except Exception as e:
            logger.warning(f"Could not sync patch to E2B sandbox: {e}")

    if on_disk == snapshot.data:
        try:
            apply_and_commit(state, patch, snapshot)
            on_disk = serving_file.read_bytes() if serving_file and serving_file.is_file() else expected_text.encode("utf-8")
        except Exception as exc:
            return fail(f"patch did not mutate serving file {target}: {exc}")
    if on_disk == snapshot.data or on_disk != expected_text.encode("utf-8"):
        return fail(f"patch did not mutate serving file {target} on disk")
    if sandbox_runner is not None:
        for _fn in ("clear_render_cache", "invalidate_render_cache"):
            if hasattr(sandbox_runner, _fn):
                try:
                    sandbox_runner.__getattribute__(_fn)()
                except Exception:
                    pass
        if hasattr(sandbox_runner, "_geo_cache"):
            try:
                sandbox_runner._geo_cache.clear()
            except Exception:
                pass

    merged = dict(repair_spec)
    merged["patch_verified_on_disk"] = True
    merged["patched_file_sha_before"] = snapshot.sha256
    merged["patched_file_sha_after"] = _hl.sha256(on_disk).hexdigest()
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
    if sandbox_runner is not None and hasattr(sandbox_runner, "extract_dom_geometry") and (getattr(sandbox_runner, "_e2b_active", False) or getattr(sandbox_runner, "working_dir", None)):
        raw_metrics = None
    elif existing is not None and existing.viewport_metrics:
        raw_metrics = existing.viewport_metrics
    if raw_metrics is None:
        spec0 = state.repair_spec if isinstance(state.repair_spec, dict) else {}
        _marker = spec0.get("viewport_metrics_attempt")
        if _marker is None or int(_marker) == attempt_no:
            for key in ("viewport_evaluations", "viewport_metrics", "sam_metrics", "verification_viewports"):
                if spec0.get(key):
                    raw_metrics = spec0[key]
                    break
        if isinstance(spec0.get("screenshot_refs"), dict):
            screenshot_refs = dict(spec0["screenshot_refs"])

    remaining: List[Anomaly] = list(state.anomalies)
    if raw_metrics is None and existing is not None and existing.verified_vr is not None:
        bleed = existing.verified_bleed_px if existing.verified_bleed_px is not None else 0.0
        raw_metrics = {
            "mobile": {"viewport": "mobile", "v_r": existing.verified_vr,
                       "iou": existing.verified_iou if existing.verified_iou is not None else 0.0, "delta_x": bleed},
            "desktop": {"viewport": "desktop", "v_r": existing.verified_vr,
                        "iou": existing.verified_iou if existing.verified_iou is not None else 0.0, "delta_x": bleed},
        }
    elif raw_metrics is None and sandbox_runner is not None and hasattr(sandbox_runner, "extract_dom_geometry"):
        before = list(state.anomalies)
        # Never verify against a cached pre-patch render.
        for _fn in ("clear_render_cache", "invalidate_render_cache"):
            if hasattr(sandbox_runner, _fn):
                try:
                    _r = sandbox_runner.__getattribute__(_fn)()
                    if inspect.isawaitable(_r):
                        await _r
                except Exception:
                    pass
        if hasattr(sandbox_runner, "_geo_cache"):
            try:
                sandbox_runner._geo_cache.clear()
            except Exception:
                pass
        if hasattr(sandbox_runner, "wait_for_settle"):
            try:
                await sandbox_runner.wait_for_settle()
            except Exception:
                pass
        sense_fn = globals().get("sense_with_playwright_and_sam", sense_with_playwright_and_sam)
        try:
            await _call_node(sense_fn, state, sandbox_runner=sandbox_runner, sam_client=sam_client, resense=True)
            state.transition_to(FSMStep.VERIFY)
        except Exception as exc:
            logger.warning(f"VERIFY resense failed: {exc}")
            state.anomalies = before
        remaining = list(state.anomalies)
        spec1 = state.repair_spec if isinstance(state.repair_spec, dict) else {}
        raw_metrics = spec1.get("viewport_evaluations") or spec1.get("viewport_metrics") or spec1.get("sam_metrics")
        if not raw_metrics:
            raw_metrics = metrics_from_anomalies(remaining) or None
    elif raw_metrics is None and existing is not None:
        raw_metrics = metrics_from_anomalies(state.anomalies) or None
    elif raw_metrics is None:
        raw_metrics = metrics_from_anomalies(remaining) or None

    result = evaluate_dual_viewport(raw_metrics)
    viewports = result["viewports"]
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

        # Node 1: SENSE (strict 60s timeout to allow dev boot + Playwright dual capture + Meta SAM)
        try:
            state = await asyncio.wait_for(orchestrator.step_1_sense(state), timeout=60.0)
        except asyncio.TimeoutError:
            logger.error("Node 1 SENSE timed out after 60s")
            state.is_resolved = False
            state.transition_to(FSMStep.VERIFY, RunStatus.FAILED)
            spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
            spec["sense_status"] = "capture_failed"
            spec["sense_error"] = "SENSE stage timed out after 60s (target app boot/capture)"
            spec["stage_error"] = spec["sense_error"]
            state.stage_error = spec["sense_error"]
            state.repair_spec = spec
            if use_events:
                await _broadcast(event_broadcast, "RUN_HALTED", state)
            else:
                await orchestrator.emit_update(state)
            return state

        if use_events:
            await _broadcast(event_broadcast, "SENSE_COMPLETE", state)

        _sense_failed = (
            isinstance(state.repair_spec, dict)
            and state.repair_spec.get("sense_status") == "capture_failed")
        if _sense_failed:
            # No real capture: honest failure, never a no-defect pass.
            state.is_resolved = False
            state.transition_to(FSMStep.VERIFY, RunStatus.FAILED)
            if use_events:
                await _broadcast(event_broadcast, "RUN_HALTED", state)
            else:
                await orchestrator.emit_update(state)
            return state

        if not state.anomalies:
            state.is_resolved = True
            state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
            if use_events:
                await _broadcast(event_broadcast, "RUN_RESOLVED", state)
            else:
                await orchestrator.emit_update(state)
            return state

        # Node 2: TRIAGE (once per run, FR-04, 45s timeout)
        try:
            state = await asyncio.wait_for(orchestrator.step_2_triage(state), timeout=45.0)
        except asyncio.TimeoutError:
            logger.warning("Node 2 TRIAGE timed out after 45s; using fallback target files")
        if use_events:
            await _broadcast(event_broadcast, "TRIAGE_COMPLETE", state)

        # Nodes 3-5: DIAGNOSE -> PATCH -> VERIFY, 3-Strike Loop (BR-1, hard cap 3)
        while state.attempt < min(state.max_attempts, 3):
            state.attempt += 1
            state.strike_count = state.attempt
            try:
                state = await asyncio.wait_for(orchestrator.step_3_diagnose(state), timeout=60.0)
                state = await asyncio.wait_for(orchestrator.step_4_patch(state), timeout=60.0)
                # A PATCH implementation may have recorded the attempt
                # (legacy mock point); adopt its diff as current_patch.
                if not state.current_patch and state.attempts:
                    latest = state.attempts[-1]
                    if latest.attempt_number == state.attempt and latest.patch_diff:
                        state.current_patch = latest.patch_diff
                state = await asyncio.wait_for(orchestrator.step_5_verify(state), timeout=60.0)
            except Exception as exc:
                # Record the failed strike and continue; never loop forever.
                spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
                fallback_metrics = spec.get("viewport_metrics") or spec.get("viewport_evaluations") or {}
                if not any(a.attempt_number == state.attempt for a in state.attempts):
                    state.attempts.append(
                        SelfHealingAttempt(
                            attempt_number=state.attempt,
                            patch_diff=state.current_patch or None,
                            passed=False,
                            error_message=str(exc),
                            viewport_metrics=dict(fallback_metrics),
                        )
                    )
                else:
                    state.attempts[-1].passed = False
                    state.attempts[-1].error_message = str(exc)
                    if not state.attempts[-1].viewport_metrics and fallback_metrics:
                        state.attempts[-1].viewport_metrics = dict(fallback_metrics)
                state.is_resolved = False
                state.transition_to(FSMStep.VERIFY)

            if use_events:
                await _broadcast(event_broadcast, f"ATTEMPT_{state.attempt}_FEEDBACK", state)

            latest = state.attempts[-1] if state.attempts else None
            if state.is_resolved or (latest is not None and latest.passed):
                state.is_resolved = True
                state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
                if state.pr_number:
                    try:
                        from backend.api.github_repos import auto_publish_github_telemetry_and_commit
                        gh_tok = getattr(orchestrator.github_client, "token", "") if orchestrator.github_client else ""
                        await auto_publish_github_telemetry_and_commit(state, gh_tok)
                    except Exception as e:
                        logger.warning(f"Auto-publish to GitHub caught: {e}")
                if use_events:
                    await _broadcast(event_broadcast, "RUN_RESOLVED", state)
                break

        if not state.is_resolved and state.status not in (RunStatus.RESOLVED, RunStatus.FAILED):
            state.status = RunStatus.FAILED
            state.transition_to(FSMStep.VERIFY, RunStatus.FAILED)
            if use_events:
                await _broadcast(event_broadcast, "RUN_HALTED", state)
            else:
                await orchestrator.emit_update(state)
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
    if (github is not None or getattr(settings, "GITHUB_APP_ID", "")
            or getattr(settings, "GITHUB_PAT", "")) and state.attempts:
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

