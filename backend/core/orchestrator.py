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
    from backend.adapters.sandbox_runner import ModalSandboxRunner

    return ModalSandboxRunner()


def _default_sam() -> Any:
    from backend.adapters.muse_clients import SAM31Client

    return SAM31Client()


def _default_spark() -> Any:
    from backend.adapters.muse_clients import MuseSparkClient

    return MuseSparkClient()


def _default_wonder() -> Any:
    from backend.adapters.muse_clients import MuseWonderClient

    return MuseWonderClient()


def _default_code() -> Any:
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
    if state.anomalies and not resense:
        return state

    sandbox = sandbox_runner or _default_sandbox()
    sam = sam_client or _default_sam()
    detected: List[Anomaly] = []

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
        try:
            screenshot = await sandbox.capture_screenshot(vp_width, vp_height)
            masks = await sam.generate_component_masks(screenshot, boxes) or []
        except Exception:
            masks = []

        viewport_label = f"{vp_width}px"
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
    state.anomalies = detected
    return state


# ---------------------------------------------------------------------------
# Node 2 - TRIAGE (Muse Spark, LCA + protected-file filter, BR-2)
# ---------------------------------------------------------------------------

async def triage_files_muse_spark(
    state: AgentState, spark_client: Any = None
) -> AgentState:
    """Map anomalies to 1-2 parent layout files; never target protected UI."""
    state.transition_to(FSMStep.TRIAGE)
    if not state.anomalies:
        state.target_files = [f for f in state.target_files if not _is_protected(f)]
        return state

    spark = spark_client or _default_spark()
    candidates: List[str] = list(state.target_files)
    try:
        result: Dict[str, Any] = await spark.triage_anomalies(
            [a.model_dump(mode="json") for a in state.anomalies],
            state.repair_spec.get("lca_dom", {}) if isinstance(state.repair_spec, dict) else {},
        ) or {}
    except Exception:
        result = {}
    if isinstance(result, dict):
        raw = result.get("target_files") or result.get("candidate_files") or []
        if isinstance(raw, str):
            raw = [raw]
        candidates.extend(str(f) for f in raw)
        single = result.get("candidate_source_file") or result.get("candidate_file")
        if single:
            candidates.append(str(single))
        # Preserve LCA / summary context for DIAGNOSE without clobbering spec.
        merged = dict(state.repair_spec)
        for key in ("lca_element_id", "lca_dom", "triage_summary"):
            if result.get(key) is not None:
                merged[key] = result[key]
        state.repair_spec = merged

    # De-duplicate, preserve order, enforce BR-2.
    seen: set[str] = set()
    target_files: List[str] = []
    for path in candidates:
        if path and path not in seen and not _is_protected(path):
            seen.add(path)
            target_files.append(path)
    state.target_files = target_files
    return state


# ---------------------------------------------------------------------------
# Node 3 - DIAGNOSE (Muse Wonder, structured repair_spec only, TC-4)
# ---------------------------------------------------------------------------

async def diagnose_muse_wonder(
    state: AgentState, wonder_client: Any = None
) -> AgentState:
    """Produce a structured JSON ``repair_spec``; never writes raw code."""
    state.transition_to(FSMStep.DIAGNOSE)
    wonder = wonder_client or _default_wonder()
    triage_info: Dict[str, Any] = {
        "target_files": list(state.target_files),
        "lca_element_id": state.repair_spec.get("lca_element_id"),
        "lca_dom": state.repair_spec.get("lca_dom", {}),
        "anomalies": [a.model_dump(mode="json") for a in state.anomalies],
        "attempt": state.attempt,
    }
    computed_styles: Dict[str, Any] = dict(state.repair_spec.get("computed_styles", {}))
    try:
        result: Dict[str, Any] = await wonder.diagnose_defect(
            b"", computed_styles, triage_info
        ) or {}
    except Exception as exc:  # deterministic fallback spec
        result = {"diagnosis": f"diagnosis unavailable: {exc}", "recommended_fix": ""}

    spec: Dict[str, Any] = dict(result.get("repair_spec", result)) if isinstance(result, dict) else {}
    first = state.anomalies[0] if state.anomalies else None
    merged: Dict[str, Any] = dict(state.repair_spec)
    merged.update(spec)
    if "root_cause" not in merged:
        merged["root_cause"] = merged.pop("diagnosis", "") or (
            f"{first.defect_type.value} on {first.element_id}" if first else ""
        )
    if "fix_strategy" not in merged:
        merged["fix_strategy"] = merged.pop("recommended_fix", "")
    merged.setdefault("defect_type", first.defect_type.value if first else "OCCLUSION")
    merged["target_files"] = list(state.target_files)
    merged["attempt"] = state.attempt
    state.repair_spec = merged
    return state


# ---------------------------------------------------------------------------
# Node 4 - PATCH (Muse Code unified diff + BR-4 guard)
# ---------------------------------------------------------------------------

