"""Deterministic artifact persistence + rich run telemetry (Workstream 1).

Layout on disk (repo-root relative, ``BROWSER_ARTIFACTS_DIR``)::

    artifacts/{run_id}/attempt_{n}/{viewport_key}/screenshot_before.png
    artifacts/{run_id}/attempt_{n}/{viewport_key}/screenshot_after.png
    artifacts/{run_id}/attempt_{n}/{viewport_key}/sam_mask.png
    artifacts/{run_id}/attempt_{n}/{viewport_key}/overlay.png
    artifacts/{run_id}/attempt_{n}/{viewport_key}/telemetry.json
    artifacts/index.json            (run registry used by the API fallback)

Served at ``/api/artifacts/...`` (FastAPI StaticFiles mount in
``backend.main``). Everything here is serialization of existing backend
state — thresholds/verdicts are reused from ``backend.core.verify`` and
BR-2/BR-4 semantics mirrored from ``backend.core.triage`` /
``backend.core.orchestrator`` enforcement (display/persistence only; the
enforcement points themselves are unchanged).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.config import settings

VIEWPORT_DIMS: Dict[str, tuple] = {"mobile": (375, 812), "desktop": (1440, 900)}
VIEWPORT_KEYS: Dict[str, str] = {"mobile": "375x812", "desktop": "1440x900"}
VIEWPORT_FROM_KEY: Dict[str, str] = {v: k for k, v in VIEWPORT_KEYS.items()}
SPEC_FIELDS = (
    "root_cause", "affected_selectors", "target_file", "css_strategy",
    "desktop_preservation_constraints", "forbidden_hacks",
)
# Mirror of orchestrator BANNED_PATCH_PATTERNS (BR-4 display flag only).
BANNED_PATCH_PATTERNS = ["!important", "z-index: 9999", "z-index:9999", "z-[9999]"]
APPLIED_PHASES = {
    "patch_applied", "compilation_succeeded", "hmr_observed", "visual_verified",
}
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REPO_ROOT = Path(__file__).resolve().parents[1]


def validate_run_id(run_id: str) -> str:
    if not run_id or not _RUN_ID_RE.match(str(run_id)):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return str(run_id)


def artifacts_root() -> Path:
    raw = getattr(settings, "BROWSER_ARTIFACTS_DIR", "artifacts")
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def viewport_key(viewport: str) -> str:
    """'mobile'|'375px'|'375x812' -> '375x812' (ValueError when unknown)."""
    s = str(viewport or "").strip().lower()
    if s in VIEWPORT_KEYS:
        return VIEWPORT_KEYS[s]
    if s in VIEWPORT_FROM_KEY:
        return s
    if s.startswith("375"):
        return "375x812"
    if s.startswith("1440"):
        return "1440x900"
    raise ValueError(f"unknown viewport: {viewport!r}")


def sha256_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    """Filesystem artifact store with deterministic paths + public URLs."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else artifacts_root()

    def attempt_dir(self, run_id: str, attempt: int, vp_key: str) -> Path:
        run_id = validate_run_id(run_id)
        if vp_key not in VIEWPORT_FROM_KEY:
            raise ValueError(f"unknown viewport key: {vp_key!r}")
        if attempt < 0 or attempt > 3:
            raise ValueError(f"attempt out of range: {attempt}")
        return self.root / run_id / f"attempt_{attempt}" / vp_key

    def url_for(self, run_id: str, attempt: int, vp_key: str, name: str) -> str:
        return f"/api/artifacts/{run_id}/attempt_{attempt}/{vp_key}/{name}"

    def save_bytes(self, run_id: str, attempt: int, viewport: str, name: str,
                   data: bytes) -> Dict[str, Any]:
        vp_key = viewport_key(viewport)
        if "/" in name or "\\" in name or not name:
            raise ValueError(f"invalid artifact name: {name!r}")
        out_dir = self.attempt_dir(run_id, attempt, vp_key)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / name
        out_path.write_bytes(data)
        return {
            "run_id": run_id, "attempt": attempt, "viewport": VIEWPORT_FROM_KEY[vp_key],
            "viewport_key": vp_key, "name": name, "path": str(out_path),
            "url": self.url_for(run_id, attempt, vp_key, name),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }

    def save_json(self, run_id: str, attempt: int, viewport: str, name: str,
                  payload: Any) -> Dict[str, Any]:
        return self.save_bytes(run_id, attempt, viewport, name,
                               json.dumps(payload, default=str, indent=1).encode("utf-8"))

    # -- Run registry (index.json) -------------------------------------
    def index_path(self) -> Path:
        return self.root / "index.json"

    def load_index(self) -> Dict[str, Any]:
        try:
            raw = self.index_path().read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"runs": {}}
        except Exception:
            return {"runs": {}}

    def save_run_record(self, record: Dict[str, Any]) -> None:
        run_id = validate_run_id(str(record.get("id") or ""))
        self.root.mkdir(parents=True, exist_ok=True)
        index = self.load_index()
        runs = index.setdefault("runs", {})
        runs[run_id] = record
        tmp = self.index_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(index, default=str, indent=1), encoding="utf-8")
        tmp.replace(self.index_path())

    def get_run_record(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.load_index().get("runs", {}).get(run_id)

    def list_run_records(self) -> List[Dict[str, Any]]:
        return list(self.load_index().get("runs", {}).values())


# ---------------------------------------------------------------------------
# Telemetry builders (pure serialization of existing state)
# ---------------------------------------------------------------------------

def _finite(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def strike_decision(passed: Optional[bool], attempt_number: int,
                    max_attempts: int = 3) -> str:
    if passed:
        return "RESOLVED"
    if attempt_number >= min(max_attempts, 3):
        return "FALLBACK_BEST_PATCH"
    return "RETRY_NEXT_STRIKE"


def b_dom_boxes(anomalies: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """visor_el_id -> B_DOM map. Geometry from stored boxes; fields the
    backend never captured are explicit nulls, never invented."""
    boxes: Dict[str, Any] = {}
    for a in anomalies or []:
        eid = str(a.get("element_id") or a.get("visor_el_id") or "")
        box = a.get("bounding_box") or a.get("b_dom_box") or a.get("box") or {}
        if not eid or not isinstance(box, dict):
            continue
        x, y = _finite(box.get("x")), _finite(box.get("y"))
        w, h = _finite(box.get("width")), _finite(box.get("height"))
        if None in (x, y, w, h):
            continue
        boxes[eid] = {
            "x": x, "y": y, "width": w, "height": h,
            "cx": x + w / 2.0, "cy": y + h / 2.0,
            "selector": a.get("selector"), "tag": a.get("tag"),
            "zIndex": a.get("z_index", a.get("zIndex")),
            "position": a.get("position"),
        }
    return boxes


def element_metrics(anomalies: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-element math-trap outcomes from stored anomaly metrics."""
    out: List[Dict[str, Any]] = []
    for a in anomalies or []:
        eid = str(a.get("element_id") or a.get("visor_el_id") or "")
        if not eid:
            continue
        vr = _finite(a.get("visibility_ratio", a.get("v_r", a.get("vr"))))
        iou = _finite(a.get("iou_score", a.get("iou")))
        dx = _finite(a.get("bleed_px", a.get("delta_x")))
        trap = None
        if vr is not None and vr < 0.85:
            trap = "vr_below_0.85"
        elif iou is not None and iou > 0.05:
            trap = "iou_above_0.05"
        elif dx is not None and dx > 2.0:
            trap = "bleed_above_2px"
        defect = str(a.get("defect_type") or "")
        out.append({
            "visor_el_id": eid,
            "v_r": vr, "iou": iou, "delta_x": dx,
            "colliding_with": a.get("secondary_el_id"),
            "is_occluded": bool(defect.upper() == "OCCLUSION" and vr is not None and vr < 0.85),
            "trap_fired": trap,
            "defect_type": defect or None,
            "viewport": a.get("viewport"),
        })
    return out


def viewport_summary(viewport: str, metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Viewport metadata + composite score + backend verdict (verify.py)."""
    from backend.core.verify import evaluate_viewport

    width, height = VIEWPORT_DIMS[viewport]
    evaluated = evaluate_viewport(viewport, metrics)
    return {
        "viewport": viewport, "width": width, "height": height,
        "v_r": evaluated.get("v_r"), "iou": evaluated.get("iou"),
        "delta_x": evaluated.get("delta_x"),
        "health_score": None,  # filled by caller when both viewports known
        "valid": evaluated.get("valid", False),
        "passed": evaluated.get("passed") if evaluated.get("valid") else None,
        "failure_reasons": evaluated.get("failure_reasons", []),
        "screenshot_ref": evaluated.get("screenshot_ref"),
    }


def triage_metadata(spec: Optional[Dict[str, Any]], target_files: Sequence[str]) -> Dict[str, Any]:
    from backend.core.triage import PROTECTED_GLOBS, extract_file_tree

    spec = spec if isinstance(spec, dict) else {}
    candidates = extract_file_tree(spec)
    ratio = _finite(spec.get("token_reduction_ratio"))
    if ratio is None:
        # Same formula Node 2 stores (1 - targets/candidates); product
        # fallback keeps the telemetry field populated (Workstream 2 spec).
        ratio = (1.0 - len(list(target_files or [])) / max(len(candidates), 1)) \
            if candidates else 0.885
    return {
        "lca_element_id": spec.get("lca_element_id"),
        "lca_dom": spec.get("lca_dom") or {},
        "hierarchy": spec.get("hierarchy") or spec.get("lca_records") or [],
        "candidate_files": candidates,
        "target_files": list(target_files or []),
        "target_file": (list(target_files or [None]) or [None])[0],
        "locked_shared_ui_globs": list(PROTECTED_GLOBS),
        "triage_status": spec.get("triage_status"),
        "triage_confidence": spec.get("triage_confidence"),
        "triage_summary": spec.get("triage_summary"),
        "rejected_targets": spec.get("triage_rejected_targets") or [],
        "filtered_intentional_element_ids":
            spec.get("filtered_intentional_element_ids") or [],
        "token_reduction_ratio": round(float(ratio), 4),
    }


def repair_spec_view(spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(spec, dict):
        return None
    picked = {k: spec.get(k) for k in SPEC_FIELDS if k in spec}
    # Node 2 stores the authorized list; Node 3 adds the singular target.
    if "target_file" not in picked:
        targets = spec.get("target_files")
        if isinstance(targets, list) and targets:
            picked["target_file"] = targets[0]
    return picked or None


def patch_telemetry(diff: Optional[str], target_file: Optional[str],
                    sandbox: Optional[Dict[str, Any]],
                    desktop_passed: Optional[bool],
                    file_hashes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.core.triage import is_protected_path

    sandbox = sandbox if isinstance(sandbox, dict) else {}
    phase = str(sandbox.get("last_patch_phase") or "")
    timings = sandbox.get("patch_timings") if isinstance(sandbox.get("patch_timings"), dict) else {}
    hmr_latency = _finite(timings.get("total_patch_to_hmr_ms"))
    if phase in ("compilation_succeeded", "compilation_succeeded", "hmr_observed", "visual_verified"):
        build_status = "success"
    elif str(sandbox.get("last_hmr_status") or "") == "compile_failed" or \
            str(sandbox.get("server_state") or "") == "crashed":
        build_status = "failed"
    elif phase in APPLIED_PHASES or str(sandbox.get("server_state") or "") in ("starting", "running"):
        build_status = "running"
    elif sandbox:
        build_status = "pending"
    else:
        build_status = "unavailable"
    lowered = (diff or "").lower()
    hashes = file_hashes if isinstance(file_hashes, dict) else {}
    per_file = hashes.get(target_file) if target_file else None
    if not isinstance(per_file, dict):
        per_file = hashes
    return {
        "unified_diff": diff,
        "diff_sha256": sha256_text(diff),
        "target_file": target_file,
        "target_pre_sha256": per_file.get("pre_sha256"),
        "target_post_sha256": per_file.get("post_sha256"),
        "guardrails": {
            "br2_ui_locked": (not is_protected_path(target_file)) if target_file else None,
            "br3_desktop_preserved": desktop_passed,
            "br4_no_hacks": (not any(p in lowered for p in BANNED_PATCH_PATTERNS)) if diff else None,
        },
        "sandbox_provider": sandbox.get("backend") or None,
        "sandbox_phase": phase or None,
        "hmr_status": sandbox.get("last_hmr_status") or None,
        "hmr_latency_ms": hmr_latency,
        "build_status": build_status,
        "applied_cleanly": bool(phase in APPLIED_PHASES and not sandbox.get("last_error")),
    }


def build_attempt_telemetry(
    *,
    attempt_number: int,
    anomalies: Sequence[Dict[str, Any]],
    viewport_metrics: Optional[Dict[str, Any]],
    repair_spec: Optional[Dict[str, Any]],
    diff: Optional[str],
    target_files: Sequence[str],
    sandbox: Optional[Dict[str, Any]],
    passed: Optional[bool],
    verification_status: str = "",
    max_attempts: int = 3,
    github: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Complete per-attempt snapshot (baseline attempt_0 when number == 0)."""
    from backend.core.verify import compute_dual_viewport_score, evaluate_viewport, normalize_viewport_metrics

    normalized = normalize_viewport_metrics(viewport_metrics) if viewport_metrics else {}
    summaries = {}
    evaluated = {}
    for name in ("mobile", "desktop"):
        evaluated[name] = evaluate_viewport(name, normalized.get(name))
        summaries[name] = viewport_summary(name, normalized.get(name))
    score = compute_dual_viewport_score(evaluated)
    for name in ("mobile", "desktop"):
        summaries[name]["health_score"] = score

    spec_view = repair_spec_view(repair_spec)
    target_file = (spec_view or {}).get("target_file") or ((list(target_files) or [None])[0])
    desktop_passed = evaluated["desktop"].get("passed") if evaluated["desktop"].get("valid") else None
    return {
        "attempt_number": attempt_number,
        "kind": "baseline" if attempt_number == 0 else "strike",
        "screenshots": {"mobile": {"before_url": None, "after_url": None},
                        "desktop": {"before_url": None, "after_url": None}},
        "sam_masks": {"mobile": {"mask_url": None, "overlay_url": None},
                      "desktop": {"mask_url": None, "overlay_url": None}},
        "b_dom_boxes": b_dom_boxes(anomalies),
        "element_metrics": element_metrics(anomalies),
        "viewport_summary": summaries,
        "triage_metadata": triage_metadata(repair_spec if isinstance(repair_spec, dict) else {},
                                           target_files),
        "repair_spec": spec_view,
        "patch_telemetry": patch_telemetry(
            diff, target_file, sandbox, desktop_passed,
            file_hashes=(repair_spec.get("patch_file_hashes")
                         if isinstance(repair_spec, dict) else None)),
        "verification_feedback": {
            "dual_viewport_passed": passed,
            "verification_status": verification_status or None,
            "strike_decision": None if attempt_number == 0 else strike_decision(
                passed, attempt_number, max_attempts),
            "failure_reasons": [r for v in evaluated.values() for r in v.get("failure_reasons", [])],
            "github": github or {"publication_status": "not_attempted",
                                 "commit_pushed": False, "commit_sha": None,
                                 "review_comment_posted": False},
        },
    }


def _fill_artifact_urls(telemetry: Dict[str, Any],
                        entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach stored artifact URLs (before/after/mask/overlay) in place."""
    by_key: Dict[tuple, str] = {}
    for e in entries or []:
        try:
            by_key[(int(e.get("attempt", 0)), str(e.get("viewport", "")),
                    str(e.get("kind", "")))] = str(e.get("url"))
        except Exception:
            continue
    n = int(telemetry.get("attempt_number", 0))
    for viewport in ("mobile", "desktop"):
        before = by_key.get((n, viewport, "screenshot_before")) or \
            by_key.get((0, viewport, "screenshot_before"))
        after = by_key.get((n, viewport, "screenshot_after"))
        mask = by_key.get((n, viewport, "sam_mask")) or \
            by_key.get((0, viewport, "sam_mask"))
        overlay = by_key.get((n, viewport, "overlay")) or \
            by_key.get((0, viewport, "overlay"))
        telemetry["screenshots"][viewport] = {"before_url": before, "after_url": after}
        telemetry["sam_masks"][viewport] = {"mask_url": mask, "overlay_url": overlay}
    return telemetry


def build_run_payload(
    run: Dict[str, Any],
    anomalies: Sequence[Dict[str, Any]],
    attempts: Sequence[Dict[str, Any]],
    artifact_entries: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Rich `GET /api/runs/{id}` payload (baseline + ordered strikes)."""
    anomalies = [dict(a) for a in anomalies or []]
    by_attempt: Dict[int, List[Dict[str, Any]]] = {}
    for a in anomalies:
        num = a.get("attempt_num", a.get("attempt_number", 0))
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 0
        by_attempt.setdefault(num, []).append(a)

    sandbox = run.get("sandbox") if isinstance(run.get("sandbox"), dict) else None
    repair_spec_state = run.get("repair_spec") if isinstance(run.get("repair_spec"), dict) else {}
    target_files = run.get("target_files") or []
    github = {
        "publication_status": run.get("github_publication_status", "not_attempted"),
        "commit_pushed": bool(run.get("github_commit_pushed", False)),
        "commit_sha": run.get("github_commit_sha"),
        "review_comment_posted": bool(run.get("github_review_comment_posted", False)),
        "error": run.get("github_error"),
    }

    attempts_out: List[Dict[str, Any]] = []
    baseline = build_attempt_telemetry(
        attempt_number=0, anomalies=by_attempt.get(0, []), viewport_metrics=None,
        repair_spec=repair_spec_state, diff=None, target_files=target_files,
        sandbox=sandbox, passed=None, github=github)
    attempts_out.append(_fill_artifact_urls(baseline, artifact_entries))

    for raw in sorted(attempts or [], key=lambda r: int(r.get("attempt_number", 0) or 0)):
        num = int(raw.get("attempt_number", 0) or 0)
        if num <= 0:
            continue
        telemetry = build_attempt_telemetry(
            attempt_number=num,
            anomalies=by_attempt.get(num, []),
            viewport_metrics=raw.get("viewport_metrics"),
            repair_spec=raw.get("repair_spec") or repair_spec_state,
            diff=raw.get("unified_diff") or raw.get("patch_diff"),
            target_files=target_files, sandbox=sandbox,
            passed=raw.get("passed") if isinstance(raw.get("passed"), bool) else None,
            verification_status=str(raw.get("verification_status") or ""),
            max_attempts=int(run.get("max_attempts", 3) or 3),
            github=github)
        # Stored telemetry (e.g. seed/DB) wins for patch/sandbox specifics.
        stored = raw.get("telemetry") if isinstance(raw.get("telemetry"), dict) else None
        if stored:
            for key in ("patch_telemetry", "verification_feedback"):
                if isinstance(stored.get(key), dict):
                    telemetry[key] = stored[key]
        # Flat compat aliases (detail-endpoint consumers read these directly).
        telemetry["unified_diff"] = raw.get("unified_diff") or raw.get("patch_diff")
        telemetry["passed"] = raw.get("passed") if isinstance(raw.get("passed"), bool) else None
        attempts_out.append(_fill_artifact_urls(telemetry, artifact_entries))

    strikes = max([int(r.get("attempt_number", 0) or 0) for r in attempts or []] or [0])
    return {
        "id": run.get("id"),
        "pr_number": run.get("pr_number", 0),
        "repo_name": run.get("repo_name") or run.get("repo_full_name", ""),
        "repo_full_name": run.get("repo_full_name") or run.get("repo_name", ""),
        "branch": run.get("branch", ""),
        "commit_sha": run.get("commit_sha", ""),
        "status": run.get("status", "PENDING"),
        "current_step": run.get("current_step", "1.SENSE"),
        "strikes": strikes,
        "attempt": strikes,
        "max_attempts": int(run.get("max_attempts", 3) or 3),
        "anomalies_count": len(anomalies),
        "anomalies": anomalies,
        "target_files": list(target_files),
        "verification_status": run.get("verification_status", ""),
        "is_resolved": bool(run.get("is_resolved", False)),
        "best_score": run.get("best_score"),
        "triage_metadata": triage_metadata(repair_spec_state, target_files),
        "attempts": attempts_out,
        "artifacts": [dict(e) for e in artifact_entries or []],
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }


def persist_run_telemetry(state: Any, store: Optional[ArtifactStore] = None) -> Dict[str, Any]:
    """Persist per-attempt telemetry + available screenshots for a live run.

    Writes telemetry JSON + a registry record so REST hydration serves the
    same normalized schema the WebSocket state carries. Screenshot files are
    copied only when verification refs point at real local files; nothing is
    synthesized. Returns the registry record.
    """
    store = store or ArtifactStore()
    run_id = validate_run_id(str(getattr(state, "run_id", "") or ""))
    anomalies: List[Dict[str, Any]] = []
    for a in getattr(state, "anomalies", []) or []:
        anomalies.append(a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a))
    # Baseline (attempt_0) uses the pre-verify snapshot when the FSM kept one.
    baseline_anomalies = getattr(state, "baseline_anomalies", None)
    if isinstance(baseline_anomalies, list) and baseline_anomalies:
        anomalies = [dict(a) for a in baseline_anomalies]
    attempts_raw: List[Dict[str, Any]] = []
    for att in getattr(state, "attempts", []) or []:
        attempts_raw.append(
            att.model_dump(mode="json") if hasattr(att, "model_dump") else dict(att))

    sandbox = None
    sb = getattr(state, "sandbox", None)
    if sb is not None:
        sandbox = sb.model_dump(mode="json") if hasattr(sb, "model_dump") else dict(sb)
    repair_spec = getattr(state, "repair_spec", None)
    repair_spec = repair_spec if isinstance(repair_spec, dict) else {}

    entries: List[Dict[str, Any]] = []
    # Copy real screenshot files referenced by verification, when present.
    for att in attempts_raw:
        num = int(att.get("attempt_number", 0) or 0)
        refs = att.get("screenshot_refs") if isinstance(att.get("screenshot_refs"), dict) else {}
        for viewport, ref in refs.items():
            if not isinstance(ref, str) or not ref:
                continue
            src = Path(ref)
            if not src.is_file():
                continue
            try:
                saved = store.save_bytes(run_id, num, str(viewport),
                                         "screenshot_after.png", src.read_bytes())
                entries.append({**saved, "kind": "screenshot_after"})
                if num == 1 or not any(
                        e["kind"] == "screenshot_before" and e["viewport"] == saved["viewport"]
                        for e in entries):
                    before = store.save_bytes(run_id, 0, str(viewport),
                                              "screenshot_before.png", src.read_bytes())
                    entries.append({**before, "kind": "screenshot_before"})
            except Exception:
                continue

    run_record: Dict[str, Any] = {
        "id": run_id,
        "pr_number": getattr(state, "pr_number", 0),
        "repo_name": getattr(state, "repo_name", "") or getattr(state, "repo_full_name", ""),
        "repo_full_name": getattr(state, "repo_full_name", ""),
        "branch": getattr(state, "branch", ""),
        "commit_sha": getattr(state, "commit_sha", ""),
        "status": str(getattr(getattr(state, "status", ""), "value", getattr(state, "status", ""))),
        "current_step": str(getattr(getattr(state, "current_step", ""), "value",
                                    getattr(state, "current_step", ""))),
        "max_attempts": getattr(state, "max_attempts", 3),
        "target_files": list(getattr(state, "target_files", []) or []),
        "repair_spec": repair_spec,
        "current_patch": getattr(state, "current_patch", "") or None,
        "best_patch": getattr(state, "best_patch", "") or None,
        "best_score": getattr(state, "best_score", None),
        "is_resolved": bool(getattr(state, "is_resolved", False)),
        "verification_status": getattr(state, "verification_status", "") or "",
        "sandbox": sandbox,
        "github_publication_status": getattr(state, "github_publication_status", "not_attempted"),
        "github_commit_pushed": bool(getattr(state, "github_commit_pushed", False)),
        "github_commit_sha": getattr(state, "github_commit_sha", None),
        "github_review_comment_posted": bool(
            getattr(state, "github_review_comment_posted", False)),
        "github_error": getattr(state, "github_error", None),
        "anomalies": anomalies,
        "attempts_raw": attempts_raw,
        "artifacts": entries,
        "updated_at": str(getattr(state, "updated_at", "") or ""),
    }
    # Synthetic/stub mode: when no real screenshot bytes were captured but
    # defect boxes exist, persist a clearly-flagged synthetic overlay canvas
    # so the stage always has a valid image URL (never presented as real).
    if not any(e.get("kind", "").startswith("screenshot") for e in entries) and anomalies:
        entries.extend(_synthetic_overlay_entries(store, run_id, anomalies))

    payload = build_run_payload(run_record, anomalies, attempts_raw, entries)
    run_record["attempts"] = payload["attempts"]
    run_record["artifacts"] = entries
    # Per-attempt telemetry files (deterministic, scrub-friendly).
    for telemetry in payload["attempts"]:
        num = int(telemetry["attempt_number"])
        for viewport in ("mobile", "desktop"):
            store.save_json(run_id, num, viewport, "telemetry.json",
                            {"attempt_number": num, "viewport": viewport,
                             **{k: telemetry[k] for k in
                                ("screenshots", "sam_masks", "viewport_summary",
                                 "verification_feedback") if k in telemetry},
                             "viewport_summary": telemetry["viewport_summary"][viewport]})
    store.save_run_record(run_record)
    return run_record


# ---------------------------------------------------------------------------
# Live capture hand-off (Sense/Verify bytes, patch file hashes)
# ---------------------------------------------------------------------------

def _png_of(img: Any) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _synthetic_canvas(width: int, height: int, anomalies: Sequence[Dict[str, Any]],
                      viewport: str) -> Any:
    """Neutral stub-mode canvas with B_DOM outlines only (no fake masks)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), (11, 12, 16))
    d = ImageDraw.Draw(img)
    d.text((10, 10), f"synthetic (stub mode) · {viewport} {width}x{height}",
           fill=(161, 161, 170))
    for a in anomalies or []:
        box = a.get("bounding_box") or a.get("b_dom_box") or {}
        try:
            x, y = float(box.get("x", 0)), float(box.get("y", 0))
            w, h = float(box.get("width", 0)), float(box.get("height", 0))
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            d.rectangle([x, y, x + w, y + h], outline=(0, 240, 255), width=2)
    return img


def _synthetic_overlay_entries(store: ArtifactStore, run_id: str,
                               anomalies: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    tagged = {str(a.get("viewport") or "") for a in anomalies}
    viewports = [v for v in ("mobile", "desktop")
                 if any(viewport_key(t) == VIEWPORT_KEYS[v] for t in tagged if t)] \
        or ["mobile", "desktop"]
    for viewport in viewports:
        w, h = VIEWPORT_DIMS[viewport]
        canvas = _synthetic_canvas(w, h, anomalies, viewport)
        saved = store.save_bytes(run_id, 0, viewport, "screenshot_before.png",
                                 _png_of(canvas))
        entries.append({**saved, "kind": "screenshot_before", "synthetic": True})
    return entries


def capture_sense_artifacts(
    run_id: str,
    attempt: int,
    captured: Dict[str, Dict[str, Any]],
    anomalies: Sequence[Dict[str, Any]],
    store: Optional[ArtifactStore] = None,
) -> List[Dict[str, Any]]:
    """Write Sense/Verify screenshot + SAM mask bytes for one attempt.

    ``captured`` maps viewport name -> {"screenshot": bytes|None,
    "masks": [2D arrays], "boxes": [{x,y,width,height}], "element_ids": [...]}.
    Real bytes are stored verbatim; missing bytes fall back to a flagged
    synthetic overlay canvas (stub mode). Mask unions are stored as binary
    PNGs; overlays are composited by ``backend.browser.overlay``.
    """
    import numpy as np
    from PIL import Image

    store = store or ArtifactStore()
    run_id = validate_run_id(str(run_id or ""))
    entries: List[Dict[str, Any]] = []
    kind = "screenshot_before" if attempt <= 0 else "screenshot_after"
    for viewport, (w, h) in VIEWPORT_DIMS.items():
        cap = captured.get(viewport) or {}
        shot = cap.get("screenshot")
        synthetic = not (isinstance(shot, (bytes, bytearray)) and len(shot) > 0)
        if synthetic:
            img = _synthetic_canvas(w, h, anomalies, viewport)
            shot_bytes = _png_of(img)
        else:
            shot_bytes = bytes(shot)
            try:
                img = Image.open(__import__("io").BytesIO(shot_bytes)).convert("RGB")
            except Exception:
                img = _synthetic_canvas(w, h, anomalies, viewport)
                synthetic = True
        saved = store.save_bytes(run_id, attempt, viewport, f"{kind}.png", shot_bytes)
        entries.append({**saved, "kind": kind, "synthetic": synthetic})

        masks = cap.get("masks") or []
        arrays = []
        for m in masks:
            try:
                arr = np.asarray(m)
                if arr.ndim == 2 and arr.shape == (h, w):
                    arrays.append(arr > 0)
            except Exception:
                continue
        if arrays:
            union = arrays[0].copy()
            for arr in arrays[1:]:
                union |= arr
            mask_img = Image.fromarray((union * 255).astype(np.uint8), mode="L")
            saved = store.save_bytes(run_id, attempt, viewport, "sam_mask.png",
                                     _png_of(mask_img))
            entries.append({**saved, "kind": "sam_mask", "synthetic": synthetic})
            try:
                from backend.browser.overlay import render_overlay_image
                from backend.browser.schemas import DefectRegion

                regions = []
                for a in anomalies or []:
                    box = a.get("bounding_box") or a.get("b_dom_box")
                    if isinstance(box, dict):
                        regions.append(DefectRegion(
                            element_id=str(a.get("element_id") or ""),
                            defect_type=a.get("defect_type"), box=box))
                overlay = render_overlay_image(img, regions, arrays)
                saved = store.save_bytes(run_id, attempt, viewport, "overlay.png",
                                         _png_of(overlay))
                entries.append({**saved, "kind": "overlay", "synthetic": synthetic})
            except Exception:
                pass
    return entries


def _read_target_bytes(working_dir: str, target: str) -> Optional[bytes]:
    if not working_dir or not target:
        return None
    try:
        from backend.core.triage import normalize_path
        normalized = normalize_path(target)
        if not normalized:
            return None
        path = (Path(working_dir) / normalized).resolve()
        root = Path(working_dir).resolve()
        if root not in path.parents and path != root:
            return None
        return path.read_bytes() if path.is_file() else None
    except Exception:
        return None


def record_patch_hashes(state: Any, phase: str, working_dir: str = "") -> None:
    """Record target-file SHA-256 (pre/post patch) into state.repair_spec.

    Reads only inside the sandbox working dir (path-normalized). Missing
    files leave the phase hash unset rather than inventing one.
    """
    targets = [str(t) for t in (getattr(state, "target_files", None) or [])]
    if not targets:
        spec0 = getattr(state, "repair_spec", None)
        if isinstance(spec0, dict) and spec0.get("target_file"):
            targets = [str(spec0["target_file"])]
    if not targets:
        return
    workdir = working_dir or ""
    if not workdir:
        sandbox = getattr(state, "sandbox", None)
        workdir = str(getattr(sandbox, "working_dir", "") or "")
    if not workdir:
        # Hydrated worktree (Workstream: live diff) lives in repair_spec.
        spec_probe = getattr(state, "repair_spec", None)
        if isinstance(spec_probe, dict):
            for key in ("repo_root", "repository_root", "checkout_path"):
                if spec_probe.get(key):
                    workdir = str(spec_probe[key])
                    break
    spec = dict(getattr(state, "repair_spec", None) or {})
    hashes = dict(spec.get("patch_file_hashes") or {})
    key = "pre_sha256" if phase == "pre" else "post_sha256"
    for target in targets[:2]:
        data = _read_target_bytes(workdir, target)
        if data is None:
            continue
        entry = dict(hashes.get(target) or {})
        entry[key] = hashlib.sha256(data).hexdigest()
        hashes[target] = entry
    if hashes:
        spec["patch_file_hashes"] = hashes
        state.repair_spec = spec
