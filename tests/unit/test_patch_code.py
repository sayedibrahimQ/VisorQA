"""Tests for Node 4 PATCH: Muse Code diff synthesis + safe application.

Mocked model responses only; no live endpoint or credentials. Desktop
preservation at the pixel level belongs to Node 5 re-sensing and the
visual suites -- here it is enforced as prompt content, diff policy,
and single-line-scope assertions, not claimed as visual proof.
"""
import asyncio
import hashlib
from pathlib import Path

import pytest

from backend.adapters.code_client import (
    CodeResponseError,
    MuseCodePatchClient,
    build_patch_messages,
)
from backend.config import settings
from backend.core.orchestrator import (
    patch_muse_code_and_apply,
    verify_with_sam,
)
from backend.core.patch import (
    PatchValidationError,
    apply_parsed_patch,
    authorize_patch,
    normalize_diff,
    parse_unified_diff,
)
from backend.core.state import AgentState, Anomaly, DefectType

TARGET = "src/components/PromoBanner.tsx"
UI_TARGET = "src/components/ui/button.tsx"

ORIGINAL = (
    'import React from "react";\n'
    "\n"
    "export function PromoBanner() {\n"
    "  return (\n"
    '    <div className="fixed top-0 z-50 promo-banner">\n'
    "      <span>Sale ends soon</span>\n"
    "    </div>\n"
    "  );\n"
    "}\n"
)
EXPECTED = ORIGINAL.replace(
    'className="fixed top-0 z-50 promo-banner"',
    'className="sticky top-0 z-10 promo-banner sm:fixed"')

GOOD_DIFF = (
    f"--- a/{TARGET}\n"
    f"+++ b/{TARGET}\n"
    "@@ -3,5 +3,5 @@\n"
    " export function PromoBanner() {\n"
    "   return (\n"
    '-    <div className="fixed top-0 z-50 promo-banner">\n'
    '+    <div className="sticky top-0 z-10 promo-banner sm:fixed">\n'
    "       <span>Sale ends soon</span>\n"
    "     </div>\n"
)

TRIAGE_AND_DIAGNOSIS = {
    "triage_status": "resolved",
    "triage_summary": "Promo banner overlaps the checkout CTA",
    "filtered_intentional_element_ids": ["badge-el"],
    "triage_rejected_targets": [
        {"path": UI_TARGET, "reason": "protected_shared_ui"}],
    "computed_styles": {"#promo-banner": {"position": "fixed"}},
    "root_cause": "PromoBanner is fixed without a stacking context",
    "affected_selectors": ["#promo-banner"],
    "target_file": TARGET,
    "css_strategy": "Make the banner sticky inside its hero container",
    "desktop_preservation_constraints": [
        "Desktop 1440px hero keeps banner height and offset"],
    "forbidden_hacks": ["!important"],
    "diagnose_status": "resolved",
}


def make_state(tmp_path, spec_over=None, content=ORIGINAL):
    target_path = tmp_path / TARGET
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content)
    spec = dict(TRIAGE_AND_DIAGNOSIS)
    spec.update({
        "repo_root": str(tmp_path),
        "repository_files": [TARGET, "src/app/page.tsx", UI_TARGET],
    })
    spec.update(spec_over or {})
    return AgentState(
        run_id="run-patch-1",
        repo_full_name="org/repo", pr_number=1, branch="fix/x", attempt=1,
        anomalies=[Anomaly(
            element_id="cta-el", defect_type=DefectType.OCCLUSION,
            visibility_ratio=0.45, iou_score=0.16, bleed_px=37.0,
            viewport="375px")],
        target_files=[TARGET],
        repair_spec=spec,
    )


class FakeCode:
    """New-contract client mock: generate_diff(context) -> raw text."""

    def __init__(self, response="", exc=None, on_call=None):
        self.response = response
        self.exc = exc
        self.on_call = on_call
        self.contexts = []

    async def generate_diff(self, context):
        self.contexts.append(context)
        if self.on_call:
            self.on_call(context)
        if self.exc:
            raise self.exc
        return self.response