async def patch_with_muse_code(
    state: AgentState, code_client: Any = None
) -> AgentState:
    """Synthesise ``current_patch`` from ``repair_spec`` (no protected files)."""
    state.transition_to(FSMStep.PATCH)
    safe_targets = [f for f in state.target_files if not _is_protected(f)]
    if state.target_files and not safe_targets:
        state.current_patch = ""
        spec = dict(state.repair_spec)
        spec["patch_skipped"] = "BR-2: all target files are protected"
        state.repair_spec = spec
        return state

    code = code_client or _default_code()
    file_path = safe_targets[0] if safe_targets else ""
    source_code = str(state.repair_spec.get("source_code", ""))
    try:
        patch = await code.generate_patch(source_code, dict(state.repair_spec), file_path)
    except Exception as exc:
        patch = ""
        spec = dict(state.repair_spec)
        spec["patch_error"] = str(exc)
        state.repair_spec = spec
    state.current_patch = patch or ""
    return state


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
    """Re-evaluate after PATCH, update best patch, decide resolution.

    Resolution (FR-07/BR-3): V_r >= 0.98, IoU == 0, bleed <= 2px and
    no remaining anomalies. A ``SelfHealingAttempt`` already recorded
    by PATCH (the class-level mock point) is honoured; otherwise the
    sandbox/SAM adapters are re-sensed deterministically.
    """
    state.transition_to(FSMStep.VERIFY)
    attempt_no = state.attempt or (len(state.attempts) + 1)
    state.attempt = attempt_no
    state.strike_count = attempt_no

    existing = next(
        (a for a in reversed(state.attempts) if a.attempt_number == attempt_no), None
    )
    if existing is None and state.attempts and state.attempts[-1].post_score is None:
        # PATCH recorded an unverified attempt with its own numbering
        # (legacy step_4_patch contract); adopt and renumber it.
        existing = state.attempts[-1]
        existing.attempt_number = attempt_no
    error_message: Optional[str] = existing.error_message if existing else None

    if existing is not None and existing.verified_vr is not None:
        vr_values = [float(existing.verified_vr)]
        iou_values = [float(existing.verified_iou or 0.0)]
        bleed_values = [float(existing.verified_bleed_px or 0.0)]
        remaining = [] if existing.passed else list(state.anomalies)
        passed = (
            vr_values[0] >= 0.98
            and iou_values[0] == 0.0
            and bleed_values[0] <= 2.0
            and (existing.passed or not remaining)
        )
        if existing.passed:
            passed = vr_values[0] >= 0.98 and iou_values[0] == 0.0 and bleed_values[0] <= 2.0
    elif existing is not None:
        passed = bool(existing.passed)
        if passed:
            vr_values, iou_values, bleed_values = [1.0], [0.0], [0.0]
            remaining = []
        else:
            vr_values, iou_values, bleed_values = _anomaly_metrics(state.anomalies)
            if not vr_values:
                vr_values = [0.0]
            remaining = list(state.anomalies)
    else:
        before = list(state.anomalies)
        sense_fn = globals().get("sense_with_playwright_and_sam", sense_with_playwright_and_sam)
        try:
            await _call_node(
                sense_fn, state, sandbox_runner=sandbox_runner, sam_client=sam_client, resense=True
            )
            # _call_node's node transition moved us to SENSE; restore VERIFY.
            state.transition_to(FSMStep.VERIFY)
        except Exception:
            state.anomalies = before
        remaining = list(state.anomalies)
        if remaining:
            vr_values, iou_values, bleed_values = _anomaly_metrics(remaining)
        else:
            vr_values, iou_values, bleed_values = [1.0], [0.0], [0.0]
        passed = (
            not remaining
            and vr_values[0] >= 0.98
            and max(iou_values) == 0.0
            and max(bleed_values) <= 2.0
        ) if remaining else True

    score = compute_health_score(vr_values, iou_values, bleed_values)

    if not is_patch_safe(state.current_patch):
        passed = False
        error_message = "BR-4: patch contains banned CSS (!important / z-index: 9999)"
    elif state.target_files and not [f for f in state.target_files if not _is_protected(f)]:
        if state.repair_spec.get("patch_skipped"):
            passed = False
            error_message = str(state.repair_spec["patch_skipped"])

    # Snapshot the best-scoring safe patch across all attempts (TDS SS3).
    if is_patch_safe(state.current_patch):
        state.update_best(score)

    if existing is not None:
        existing.patch_diff = state.current_patch
        existing.verified_vr = vr_values[0] if vr_values else 1.0
        existing.verified_iou = max(iou_values) if iou_values else 0.0
        existing.verified_bleed_px = max(bleed_values) if bleed_values else 0.0
        existing.post_score = score
        existing.passed = passed
        existing.error_message = error_message
        record = existing
    else:
        record = SelfHealingAttempt(
            attempt_number=attempt_no,
            patch_diff=state.current_patch,
            verified_vr=vr_values[0] if vr_values else 1.0,
            verified_iou=max(iou_values) if iou_values else 0.0,
            verified_bleed_px=max(bleed_values) if bleed_values else 0.0,
            post_score=score,
            passed=passed,
            error_message=error_message,
        )
        state.attempts.append(record)

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
        state = await _call_node(fn, state, code_client=self.code_client)
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

        # Nodes 3-5: DIAGNOSE -> PATCH -> VERIFY, 3-Strike Loop (BR-1)
        while state.attempt < state.max_attempts:
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

    # Optional GitHub side-effects, only when a client was injected.
    github = orchestrator.github_client
    if github is not None:
        try:
            if state.is_resolved and state.best_patch:
                await github.commit_patch(
                    state.repo_full_name or state.repo_name,
                    state.branch,
                    state.target_files[0] if state.target_files else "",
                    state.best_patch,
                )
            elif not state.is_resolved:
                await github.post_pr_review(
                    state.repo_full_name or state.repo_name,
                    state.pr_number,
                    state.run_id,
                    {"status": state.status.value, "strikes": state.attempt,
                     "best_score": state.best_score, "best_patch": state.best_patch},
                )
        except Exception:
            pass
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


