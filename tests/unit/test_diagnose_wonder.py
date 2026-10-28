"""Tests for Node 3 DIAGNOSE: Muse Wonder multimodal RepairSpec.

Mocked model responses only; no live endpoint or credentials.
"""
import asyncio
import base64
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from backend.adapters.wonder_client import (
    MuseWonderDiagnosisClient,
    WonderResponseError,
    build_diagnose_messages,
    to_repair_spec,
)
from backend.config import settings
from backend.core.diagnose import (
    build_attempt_feedback,
    build_diagnosis_context,
    validate_repair_spec,
)
from backend.core.orchestrator import diagnose_muse_wonder, patch_with_muse_code
from backend.core.state import (
    AgentState,
    Anomaly,
    DefectType,
    RepairSpec,
    SelfHealingAttempt,
)

TREE = [
    "src/app/page.tsx",
    "src/components/PromoBanner.tsx",
    "src/components/ProductCard.tsx",
    "src/components/ui/button.tsx",
    "src/layouts/MainLayout.tsx",
]

TRIAGE_META = {
    "triage_status": "resolved",
    "triage_confidence": 0.9,
    "triage_summary": "Promo banner overlaps the checkout CTA",
    "filtered_intentional_element_ids": ["badge-el"],
    "triage_rejected_targets": [
        {"path": "src/components/ui/button.tsx",
         "reason": "protected_shared_ui"}],
    "lca_element_id": "hero",
    "lca_dom": {"tag": "div", "id": "hero"},
    "computed_styles": {"#promo-banner": {"position": "fixed"}},
    "repository_files": TREE,
}

VALID = {
    "root_cause": "PromoBanner uses position:fixed without a stacking "
                  "context, so it paints over the checkout CTA",
    "affected_selectors": ["#promo-banner"],
    "target_file": "src/components/PromoBanner.tsx",
    "css_strategy": "Scope the banner to its parent stacking context: "
                    "make the banner sticky inside the hero container "
                    "instead of fixed to the viewport",
    "desktop_preservation_constraints": [
        "Desktop 1440px hero keeps its current banner height and "
        "sticky offset"],
    "forbidden_hacks": ["global CSS resets", "!important"],
}


def valid_spec(**overrides):
    data = dict(VALID)
    data.update(overrides)
    return RepairSpec.model_validate(data)


def make_state(tmp_spec=None, **overrides):
    spec = dict(TRIAGE_META)
    spec.update(tmp_spec or {})
    kwargs = dict(
        run_id="run-diag-1",
        pr_url="https://github.com/org/repo/pull/1",
        repo_full_name="org/repo", pr_number=1, branch="fix/x",
        attempt=1,
        anomalies=[Anomaly(
            element_id="cta-el", defect_type=DefectType.OCCLUSION,
            visibility_ratio=0.45, iou_score=0.16, bleed_px=37.0,
            viewport="375px")],
        target_files=["src/components/PromoBanner.tsx"],
        repair_spec=spec,
    )
    kwargs.update(overrides)
    return AgentState(**kwargs)


def make_overlay(tmp_path, name="mobile", size=(100, 80)):
    path = tmp_path / f"{name}.png"
    Image.new("RGB", size, (200, 30, 30)).save(path, format="PNG")
    return path


class FakeWonder:
    """New-contract client mock: diagnose(context, overlay_image)."""

    def __init__(self, spec=None, exc=None):
        self.spec = spec
        self.exc = exc
        self.contexts = []
        self.images = []

    async def diagnose(self, context, overlay_image=None):
        self.contexts.append(context)
        self.images.append(overlay_image)
        if self.exc:
            raise self.exc
        return self.spec