# 1. Prompt construction -----------------------------------------------------------------
def test_prompt_construction_from_repair_spec(tmp_path):
    state = make_state(tmp_path)
    context = {
        "repair_spec": {k: state.repair_spec[k] for k in (
            "root_cause", "affected_selectors", "target_file",
            "css_strategy", "desktop_preservation_constraints",
            "forbidden_hacks")},
        "target_file": TARGET,
        "defect": {"element_id": "cta-el", "viewport": "mobile",
                   "metrics": {"V_r": 0.45, "IoU": 0.16,
                               "Delta_x_px": 37.0}},
        "tailwind_config": "screens: {sm: '640px', MARKER_TW: 1}",
        "feedback": {"available": True, "attempt_number": 1,
                     "error": "desktop V_r dropped to 0.74"},
        "files": [{"path": TARGET, "status": "ready",
                   "language": "TypeScript React (TSX)",
                   "sha256": "abc123", "content": ORIGINAL}],
    }
    messages = build_patch_messages(context)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "EXACTLY one Unified Diff" in system
    assert "1440px" in system and "src/components/ui/*" in system
    assert "PromoBanner is fixed without a stacking context" in user
    assert ORIGINAL in user  # exact original content, verbatim
    assert TARGET in user and "MARKER_TW" in user  # project Tailwind
    assert "desktop V_r dropped to 0.74" in user  # regression evidence
    assert "Desktop 1440px hero keeps" in user


async def _run_node(tmp_path, code, spec_over=None):
    state = make_state(tmp_path, spec_over)
    out = await patch_muse_code_and_apply(state, code_client=code)
    return out, tmp_path / TARGET


# 2-3. Parsing, application, responsive scope ---------------------------------------------
def test_parse_and_apply_success():
    parsed = parse_unified_diff(normalize_diff(GOOD_DIFF))
    assert apply_parsed_patch(ORIGINAL, parsed[0]) == EXPECTED


def test_only_the_defect_line_changes():
    before = ORIGINAL.split("\n")
    after = EXPECTED.split("\n")
    assert len(before) == len(after)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert changed == [4]  # structural check only; pixels are Node 5's job
    assert "sm:fixed" in after[4]  # breakpoint-scoped, base desktop intact
    assert "sticky" in after[4]


def test_git_metadata_lines_tolerated():
    diff = (f"diff --git a/{TARGET} b/{TARGET}\n"
            "index 1234567..89abcde 100644\n" + GOOD_DIFF)
    parsed = parse_unified_diff(normalize_diff(diff))
    assert apply_parsed_patch(ORIGINAL, parsed[0]) == EXPECTED


# 4. Normalization: fences, prose, malformed input, content preservation --------------------
@pytest.mark.parametrize("wrapped", [
    GOOD_DIFF,
    "```diff\n" + GOOD_DIFF + "```\n",
    "```patch\n" + GOOD_DIFF + "```\n",
    "```\n" + GOOD_DIFF + "```\n",
    "\n\n   \n" + GOOD_DIFF + "\n\n",
    "Here is the minimal fix:\n" + GOOD_DIFF + "\nThis scopes the banner.\n",
    "Fix below.\n```diff\n" + GOOD_DIFF + "```\nDone.\n",
])
def test_normalization_accepts_identifiable_diffs(wrapped):
    assert normalize_diff(wrapped) == GOOD_DIFF


@pytest.mark.parametrize("bad", [
    "",
    "   \n",
    "I would change the class to sticky.",  # pure prose
    "```diff\nno diff here\n```\n",
    GOOD_DIFF.replace(f"+++ b/{TARGET}", "+++ b/src/other/File.tsx"),
    GOOD_DIFF.replace("@@ -3,5 +3,5 @@", "@@ -3,7 +3,7 @@"),  # bad counts
    GOOD_DIFF.replace("       <span>Sale ends soon</span>\n", ""),  # short hunk
    "```diff\n" + GOOD_DIFF + "```\n```diff\n" + GOOD_DIFF + "```\n",
])
def test_normalization_rejects_unsafe_responses(bad):
    with pytest.raises(PatchValidationError):
        parse_unified_diff(normalize_diff(bad))


def test_two_file_diff_rejected_at_authorization(tmp_path):
    state = make_state(tmp_path)
    two = GOOD_DIFF + GOOD_DIFF.replace(TARGET, "src/app/page.tsx")
    parsed = parse_unified_diff(normalize_diff(two))
    assert len(parsed) == 2
    with pytest.raises(PatchValidationError):
        authorize_patch(parsed, state, TARGET)


def test_added_deleted_content_lines_preserved():
    original = "a\n-b\nc\n"
    diff = ("--- a/src/components/PromoBanner.tsx\n"
            "+++ b/src/components/PromoBanner.tsx\n"
            "@@ -1,3 +1,3 @@\n a\n--b\n++b\n c\n")
    parsed = parse_unified_diff(normalize_diff(diff))
    assert apply_parsed_patch(original, parsed[0]) == "a\n+b\nc\n"


