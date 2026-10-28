"""Deterministic BR-2 enforcement for Node 2 (Muse Spark triage).

The model proposes; this module disposes. Regardless of model
confidence: protected ``src/components/ui/*`` primitives are never
direct fix targets, fabricated/traversal paths are rejected, targets
must exist in the supplied repository tree (when one is supplied), and
intentional overlaps are filtered only on strong multi-signal evidence.
"""
from __future__ import annotations

import fnmatch
import json
import posixpath
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.core.state import (
    AgentState,
    RejectedTarget,
    TriageCandidate,
    TriageResponse,
)

PROTECTED_GLOBS: List[str] = ["src/components/ui/*", "*/components/ui/*"]
MIN_CONFIDENCE = 0.35
_MAX_CONTEXT_CHARS = 12000


def normalize_path(raw: Any) -> Optional[str]:
    """Normalize a repo-relative POSIX path; None when malformed/unsafe."""
    if not raw or not isinstance(raw, str):
        return None
    p = raw.strip().replace("\\", "/")
    if not p or p.startswith("/") or p.startswith("~") or "\x00" in p:
        return None
    if len(p) >= 2 and p[1] == ":":  # windows drive
        return None
    # Resolve "." and ".." segment by segment; escaping the repo root
    # (a ".." with nothing to pop) is traversal and rejected.
    stack: List[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not stack:
                return None
            stack.pop()
        else:
            stack.append(seg)
    normalized = posixpath.normpath("/".join(stack)) if stack else ""
    if normalized in (".", "") or normalized.startswith("../"):
        return None
    return normalized


def is_protected_path(path: str) -> bool:
    normalized = normalize_path(path) or path
    return any(fnmatch.fnmatch(normalized, g) for g in PROTECTED_GLOBS)


def extract_file_tree(repair_spec: Dict[str, Any]) -> List[str]:
    """Repository file tree from state, in any of its stored shapes."""
    if not isinstance(repair_spec, dict):
        return []
    raw = None
    for key in ("repository_files", "file_tree", "repo_files",
                "repository_tree", "files"):
        if repair_spec.get(key):
            raw = repair_spec[key]
            break
    out: List[str] = []

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, str):
            p = normalize_path(node)
            if p:
                out.append(p)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in ("files", "paths") and isinstance(value, list):
                    for item in value:
                        walk(item, prefix)
                elif isinstance(value, (dict, list)):
                    walk(value, f"{prefix}{key}/")
                else:
                    walk(str(key), prefix)
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix)

    walk(raw)
    return sorted(set(out))[:2000]


def _descriptor_text(desc: Dict[str, Any]) -> str:
    parts = [
        str(desc.get("tag") or ""), str(desc.get("id") or ""),
        " ".join(desc.get("classes") or []),
        str(desc.get("data-testid") or desc.get("data_testid") or ""),
        str(desc.get("react_hint") or ""),
        str(desc.get("text_hint") or ""),
        str(desc.get("role") or ""),
    ]
    return " ".join(parts).lower()


def _hierarchy_index(hierarchy: Sequence[Any]) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """visor_el_id -> (descriptor, css signature) from hierarchy records."""
    descriptors: Dict[str, Dict[str, Any]] = {}
    css: Dict[str, Dict[str, Any]] = {}
    for rec in hierarchy or []:
        if not isinstance(rec, dict):
            rec = rec.model_dump(by_alias=True) if hasattr(rec, "model_dump") else {}
        for node in (rec.get("element"), rec.get("sibling"), rec.get("lca")):
            if isinstance(node, dict):
                vid = node.get("data-visor-el-id") or node.get("visor_el_id")
                if vid:
                    descriptors.setdefault(str(vid), node)
        for vid, sig in (rec.get("element_css_signatures") or {}).items():
            if isinstance(sig, dict):
                css.setdefault(str(vid), sig)
        for node in rec.get("ancestor_chain") or []:
            if isinstance(node, dict):
                vid = node.get("data-visor-el-id") or node.get("visor_el_id")
                if vid:
                    descriptors.setdefault(str(vid), node)
    return descriptors, css