# 1. Multimodal request construction with the actual overlay image ------------------
async def test_request_carries_actual_overlay_image(tmp_path):
    overlay_path = make_overlay(tmp_path)
    state = make_state({"overlays": [{
        "viewport": "mobile", "status": "generated",
        "path": str(overlay_path), "artifact_type": "collision_overlay"}]})
    ctx, image = build_diagnosis_context(state)
    assert ctx["overlay"]["status"] == "ready"
    assert image is not None and image[0] == overlay_path.read_bytes()
    assert image[1] == "image/png"

    fake = _FakeOpenAI(parsed=VALID)
    client = MuseWonderDiagnosisClient(api_key="k", base_url="https://x",
                                       model="m", client=fake)
    res = await client.diagnose(ctx, image)
    assert isinstance(res, RepairSpec)
    user = fake.completions.kwargs["messages"][1]
    assert user["role"] == "user"
    image_parts = [p for p in user["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 1
    url = image_parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == overlay_path.read_bytes()
    system = fake.completions.kwargs["messages"][0]["content"]
    assert "do NOT write code" in system


def test_overlay_missing_and_invalid_handled(tmp_path):
    state = make_state()
    ctx, image = build_diagnosis_context(state)
    assert ctx["overlay"]["status"] == "unavailable" and image is None

    bogus = tmp_path / "fake.png"
    bogus.write_text("not an image")
    state2 = make_state({"overlays": [{
        "viewport": "mobile", "status": "generated", "path": str(bogus)}]})
    ctx2, image2 = build_diagnosis_context(state2)
    assert ctx2["overlay"]["reason"] == "invalid image format"
    assert image2 is None

    big = tmp_path / "big.png"
    with open(big, "wb") as fh:
        fh.seek(11 * 1024 * 1024)
        fh.write(b"x")
    state3 = make_state({"overlays": [{
        "viewport": "mobile", "status": "generated", "path": str(big)}]})
    ctx3, image3 = build_diagnosis_context(state3)
    assert ctx3["overlay"]["reason"] == "overlay image too large"
    assert image3 is None

    messages = build_diagnose_messages(ctx, None)
    text = messages[1]["content"][0]["text"]
    assert "unavailable" in text
    assert all(p["type"] == "text" for p in messages[1]["content"])


# 2. Metrics, LCA, and targeted source serialization ----------------------------------
def test_context_serializes_metrics_lca_targets_source(tmp_path):
    src = tmp_path / "src" / "components" / "PromoBanner.tsx"
    src.parent.mkdir(parents=True)
    src.write_text("export const PROMO_MARKER = 1;\n" * 2)
    state = make_state({"repo_root": str(tmp_path)})
    ctx, _ = build_diagnosis_context(state)
    assert ctx["metrics"] == {"V_r": 0.45, "IoU": 0.16, "Delta_x_px": 37.0}
    assert ctx["targets"] == ["src/components/PromoBanner.tsx"]
    assert ctx["sources"][0]["status"] == "ready"
    assert "PROMO_MARKER" in ctx["sources"][0]["excerpt"]

    text = build_diagnose_messages(ctx, None)[1]["content"][0]["text"]
    assert '"V_r": 0.45' in text and '"IoU": 0.16' in text
    assert "Delta_x_px" in text and "37.0" in text
    assert "hero" in text and "#promo-banner" in text
    assert "src/components/PromoBanner.tsx" in text and "PROMO_MARKER" in text


def test_source_context_unavailable_without_checkout():
    ctx, _ = build_diagnosis_context(make_state())
    assert ctx["sources"][0]["status"] == "unavailable"


# 3. Structured parsing and invalid-response handling ------------------------------------
class _Msg:
    def __init__(self, parsed=None, content=None, refusal=None):
        self.parsed = parsed
        self.content = content
        self.refusal = refusal


class _Completion:
    def __init__(self, msg):
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, parsed=None, exc=None):
        self._parsed = parsed
        self._exc = exc
        self.calls = 0
        self.kwargs = None

    async def parse(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self._exc:
            raise self._exc
        return _Completion(_Msg(parsed=RepairSpec.model_validate(self._parsed)))


class _FakeOpenAI:
    def __init__(self, parsed=None, exc=None):
        self.completions = _FakeCompletions(parsed, exc)
        self.beta = type("B", (), {
            "chat": type("C", (), {"completions": self.completions})()})()


class _RefusalCompletions:
    async def parse(self, **kwargs):
        return _Completion(_Msg(refusal="cannot comply"))


def _wrap_beta(completions):
    return type("C", (), {"beta": type("B", (), {
        "chat": type("Ch", (), {"completions": completions})()})()})()


def test_repair_spec_schema_strictness():
    with pytest.raises(ValidationError):
        RepairSpec.model_validate({**VALID, "root_cause": ""})
    with pytest.raises(ValidationError):
        RepairSpec.model_validate({**VALID, "affected_selectors": []})
    with pytest.raises(ValidationError):
        RepairSpec.model_validate({**VALID, "unexpected_field": 1})
    with pytest.raises(ValidationError):
        RepairSpec.model_validate(
            {k: v for k, v in VALID.items() if k != "target_file"})


async def test_client_parsing_refusal_create_fallback():
    fake = _FakeOpenAI(parsed=VALID)
    client = MuseWonderDiagnosisClient(api_key="k", base_url="https://x",
                                       model="m", client=fake)
    res = await client.diagnose({"defect": {}}, None)
    assert res.target_file == "src/components/PromoBanner.tsx"
    assert fake.completions.kwargs["response_format"] is RepairSpec

    refused = MuseWonderDiagnosisClient(api_key="k", base_url="https://x",
                                        model="m", client=_wrap_beta(
                                            _RefusalCompletions()))
    with pytest.raises(WonderResponseError):
        await refused.diagnose({}, None)

    class CreateOnly:
        def __init__(self, content):
            self.kwargs = None
            self._content = content
            self.chat = type("Ch", (), {"completions": self})()

        async def create(self, **kwargs):
            self.kwargs = kwargs
            return _Completion(_Msg(content=self._content))

    good = CreateOnly(json.dumps(VALID))
    client2 = MuseWonderDiagnosisClient(api_key="k", base_url="https://x",
                                        model="m", client=good)
    res2 = await client2.diagnose({"defect": {}}, None)
    assert res2.root_cause == VALID["root_cause"]
    sent = good.kwargs["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["name"] == "RepairSpec"

    bad = CreateOnly(json.dumps({"root_cause": "only one field"}))
    client3 = MuseWonderDiagnosisClient(api_key="k", base_url="https://x",
                                        model="m", client=bad)
    with pytest.raises(WonderResponseError):
        await client3.diagnose({"defect": {}}, None)


def test_invalid_output_rejected_locally():
    with pytest.raises(WonderResponseError):
        to_repair_spec({"target_file": "src/app/page.tsx"})
    with pytest.raises(WonderResponseError):
        to_repair_spec("not json {{{")


# 4-5. Node 2 metadata preservation on success and failure ------------------------------
async def test_triage_metadata_preserved_on_success():
    state = make_state()
    before = {k: state.repair_spec[k] for k in TRIAGE_META}
    out = await diagnose_muse_wonder(
        state, wonder_client=FakeWonder(spec=valid_spec()))
    for key, value in before.items():
        assert out.repair_spec[key] == value, key
    assert out.repair_spec["diagnose_status"] == "resolved"
    assert out.repair_spec["root_cause"] == VALID["root_cause"]
    assert out.repair_spec["target_file"] == \
        "src/components/PromoBanner.tsx"
    assert out.target_files == ["src/components/PromoBanner.tsx"]


async def test_triage_metadata_preserved_on_endpoint_failure():
    state = make_state()
    before = dict(state.repair_spec)
    wonder = FakeWonder(exc=RuntimeError("endpoint down"))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    for key, value in before.items():
        assert out.repair_spec[key] == value, key
    assert out.repair_spec["diagnose_status"] == "error"
    assert "diagnose_error" in out.repair_spec
    assert "root_cause" not in out.repair_spec  # never fabricated


async def test_triage_metadata_preserved_on_validation_failure():
    state = make_state()
    before = dict(state.repair_spec)
    wonder = FakeWonder(spec=valid_spec(target_file="src/app/page.tsx"))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    for key, value in before.items():
        assert out.repair_spec[key] == value, key
    assert out.repair_spec["diagnose_status"] == "error"


# 6. Unauthorized, nonexistent, protected target_file --------------------------------------
@pytest.mark.parametrize("evil,kind", [
    ("src/components/ProductCard.tsx", "unauthorized"),
    ("src/components/ui/button.tsx", "protected"),
    ("../etc/passwd", "malformed"),
    ("", "malformed"),
])
async def test_rejected_target_files(evil, kind):
    state = make_state()
    wonder = FakeWonder(spec=valid_spec(target_file=evil or "x"))
    if not evil:
        wonder.spec = RepairSpec.model_construct(
            **{**VALID, "target_file": ""})
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    assert out.repair_spec["diagnose_status"] == "error"
    assert out.target_files == ["src/components/PromoBanner.tsx"]
    assert "target_file" not in out.repair_spec or \
        out.repair_spec["target_file"] != evil


async def test_nonexistent_target_rejected_with_tree():
    state = make_state(
        tmp_spec={}, target_files=["src/components/Ghost.tsx"])
    wonder = FakeWonder(spec=valid_spec(
        target_file="src/components/Ghost.tsx"))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    assert out.repair_spec["diagnose_status"] == "error"

    with pytest.raises(Exception):
        validate_repair_spec(
            valid_spec(target_file="src/components/Ghost.tsx"), state)


# 7. Attempt feedback --------------------------------------------------------------------------
def test_first_attempt_has_no_feedback():
    state = make_state(attempt=1)
    assert build_attempt_feedback(state, state.repair_spec) is None
    ctx, _ = build_diagnosis_context(state)
    assert ctx["feedback"] is None
    text = build_diagnose_messages(ctx, None)[1]["content"][0]["text"]
    assert "Previous-attempt feedback" not in text


def _attempt(n, **kw):
    base = dict(attempt_number=n, patch_diff="--- a/x\n+++ b/x",
                  verified_vr=0.74, verified_iou=0.1,
                  verified_bleed_px=5.0, passed=False,
                  error_message="desktop V_r dropped to 0.74")
    base.update(kw)
    return SelfHealingAttempt(**base)


def test_second_attempt_includes_prior_failure():
    state = make_state(attempt=2, attempts=[_attempt(1)])
    state.repair_spec["root_cause"] = "attempt-1 root cause"
    state.repair_spec["fix_strategy"] = "attempt-1 strategy"
    feedback = build_attempt_feedback(state, state.repair_spec)
    assert feedback["available"] is True
    assert feedback["attempt_number"] == 1
    assert feedback["verified_metrics"] == {
        "V_r": 0.74, "IoU": 0.1, "Delta_x_px": 5.0}
    assert feedback["previous_css_strategy"] == "attempt-1 strategy"
    ctx, _ = build_diagnosis_context(state)
    text = build_diagnose_messages(ctx, None)[1]["content"][0]["text"]
    assert "Previous-attempt feedback" in text
    assert "Historical evidence only" in text and "0.74" in text
    # Current metrics stay in their own section, not replaced by history.
    assert '"V_r": 0.45' in text


def test_third_attempt_uses_latest_feedback():
    state = make_state(attempt=3, attempts=[
        _attempt(1), _attempt(2, verified_vr=0.81, error_message=None)])
    feedback = build_attempt_feedback(state, state.repair_spec)
    assert feedback["attempt_number"] == 2
    assert feedback["verified_metrics"]["V_r"] == 0.81


def test_missing_feedback_handled_safely():
    state = make_state(attempt=2, attempts=[])
    feedback = build_attempt_feedback(state, state.repair_spec)
    assert feedback["available"] is False
    ctx, _ = build_diagnosis_context(state)
    text = build_diagnose_messages(ctx, None)[1]["content"][0]["text"]
    assert "no completed attempt record" in text


# 8. Desktop constraints and forbidden hacks -------------------------------------------------------
async def test_desktop_constraints_and_forbidden_hacks():
    state = make_state()
    wonder = FakeWonder(spec=valid_spec(forbidden_hacks=["custom-hack"]))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    hacks = out.repair_spec["forbidden_hacks"]
    assert "custom-hack" in hacks  # model content preserved
    assert "!important" in hacks and "z-index: 9999" in hacks  # policy merged
    assert out.repair_spec["desktop_preservation_constraints"] == \
        VALID["desktop_preservation_constraints"]


# 9. No raw patch code ---------------------------------------------------------------------------------
@pytest.mark.parametrize("poisoned", [
    {"css_strategy": "Apply this:\n```css\n#promo-banner{top:0}\n```"},
    {"css_strategy": "Just add !important to the banner rule"},
    {"root_cause": "--- a/src/x\n+++ b/src/x\n@@ -1 +1 @@\n-old\n+new"},
])
async def test_patch_code_and_banned_strategy_rejected(poisoned):
    state = make_state()
    wonder = FakeWonder(spec=valid_spec(**poisoned))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    assert out.repair_spec["diagnose_status"] == "error"
    assert "root_cause" not in out.repair_spec or \
        out.repair_spec.get("diagnose_status") == "error"


async def test_invented_selector_rejected():
    state = make_state()
    wonder = FakeWonder(spec=valid_spec(
        affected_selectors=["#totally-invented-widget"]))
    out = await diagnose_muse_wonder(state, wonder_client=wonder)
    assert out.repair_spec["diagnose_status"] == "error"


# 10. Downstream compatibility + legacy stub --------------------------------------------------------------
async def test_downstream_patch_consumes_validated_spec():
    state = make_state(attempt=1)
    out = await diagnose_muse_wonder(
        state, wonder_client=FakeWonder(spec=valid_spec()))
    seen = {}

    class FakeCode:
        async def generate_patch(self, source, spec, path):
            seen.update(source=source, spec=spec, path=path)
            return "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b"

    patched = await patch_with_muse_code(out, code_client=FakeCode())
    assert seen["path"] == "src/components/PromoBanner.tsx"
    assert seen["spec"]["css_strategy"] == VALID["css_strategy"]
    assert seen["spec"]["target_file"] == "src/components/PromoBanner.tsx"
    assert patched.current_patch.startswith("--- a/x")


async def test_legacy_stub_contract_preserved():
    from backend.adapters.muse_clients import MuseWonderClient

    state = make_state()
    out = await diagnose_muse_wonder(
        state, wonder_client=MuseWonderClient(api_key="k"))
    assert out.repair_spec["root_cause"]
    assert "z-10" in out.repair_spec["fix_strategy"]
    assert out.repair_spec["diagnose_status"] == "resolved"
    assert out.repair_spec["triage_status"] == "resolved"
    assert out.repair_spec["filtered_intentional_element_ids"] == ["badge-el"]


# Client configuration, retries, cancellation ------------------------------------------------------------
def test_wonder_config_defaults():
    assert settings.MUSE_WONDER_MODEL == "muse-wonder-1.0"
    client = MuseWonderDiagnosisClient(api_key="k")
    assert client.base_url == "https://api.meta.ai/v1"
    assert client.model == "muse-wonder-1.0"


async def test_retry_policy_and_cancellation():
    class HttpError(Exception):
        status_code = 503

    flaky = _FakeCompletions(exc=HttpError())
    client = MuseWonderDiagnosisClient(
        api_key="k", base_url="https://x", model="m", max_retries=2,
        sleep=lambda s: asyncio.sleep(0))
    client._client = _wrap_beta(flaky)
    with pytest.raises(Exception):
        await client.diagnose({}, None)
    assert flaky.calls == 3

    class AuthError(Exception):
        status_code = 401

    auth = _FakeCompletions(exc=AuthError())
    client2 = MuseWonderDiagnosisClient(
        api_key="k", base_url="https://x", model="m", max_retries=3,
        sleep=lambda s: asyncio.sleep(0))
    client2._client = _wrap_beta(auth)
    with pytest.raises(Exception):
        await client2.diagnose({}, None)
    assert auth.calls == 1

    class CancelCompletions:
        async def parse(self, **kwargs):
            raise asyncio.CancelledError()

    client3 = MuseWonderDiagnosisClient(
        api_key="k", base_url="https://x", model="m",
        sleep=lambda s: asyncio.sleep(0))
    client3._client = _wrap_beta(CancelCompletions())
    with pytest.raises(asyncio.CancelledError):
        await client3.diagnose({}, None)