# 5. Authorization at the node ----------------------------------------------------------------
@pytest.mark.parametrize("evil_diff", [
    GOOD_DIFF.replace(TARGET, UI_TARGET),                       # protected
    GOOD_DIFF.replace(TARGET, "src/app/page.tsx"),              # not spec target
    GOOD_DIFF.replace(TARGET, "../etc/passwd"),                 # traversal
    GOOD_DIFF.replace("a/src/components/PromoBanner.tsx",
                      "/etc/passwd").replace(
                      "b/src/components/PromoBanner.tsx", "/etc/passwd"),
    GOOD_DIFF.replace("fixed top-0 z-50", "fixed top-0 z-[9999]"),  # BR-4
    GOOD_DIFF.replace("sticky top-0 z-10 promo-banner sm:fixed",
                      "hidden promo-banner"),                   # hides content
])
async def test_node_rejects_unauthorized_or_unsafe_diffs(tmp_path, evil_diff):
    out, path = await _run_node(tmp_path, FakeCode(response=evil_diff))
    assert out.repair_spec["patch_status"] == "error"
    assert out.current_patch == ""
    assert path.read_text() == ORIGINAL


async def test_node_rejects_missing_or_unresolved_spec(tmp_path):
    out, path = await _run_node(
        tmp_path, FakeCode(response=GOOD_DIFF),
        spec_over={"diagnose_status": "error"})
    assert out.repair_spec["patch_status"] == "error"
    assert path.read_text() == ORIGINAL


# 6-7. Stale detection, atomicity, rollback ------------------------------------------------------
async def test_stale_source_aborts_without_overwriting(tmp_path):
    target = tmp_path / TARGET

    def mutate(_ctx):
        target.write_text(ORIGINAL + "// concurrent edit\n")

    out, path = await _run_node(
        tmp_path, FakeCode(response=GOOD_DIFF, on_call=mutate))
    assert out.repair_spec["patch_status"] == "error"
    assert "stale" in out.repair_spec["patch_error"]
    assert path.read_text() == ORIGINAL + "// concurrent edit\n"
    assert out.current_patch == ""


async def test_write_failure_leaves_original_and_no_temp(tmp_path, monkeypatch):
    import backend.core.patch as patch_module

    real_write = patch_module.write_atomically
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        raise OSError("disk full")

    monkeypatch.setattr(patch_module, "write_atomically", flaky)
    out, path = await _run_node(tmp_path, FakeCode(response=GOOD_DIFF))
    assert calls["n"] == 1
    assert out.repair_spec["patch_status"] == "error"
    assert path.read_text() == ORIGINAL  # untouched, never partially written
    assert not list(tmp_path.rglob(".visorqa-*"))
    monkeypatch.setattr(patch_module, "write_atomically", real_write)


# 8. Client errors: timeout, auth, refusal, retries --------------------------------------------------
class _Msg:
    def __init__(self, content=None, refusal=None):
        self.content = content
        self.refusal = refusal


class _Completion:
    def __init__(self, msg):
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCreate:
    def __init__(self, content=None, exc=None, refusal=None):
        self._content = content
        self._exc = exc
        self._refusal = refusal
        self.calls = 0
        self.kwargs = None

    async def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self._exc:
            raise self._exc
        return _Completion(_Msg(content=self._content,
                                refusal=self._refusal))


class _FakeChat:
    def __init__(self, create):
        self.chat = type("Ch", (), {"completions": create})()


async def test_client_retry_auth_refusal_empty_cancel():
    class HttpError(Exception):
        status_code = 503

    flaky = _FakeCreate(exc=HttpError())
    client = MuseCodePatchClient(api_key="k", base_url="https://x",
                                 model="m", max_retries=2,
                                 sleep=lambda s: asyncio.sleep(0),
                                 client=_FakeChat(flaky))
    with pytest.raises(Exception):
        await client.generate_diff({})
    assert flaky.calls == 3  # bounded retries on transient 503

    class AuthError(Exception):
        status_code = 401

    auth = _FakeCreate(exc=AuthError())
    client2 = MuseCodePatchClient(api_key="k", base_url="https://x",
                                  model="m", max_retries=3,
                                  sleep=lambda s: asyncio.sleep(0),
                                  client=_FakeChat(auth))
    with pytest.raises(Exception):
        await client2.generate_diff({})
    assert auth.calls == 1  # auth failures never retried

    refused = _FakeCreate(refusal="cannot")
    client3 = MuseCodePatchClient(api_key="k", base_url="https://x",
                                  model="m", client=_FakeChat(refused))
    with pytest.raises(CodeResponseError):
        await client3.generate_diff({})

    empty = _FakeCreate(content="   ")
    client4 = MuseCodePatchClient(api_key="k", base_url="https://x",
                                  model="m", client=_FakeChat(empty))
    with pytest.raises(CodeResponseError):
        await client4.generate_diff({})

    class ReadTimeout(Exception):
        pass

    slow = _FakeCreate(exc=ReadTimeout())
    client5 = MuseCodePatchClient(api_key="k", base_url="https://x",
                                  model="m", max_retries=1,
                                  sleep=lambda s: asyncio.sleep(0),
                                  client=_FakeChat(slow))
    with pytest.raises(Exception):
        await client5.generate_diff({})
    assert slow.calls == 2

    class CancelCreate:
        async def create(self, **kwargs):
            raise asyncio.CancelledError()

    client6 = MuseCodePatchClient(api_key="k", base_url="https://x",
                                  model="m", client=_FakeChat(CancelCreate()))
    with pytest.raises(asyncio.CancelledError):
        await client6.generate_diff({})