def detect_intentional_overlaps(
    anomalies: Sequence[Any],
    hierarchy: Sequence[Any],
    repair_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Element IDs whose collision is intentional, with the reason.

    Strong evidence is required -- all of: (1) badge/avatar semantics on
    the two sides, (2) the badge is absolutely/fixed positioned in its
    computed CSS signature, and (3) the badge is nested inside the
    avatar (or its container) in the hierarchy. Nesting or intersection
    alone never qualifies. Explicit ``intentional_overlaps`` metadata in
    ``repair_spec`` also qualifies on its own.
    """
    repair_spec = repair_spec or {}
    intentional: Dict[str, str] = {}
    for entry in repair_spec.get("intentional_overlaps") or []:
        ids = entry.get("element_ids") if isinstance(entry, dict) else entry
        for vid in ids or []:
            intentional[str(vid)] = "explicit intentional_overlaps metadata"

    descriptors, css = _hierarchy_index(hierarchy or [])
    # Ancestor map: visor id -> set of ancestor descriptor texts.
    ancestors: Dict[str, List[Dict[str, Any]]] = {}
    for rec in hierarchy or []:
        if not isinstance(rec, dict):
            rec = rec.model_dump(by_alias=True) if hasattr(rec, "model_dump") else {}
        if rec.get("relationship") == "element_ancestry":
            ids = rec.get("element_ids") or []
            if ids:
                ancestors[str(ids[0])] = [
                    n for n in (rec.get("ancestor_chain") or [])
                    if isinstance(n, dict)]

    def is_badge(vid: str) -> bool:
        d = descriptors.get(vid)
        return bool(d and "badge" in _descriptor_text(d))

    def is_avatar(vid: str) -> bool:
        d = descriptors.get(vid)
        return bool(d and "avatar" in _descriptor_text(d))

    for anomaly in anomalies or []:
        if isinstance(anomaly, dict):
            eid = str(anomaly.get("element_id") or anomaly.get("visor_el_id") or "")
            secondary = anomaly.get("secondary_el_id")
            defect = str(anomaly.get("defect_type") or "")
        else:
            eid = str(getattr(anomaly, "element_id", "") or "")
            secondary = getattr(anomaly, "secondary_el_id", None)
            defect = getattr(getattr(anomaly, "defect_type", ""), "value", "") or ""
        if defect and "COLLISION" not in str(defect).upper():
            continue
        pair = [eid, str(secondary)] if secondary else [eid]
        badge = next((v for v in pair if is_badge(v)), None)
        avatar = next((v for v in pair if is_avatar(v)), None)
        if not badge or not avatar or badge == avatar:
            continue
        position = str((css.get(badge) or {}).get("position") or "")
        if position not in ("absolute", "fixed"):
            continue
        chain_texts = [_descriptor_text(n) for n in ancestors.get(badge, [])]
        nested = any("avatar" in t for t in chain_texts)
        if not nested:
            continue
        intentional[badge] = (
            "badge-over-avatar: badge semantics + position "
            f"{position} + nested inside avatar container")
        intentional[avatar] = intentional[badge]
    return intentional


def build_triage_context(state: AgentState) -> Dict[str, Any]:
    """Bounded model context: defects, LCA hierarchy, CSS, file tree."""
    spec = state.repair_spec if isinstance(state.repair_spec, dict) else {}
    hierarchy = spec.get("hierarchy") or spec.get("lca_records") or []
    context: Dict[str, Any] = {
        "anomalies": [a.model_dump(mode="json") for a in state.anomalies],
        "lca_dom": spec.get("lca_dom", {}),
        "lca_element_id": spec.get("lca_element_id"),
        "hierarchy": hierarchy,
        "computed_styles": spec.get("computed_styles")
        or spec.get("computed_css") or {},
        "repository_files": extract_file_tree(spec),
        "existing_target_files": list(state.target_files),
        "viewport_diagnostics": {
            k: spec[k] for k in ("viewport_evaluations", "overlays",
                                 "collision_overlay", "health")
            if k in spec
        },
    }
    # Bound the serialized context; the file tree is the bulkiest part.
    text = json.dumps(context, default=str)
    if len(text) > _MAX_CONTEXT_CHARS:
        context["repository_files"] = context["repository_files"][:200]
        context["hierarchy"] = context["hierarchy"][:20]
        context["context_truncated"] = True
    return context


def enforce_triage_response(
    response: TriageResponse,
    repo_tree: Sequence[str] = (),
    actionable_element_ids: Optional[Set[str]] = None,
    all_element_ids: Optional[Set[str]] = None,
    require_tree: bool = False,
) -> TriageResponse:
    """Apply BR-2 deterministically to a validated model response.

    When ``require_tree`` is set (live model path), an empty repository
    tree rejects every candidate: unverified paths are never confirmed
    as fix targets. The legacy stub path leaves it unset to preserve
    its tested offline behavior.
    """
    out = response.model_copy(deep=True)
    rejected: List[RejectedTarget] = list(out.rejected_targets)
    tree = {p for p in (normalize_path(f) for f in repo_tree or []) if p}

    if all_element_ids is not None and actionable_element_ids is not None \
            and not actionable_element_ids and all_element_ids:
        for path in out.target_files:
            rejected.append(RejectedTarget(
                path=path, reason="intentional_overlap_filtered"))
        out.target_files = []
        out.status = "no_actionable_defects"
        out.rejected_targets = rejected
        return out

    pool: List[TriageCandidate] = []
    shared_evidence = "; ".join(out.evidence)
    for path in out.target_files:
        pool.append(TriageCandidate(path=path, confidence=out.confidence,
                                    evidence=shared_evidence, kind="direct"))
    if out.candidate_source_file:
        pool.append(TriageCandidate(path=out.candidate_source_file,
                                    confidence=out.confidence,
                                    evidence=shared_evidence, kind="direct"))
    pool.extend(out.candidates)

    accepted: List[str] = []
    redirected_from: List[str] = []
    for cand in pool:
        if len(accepted) >= 2:
            break
        normalized = normalize_path(cand.path)
        if normalized is None:
            reason = "path_traversal" if cand.path and ".." in str(cand.path) \
                else "malformed_path"
            rejected.append(RejectedTarget(path=str(cand.path), reason=reason))
            continue
        if normalized in accepted:
            continue
        if is_protected_path(normalized):
            rejected.append(RejectedTarget(
                path=normalized, reason="protected_shared_ui"))
            redirected_from.append(normalized)
            continue
        if (tree and normalized not in tree) or \
                (require_tree and not tree):
            rejected.append(RejectedTarget(
                path=normalized, reason="not_in_repository_tree"))
            continue
        confidence = cand.confidence if cand.confidence is not None \
            else out.confidence
        if confidence < MIN_CONFIDENCE:
            rejected.append(RejectedTarget(
                path=normalized, reason="low_confidence"))
            continue
        evidence = (cand.evidence or "").strip()
        if not evidence and not redirected_from:
            # Direct targets need evidence; a redirect alternative is
            # itself grounded by the protected file it replaces plus
            # its tree membership, recorded in rejected_targets.
            rejected.append(RejectedTarget(
                path=normalized, reason="insufficient_evidence"))
            continue
        accepted.append(normalized)

    out.target_files = accepted
    out.rejected_targets = rejected
    if response.status == "error":
        out.status = "error"  # never upgrade a failure to a verdict
    elif accepted:
        out.status = "resolved"
        if redirected_from and not out.triage_summary:
            out.triage_summary = (
                f"Redirected from protected {redirected_from[0]} to "
                f"consuming layout/component {accepted[0]}")
    else:
        out.status = "unresolved"
        out.confidence = min(out.confidence, MIN_CONFIDENCE)
    return out
