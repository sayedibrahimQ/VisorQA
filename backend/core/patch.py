"""Deterministic Unified Diff safety for Node 4 (PATCH).

Model output is untrusted input. This module (1) normalizes raw or
Markdown-fenced model responses into one unambiguous Unified Diff --
removing only outer fences and safely separable prose, never patch
content, (2) parses it strictly (header paths must agree, hunk line
counts must match exactly; nothing is silently repaired), (3)
authorizes it against the Node 2/Node 3 contract (exactly the
RepairSpec target, never protected ``src/components/ui/*`` paths
(BR-2), no new/deleted files, no traversal), (4) enforces BR-4 and
no-hide policy on the patch text, and (5) applies it to the exact
original content with context verification. Application writes are
atomic (temp file + ``os.replace``); a failed post-write read-back
restores the original bytes. The repository ships no diff library, so
the parser lives here with narrow, git-compatible semantics.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from backend.core.state import AgentState
from backend.core.diagnose import authorized_targets, resolve_repo_root
from backend.core.triage import is_protected_path, normalize_path

MAX_DIFF_CHARS = 64_000
MAX_CHANGED_LINES = 300
MAX_HUNKS = 50
# BR-4 (mirrors orchestrator.BANNED_PATCH_PATTERNS; Node 5 re-checks).
BANNED_PATCH_PATTERNS: List[str] = [
    "!important", "z-index: 9999", "z-index:9999", "z-[9999]"]
_HIDE_PATTERNS = (
    r"display\s*:\s*none",
    r"visibility\s*:\s*hidden",
    r"(class|classname)\s*=\s*(\{`|\")?[^\">`]*\bhidden\b",
)

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_START_RE = re.compile(r"^(diff --git |--- (a/|/dev/null))")
_FENCE_OPEN_RE = re.compile(r"^```\s*(diff|patch)?\s*$")
_METADATA_PREFIXES = (
    "index ", "old mode", "new mode", "new file mode", "deleted file mode",
    "similarity index", "dissimilarity index", "rename from", "rename to",
    "copy from", "copy to", "Binary files",
)
_LANGUAGES = {".tsx": "TypeScript React (TSX)", ".ts": "TypeScript",
              ".jsx": "JavaScript React (JSX)", ".js": "JavaScript",
              ".css": "CSS", ".scss": "SCSS", ".py": "Python",
              ".json": "JSON", ".html": "HTML"}


class PatchValidationError(ValueError):
    """Model patch failed normalization/parsing/authorization/policy."""


@dataclass
class ParsedHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: List[str] = field(default_factory=list)
    new_lines: List[str] = field(default_factory=list)
    old_eof_no_newline: bool = False
    new_eof_no_newline: bool = False


@dataclass
class ParsedPatch:
    path: str  # repo-relative target path (old == new enforced)
    hunks: List[ParsedHunk] = field(default_factory=list)

    @property
    def changed_lines(self) -> int:
        return sum(h.old_count + h.new_count for h in self.hunks)


@dataclass
class FileSnapshot:
    path: str
    data: bytes
    text: str
    sha256: str
    language: str


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _hunk_counts(line: str) -> Optional[Tuple[int, int]]:
    match = _HUNK_RE.match(line)
    if not match:
        return None
    old_count = int(match.group(2)) if match.group(2) is not None else 1
    new_count = int(match.group(4)) if match.group(4) is not None else 1
    return old_count, new_count


def _scan_block(lines: List[str], start: int) -> int:
    """End index (inclusive) of the diff block beginning at ``start``.

    Hunk-aware: body lines are consumed by header counts exactly.
    Raises on structurally impossible content (never repairs counts).
    """
    i = start
    last = start - 1
    need_old: Optional[int] = None
    need_new = 0
    while i < len(lines):
        line = lines[i]
        if need_old is None:  # header zone
            if _DIFF_START_RE.match(line) or line.startswith("+++ ") \
                    or line.startswith(_METADATA_PREFIXES):
                last = i
                i += 1
                continue
            counts = _hunk_counts(line)
            if counts is not None:
                need_old, need_new = counts
                last = i
                i += 1
                continue
            break
        # hunk body
        if need_old == 0 and need_new == 0:
            need_old = None
            continue  # reprocess this line in the header zone
        if line.startswith("\\"):
            last = i
            i += 1
            continue
        if line == "" or line[0] == " ":
            need_old -= 1
            need_new -= 1
        elif line[0] == "-":
            need_old -= 1
        elif line[0] == "+":
            need_new -= 1
        else:
            raise PatchValidationError(
                "malformed hunk body: unexpected line in diff")
        if need_old < 0 or need_new < 0:
            raise PatchValidationError("hunk line counts exceed header")
        last = i
        i += 1
    if need_old is not None and (need_old or need_new):
        raise PatchValidationError("incomplete hunk: line counts unmet")
    return last


def _fenced_blocks(lines: List[str]) -> List[Tuple[int, int]]:
    """(content_start, content_end_exclusive) for each fenced block."""
    blocks: List[Tuple[int, int]] = []
    open_at: Optional[int] = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if open_at is None and _FENCE_OPEN_RE.match(stripped):
            open_at = idx
        elif open_at is not None and stripped == "```":
            blocks.append((open_at + 1, idx))
            open_at = None
    return blocks


def normalize_diff(raw: Optional[str]) -> str:
    """Extract one unambiguous Unified Diff from a model response.

    Accepts raw diffs and diffs wrapped in ``diff``/``patch``/unlabelled
    fences. Prose outside the diff is removed only when the diff block
    is uniquely identifiable; multiple or conflicting diffs raise.
    Every patch-content line inside the block is preserved verbatim.
    """
    if not raw or not raw.strip():
        raise PatchValidationError("empty patch response")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_DIFF_CHARS * 4:  # generous pre-cap; real cap below
        raise PatchValidationError("patch response too large")
    lines = text.split("\n")

    blocks = _fenced_blocks(lines)
    diff_blocks = [
        (s, e) for s, e in blocks
        if any(_DIFF_START_RE.match(lines[j]) for j in range(s, e))]
    if len(diff_blocks) > 1:
        raise PatchValidationError("multiple diffs in response (ambiguous)")
    if diff_blocks:
        start_scope, end_scope = diff_blocks[0]
        scope = lines[start_scope:end_scope]
        outside = lines[:start_scope] + lines[end_scope:]
        _reject_diff_markers(outside, "content outside the fenced diff")
    else:
        scope = lines
        outside = []

    start = next((j for j, line in enumerate(scope)
                  if _DIFF_START_RE.match(line)), None)
    if start is None:
        raise PatchValidationError("no unified diff found in response")
    end = _scan_block(scope, start)
    rest = scope[:start] + scope[end + 1:]
    _reject_diff_markers(rest, "multiple or conflicting diffs in response")
    normalized = "\n".join(scope[start:end + 1]) + "\n"
    if len(normalized) > MAX_DIFF_CHARS:
        raise PatchValidationError("patch exceeds size limit")
    return normalized


def _reject_diff_markers(lines: List[str], message: str) -> None:
    for line in lines:
        if _DIFF_START_RE.match(line) or _HUNK_RE.match(line):
            raise PatchValidationError(message)


# ---------------------------------------------------------------------------
# Strict parsing
# ---------------------------------------------------------------------------

def _header_path(token: str) -> str:
    token = token.strip().split("\t")[0].strip()
    if token == "/dev/null":
        return token
    if token.startswith(("a/", "b/")):
        return token[2:]
    return token


def parse_unified_diff(text: str) -> List[ParsedPatch]:
    """Parse normalized diff text strictly. Headers/counts must agree."""
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    patches: List[ParsedPatch] = []
    i = 0
    total_hunks = 0
    while i < len(lines):
        git_paths: List[str] = []
        if lines[i].startswith("diff --git "):
            parts = lines[i].split()
            if len(parts) >= 4:
                git_paths = [_header_path(parts[2]), _header_path(parts[3])]
            i += 1
            while i < len(lines) and \
                    lines[i].startswith(_METADATA_PREFIXES):
                i += 1
        if i >= len(lines) or not lines[i].startswith("--- "):
            raise PatchValidationError("missing --- header in diff")
        old_path = _header_path(lines[i][4:])
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise PatchValidationError("missing +++ header in diff")
        new_path = _header_path(lines[i][4:])
        i += 1
        if git_paths and git_paths != [old_path, new_path]:
            raise PatchValidationError("conflicting diff file headers")
        if old_path == "/dev/null" or new_path == "/dev/null":
            raise PatchValidationError(
                "file creation/deletion is not authorized")
        if old_path != new_path:
            raise PatchValidationError("conflicting diff file headers")
        patch = ParsedPatch(path=new_path)
        while i < len(lines):
            counts = _hunk_counts(lines[i])
            if counts is None:
                break
            total_hunks += 1
            if total_hunks > MAX_HUNKS:
                raise PatchValidationError("patch exceeds hunk limit")
            match = _HUNK_RE.match(lines[i])
            assert match is not None
            hunk = ParsedHunk(
                old_start=int(match.group(1)), old_count=counts[0],
                new_start=int(match.group(3)), new_count=counts[1])
            i += 1
            need_old, need_new = counts
            prev_kind: Optional[str] = None
            while need_old > 0 or need_new > 0:
                if i >= len(lines):
                    raise PatchValidationError(
                        "incomplete hunk: line counts unmet")
                line = lines[i]
                if line.startswith("\\"):
                    if prev_kind in (" ", "-"):
                        hunk.old_eof_no_newline = True
                    if prev_kind in (" ", "+"):
                        hunk.new_eof_no_newline = True
                    i += 1
                    continue
                if line == "" or line[0] == " ":
                    hunk.old_lines.append(line[1:] if line else "")
                    hunk.new_lines.append(line[1:] if line else "")
                    need_old -= 1
                    need_new -= 1
                    prev_kind = " "
                elif line[0] == "-":
                    hunk.old_lines.append(line[1:])
                    need_old -= 1
                    prev_kind = "-"
                elif line[0] == "+":
                    hunk.new_lines.append(line[1:])
                    need_new -= 1
                    prev_kind = "+"
                else:
                    raise PatchValidationError(
                        "malformed hunk body: unexpected line in diff")
                if need_old < 0 or need_new < 0:
                    raise PatchValidationError(
                        "hunk line counts exceed header")
                i += 1
            # "\ No newline" may follow the final counted line.
            while i < len(lines) and lines[i].startswith("\\"):
                if prev_kind in (" ", "-"):
                    hunk.old_eof_no_newline = True
                if prev_kind in (" ", "+"):
                    hunk.new_eof_no_newline = True
                i += 1
            patch.hunks.append(hunk)
        if not patch.hunks:
            raise PatchValidationError("diff file section has no hunks")
        patches.append(patch)
    if not patches:
        raise PatchValidationError("empty diff")
    return patches


def authorize_patch(
    patches: List[ParsedPatch],
    state: AgentState,
    expected_target: str,
) -> ParsedPatch:
    """Allow exactly the RepairSpec target; enforce BR-2 and policy."""
    if len(patches) != 1:
        raise PatchValidationError(
            "multi-file diffs are not authorized for one RepairSpec")
    patch = patches[0]
    target = normalize_path(patch.path)
    if target is None:
        raise PatchValidationError("patch path is malformed or traverses")
    if patch.path != target and patch.path.replace("\\", "/") != target:
        raise PatchValidationError("patch path is not repo-relative")
    if is_protected_path(target):
        raise PatchValidationError("patch targets protected shared UI (BR-2)")
    if target not in authorized_targets(state):
        raise PatchValidationError("patch file not authorized by Node 2")
    if target != normalize_path(expected_target):
        raise PatchValidationError(
            "patch file does not match the RepairSpec target_file")
    if patch.changed_lines > MAX_CHANGED_LINES:
        raise PatchValidationError("patch exceeds changed-line limit")
    if not any(h.new_lines != h.old_lines for h in patch.hunks):
        raise PatchValidationError("patch makes no changes")
    return patch


def check_patch_policy(normalized: str) -> None:
    """BR-4 banned patterns (whole-text, mirroring Node 5) + no-hide."""
    lowered = normalized.lower()
    for pattern in BANNED_PATCH_PATTERNS:
        if pattern in lowered:
            raise PatchValidationError(
                f"patch contains banned pattern: {pattern}")
    for line in normalized.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            body = line[1:].lower()
            for pattern in _HIDE_PATTERNS:
                if re.search(pattern, body):
                    raise PatchValidationError(
                        "patch hides content (display/visibility removal)")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def _split_text(text: str) -> Tuple[List[str], bool, str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    body = text.replace("\r\n", "\n") if newline == "\r\n" else text
    if body == "":
        return [], False, newline
    ends = body.endswith("\n")
    lines = body.split("\n")
    if ends:
        lines.pop()
    return lines, ends, newline


def _join_text(lines: List[str], ends: bool, newline: str) -> str:
    text = "\n".join(lines)
    if ends and lines:
        text += "\n"
    return text.replace("\n", newline) if newline == "\r\n" else text


def apply_parsed_patch(original: str, patch: ParsedPatch) -> str:
    """Apply to the exact original; context must match (stale-safe)."""
    lines, ends_nl, newline = _split_text(original)
    offset = 0
    touched_eof = False
    new_eof_no_newline = False
    for hunk in patch.hunks:
        if hunk.old_count == 0:
            start = hunk.old_start + offset
        else:
            start = hunk.old_start - 1 + offset
        if start < 0 or start + hunk.old_count > len(lines):
            raise PatchValidationError("hunk outside file bounds (stale?)")
        actual = lines[start:start + hunk.old_count]
        if actual != hunk.old_lines:
            raise PatchValidationError(
                "hunk context does not match original (stale source)")
        at_eof = start + hunk.old_count == len(lines)
        lines[start:start + hunk.old_count] = hunk.new_lines
        if at_eof:
            touched_eof = True
            new_eof_no_newline = hunk.new_eof_no_newline
        offset += len(hunk.new_lines) - hunk.old_count
    final_ends = (not new_eof_no_newline) if touched_eof else ends_nl
    return _join_text(lines, final_ends, newline)


# ---------------------------------------------------------------------------
# Repository access
# ---------------------------------------------------------------------------

def repo_file_path(state: AgentState, rel_path: str) -> Path:
    """Contained absolute path for an authorized file; raises if unsafe."""
    root = resolve_repo_root(
        state.repair_spec if isinstance(state.repair_spec, dict) else {})
    if root is None:
        raise PatchValidationError("repository checkout unavailable")
    candidate = (root / rel_path).resolve()
    if root not in candidate.parents:
        raise PatchValidationError("path escapes repository root")
    return candidate


def read_snapshot(state: AgentState, rel_path: str) -> FileSnapshot:
    """Exact original bytes/text/hash for one authorized file."""
    path = repo_file_path(state, rel_path)
    if not path.is_file():
        raise PatchValidationError(f"target file missing: {rel_path}")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchValidationError(f"target file is not UTF-8: {rel_path}")
    suffix = Path(rel_path).suffix.lower()
    return FileSnapshot(
        path=rel_path, data=data, text=text,
        sha256=hashlib.sha256(data).hexdigest(),
        language=_LANGUAGES.get(suffix, "text"))


def tailwind_config_excerpt(state: AgentState) -> Optional[str]:
    """Project Tailwind config excerpt (breakpoint conventions)."""
    root = resolve_repo_root(
        state.repair_spec if isinstance(state.repair_spec, dict) else {})
    if root is None:
        return None
    for name in ("tailwind.config.js", "tailwind.config.ts",
                 "tailwind.config.mjs", "tailwind.config.cjs"):
        candidate = root / name
        if candidate.is_file():
            return candidate.read_text(
                encoding="utf-8", errors="replace")[:1200]
    return None


def write_atomically(path: Path, data: bytes) -> None:
    """Temp-file + os.replace in the same directory; mode preserved."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".visorqa-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_and_commit(
    state: AgentState, patch: ParsedPatch, snapshot: FileSnapshot,
) -> str:
    """Verify freshness, apply, write atomically, verify, roll back."""
    path = repo_file_path(state, patch.path)
    current = path.read_bytes() if path.is_file() else b""
    if hashlib.sha256(current).hexdigest() != snapshot.sha256:
        raise PatchValidationError(
            "stale source: file changed since it was read; aborting")
    new_text = apply_parsed_patch(snapshot.text, patch)
    new_data = new_text.encode("utf-8")
    write_atomically(path, new_data)
    if path.read_bytes() != new_data:  # post-write verification
        write_atomically(path, snapshot.data)  # restore original bytes
        raise PatchValidationError(
            "post-write verification failed; original restored")
    return new_text