def test_code_config_defaults():
    assert settings.MUSE_CODE_MODEL == "muse-spark-1.3"
    client = MuseCodePatchClient(api_key="k")
    assert client.base_url == "https://api.meta.ai/v1"
    assert client.model == "muse-spark-1.3"


# 9-11. State handoff integration, rejection invisibility, legacy --------------------------------------------
class _QuietSandbox:
    async def extract_dom_geometry(self, width, height):
        return []

    async def capture_screenshot(self, width, height):
        return b""


class _QuietSam:
    async def generate_component_masks(self, screenshot, boxes):
        return []


async def test_fenced_diff_applied_and_handed_to_node5(tmp_path):
    fenced = "Here is the fix:\n```diff\n" + GOOD_DIFF + "```\n"
    state = make_state(tmp_path)
    triage_before = {k: state.repair_spec[k] for k in (
        "triage_status", "triage_summary",
        "filtered_intentional_element_ids", "triage_rejected_targets")}
    diag_before = {k: state.repair_spec[k] for k in (
        "root_cause", "css_strategy", "target_file",
        "desktop_preservation_constraints")}
    out = await patch_muse_code_and_apply(
        state, code_client=FakeCode(response=fenced))

    target = tmp_path / TARGET
    assert target.read_text() == EXPECTED  # actually applied
    assert "```" not in out.current_patch  # normalized, fences gone
    assert out.current_patch == GOOD_DIFF  # exact applied diff
    assert out.repair_spec["patch_status"] == "applied"
    assert out.repair_spec["patched_files"] == [TARGET]
    assert out.repair_spec["patch_attempt"] == 1
    for key, value in {**triage_before, **diag_before}.items():
        assert out.repair_spec[key] == value, key
    assert out.target_files == [TARGET]
    assert out.is_resolved is False  # Node 4 never marks verified

    # Node 5 consumes the handoff through its existing contract.
    verified = await verify_with_sam(
        out, sandbox_runner=_QuietSandbox(), sam_client=_QuietSam())
    assert verified.attempts[-1].patch_diff == GOOD_DIFF
    assert verified.best_patch == GOOD_DIFF
    assert verified.is_resolved is True


async def test_rejected_patch_never_looks_applied(tmp_path):
    state = make_state(tmp_path)
    evil = GOOD_DIFF.replace(TARGET, UI_TARGET)
    out = await patch_muse_code_and_apply(
        state, code_client=FakeCode(response="```diff\n" + evil + "```\n"))
    assert out.current_patch == ""
    assert "patched_files" not in out.repair_spec
    assert out.repair_spec["patch_status"] == "error"
    assert (tmp_path / TARGET).read_text() == ORIGINAL
    assert out.repair_spec["triage_status"] == "resolved"
    assert out.repair_spec["root_cause"] == \
        TRIAGE_AND_DIAGNOSIS["root_cause"]


async def test_legacy_stub_contract_preserved(tmp_path):
    from backend.adapters.muse_clients import MuseCodeClient

    state = make_state(tmp_path)
    out = await patch_muse_code_and_apply(
        state, code_client=MuseCodeClient(api_key="k"))
    assert out.current_patch.startswith("---")  # stub diff text only
    assert (tmp_path / TARGET).read_text() == ORIGINAL  # no disk writes
    assert out.repair_spec["triage_status"] == "resolved"


async def test_all_protected_targets_skipped(tmp_path):
    state = make_state(tmp_path)
    state.target_files = [UI_TARGET]
    out = await patch_muse_code_and_apply(
        state, code_client=FakeCode(response=GOOD_DIFF))
    assert out.current_patch == ""
    assert out.repair_spec["patch_skipped"].startswith("BR-2")
    assert out.repair_spec["patch_status"] == "skipped"


def test_authorize_requires_exact_spec_target(tmp_path):
    state = make_state(tmp_path)
    parsed = parse_unified_diff(normalize_diff(
        GOOD_DIFF.replace(TARGET, "src/app/page.tsx")))
    with pytest.raises(PatchValidationError):
        authorize_patch(parsed, state, TARGET)
    digest = hashlib.sha256(EXPECTED.encode()).hexdigest()
    assert len(digest) == 64 and isinstance(Path(TARGET).name, str)
