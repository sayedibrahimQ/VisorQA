"""Unified-Diff validation/application shared by both sandbox backends.

Reuses Node 4's strict machinery in ``backend.core.patch`` (strict
parsing, BR-4/no-hide policy, stale context checks, atomic writes).
Authorization here is sandbox-scoped: every path must be repo-relative,
non-protected (BR-2), and -- when an authorized list is supplied -- on
it. Nothing is written until every file section has been validated and
applied in memory, so a rejected patch leaves the FS untouched.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

from backend.core.patch import (
    PatchValidationError,
    apply_parsed_patch,
    check_patch_policy,
    normalize_diff,
    parse_unified_diff,
    write_atomically,
)
from backend.core.triage import is_protected_path, normalize_path
from backend.sandbox.interface import PatchRejectedError, TimingMetrics


def validate_and_plan(
    patch_text: str, root: Path, authorized_files: Optional[List[str]],
) -> Tuple[List[Tuple[str, Path, bytes, bytes]], TimingMetrics]:
    """Return [(rel, path, old_bytes, new_bytes)] or raise PatchRejectedError."""
    started = time.perf_counter()
    timings = TimingMetrics()
    try:
        normalized = normalize_diff(patch_text)
        parsed = parse_unified_diff(normalized)
        check_patch_policy(normalized)
    except PatchValidationError as exc:
        raise PatchRejectedError(str(exc)) from exc
    authorized = None
    if authorized_files is not None:
        authorized = {n for n in (normalize_path(p) for p in authorized_files) if n}
    plan: List[Tuple[str, Path, bytes, bytes]] = []
    seen = set()
    for patch in parsed:
        rel = normalize_path(patch.path)
        if rel is None:
            raise PatchRejectedError(f"patch path is malformed or traverses: {patch.path!r}")
        if rel in seen:
            raise PatchRejectedError(f"duplicate file section in patch: {rel}")
        seen.add(rel)
        if is_protected_path(rel):
            raise PatchRejectedError(f"patch targets protected shared UI (BR-2): {rel}")
        if authorized is not None and rel not in authorized:
            raise PatchRejectedError(f"patch file not authorized for this sandbox: {rel}")
        candidate = (root / rel).resolve()
        if root.resolve() not in candidate.parents:
            raise PatchRejectedError(f"patch path escapes sandbox root: {rel}")
        if not candidate.is_file():
            raise PatchRejectedError(f"patch target missing in sandbox: {rel}")
        old = candidate.read_bytes()
        try:
            new_text = apply_parsed_patch(old.decode("utf-8"), patch)
        except (PatchValidationError, UnicodeDecodeError) as exc:
            raise PatchRejectedError(str(exc)) from exc
        plan.append((rel, candidate, old, new_text.encode("utf-8")))
    timings.patch_validation_ms = (time.perf_counter() - started) * 1000.0
    return plan, timings


def commit_plan(
    plan: List[Tuple[str, Path, bytes, bytes]], timings: TimingMetrics,
) -> List[str]:
    """Write a validated plan atomically per file; roll back all on failure."""
    started = time.perf_counter()
    written: List[Tuple[Path, bytes]] = []
    try:
        for _rel, path, old, new in plan:
            write_atomically(path, new)
            written.append((path, old))
            if path.read_bytes() != new:
                raise PatchRejectedError(f"post-write verification failed: {path}")
    except Exception as exc:
        for path, old in reversed(written):
            try:
                write_atomically(path, old)
            except OSError:
                pass
        if isinstance(exc, PatchRejectedError):
            raise
        raise PatchRejectedError(f"patch write failed, rolled back: {exc}") from exc
    timings.patch_apply_ms = (time.perf_counter() - started) * 1000.0
    return [rel for rel, _p, _o, _n in plan]


def extract_patch_paths(patch_text: str) -> List[str]:
    """Best-effort target list for status reporting (never raises)."""
    try:
        return [p.path for p in parse_unified_diff(normalize_diff(patch_text))]
    except Exception:
        return []
