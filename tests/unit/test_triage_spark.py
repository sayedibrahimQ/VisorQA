"""Tests for Node 2 TRIAGE: Muse Spark localization + BR-2 enforcement.

Mocked model responses only; no live endpoint or credentials.
"""
import asyncio
import json

import pytest
from pydantic import ValidationError

from backend.adapters.spark_client import (
    MuseSparkTriageClient,
    SparkConfigurationError,
    SparkError,
    SparkResponseError,
    SparkTriageSchema,
    build_triage_messages,
    to_triage_response,
)
from backend.config import settings
from backend.core.orchestrator import triage_files_muse_spark
from backend.core.state import (
    AgentState,
    Anomaly,
    DefectType,
    TriageCandidate,
    TriageResponse,
)
from backend.core.triage import (
    build_triage_context,
    detect_intentional_overlaps,
    enforce_triage_response,
    is_protected_path,
    normalize_path,
)

TREE = [
    "src/app/page.tsx",
    "src/components/PromoBanner.tsx",
    "src/components/ProductCard.tsx",
    "src/components/cart/CartLayout.tsx",
    "src/components/ui/button.tsx",
    "src/components/ui/avatar.tsx",
    "src/layouts/MainLayout.tsx",
]


def hierarchy_record(eid, chain, css=None, sibling=None):
    rec = {"relationship": "element_ancestry", "element_ids": [eid],
           "element": {"tag": "span", "id": "", "classes": [],
                       "data-visor-el-id": eid, "text_hint": eid},
           "ancestor_chain": chain, "element_css_signatures": css or {}}
    if sibling:
        rec["sibling"] = sibling
    return rec


def badge_hierarchy():
    return [
        hierarchy_record(
            "badge-el",
            [{"tag": "div", "id": "", "classes": ["avatar"],
              "data-visor-el-id": "avatar-el", "text_hint": ""}],
            css={"badge-el": {"position": "absolute", "display": "block"}},
        ),
        hierarchy_record("avatar-el", []),
    ]


def make_state(anomalies=None, hierarchy=None, **spec):
    base = {
        "repository_files": TREE,
        "hierarchy": hierarchy if hierarchy is not None
        else badge_hierarchy(),
        "lca_dom": {"tag": "div", "id": "app"},
        "computed_styles": {"#toolbar": {"display": "flex"}},
    }
    base.update(spec)
    return AgentState(
        pr_url="https://github.com/org/repo/pull/1",
        repo_full_name="org/repo", pr_number=1, branch="fix/x",
        anomalies=anomalies if anomalies is not None else [
            Anomaly(element_id="badge-el", secondary_el_id="avatar-el",
                    defect_type=DefectType.COLLISION, iou_score=0.4),
            Anomaly(element_id="cta-el",
                    defect_type=DefectType.OCCLUSION,
                    visibility_ratio=0.4),
        ],
        repair_spec=base,
    )


class FakeSpark:
    """Muse Spark client mock returning a canned TriageResponse."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.contexts = []

    async def triage(self, context):
        self.contexts.append(context)
        if self.exc:
            raise self.exc
        return self.response


def resolved_response(targets, confidence=0.9, candidates=None, **kw):
    return TriageResponse(
        target_files=targets, candidates=candidates or [],
        confidence=confidence, status="resolved",
        evidence=["LCA container #app has display:flex (computed CSS)"],
        **kw)


# 1. Model input construction -------------------------------------------------
def test_context_and_message_construction():
    state = make_state()
    ctx = build_triage_context(state)
    assert ctx["repository_files"] == sorted(TREE)
    assert ctx["hierarchy"] and ctx["computed_styles"]["#toolbar"]
    assert {a["element_id"] for a in ctx["anomalies"]} == {"badge-el", "cta-el"}
    messages = build_triage_messages(ctx)
    assert messages[0]["role"] == "system"
    assert "src/components/ui/*" in messages[0]["content"]
    assert "badge" in messages[0]["content"].lower()
    assert "PromoBanner" in messages[1]["content"]


# 2. Structured parsing ---------------------------------------------------------
async def test_structured_response_parsing_into_triage_response():
    fake_client = _FakeOpenAI(parsed={
        "target_files": ["src/components/PromoBanner.tsx"],
        "confidence": 0.88, "status": "resolved",
        "evidence": ["banner overlaps CTA in hierarchy"],
        "lca_element_id": "hero",
    })
    client = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                     model="spark", client=fake_client)
    res = await client.triage({"anomalies": []})
    assert isinstance(res, TriageResponse)
    assert res.target_files == ["src/components/PromoBanner.tsx"]
    assert res.confidence == pytest.approx(0.88)


class _Msg:
    def __init__(self, parsed=None, content=None, refusal=None):
        self.parsed = parsed
        self.content = content
        self.refusal = refusal


class _Completion:
    def __init__(self, msg):
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, parsed=None, exc=None, parsed_as_dict=True):
        self._parsed = parsed
        self._exc = exc
        self.calls = 0
        self.kwargs = None
        self._as_dict = parsed_as_dict

    async def parse(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self._exc:
            raise self._exc
        parsed = TriageResponse.model_validate(self._parsed) \
            if self._as_dict else self._parsed
        return _Completion(_Msg(parsed=parsed))


class _FakeOpenAI:
    def __init__(self, parsed=None, exc=None):
        self.completions = _FakeCompletions(parsed, exc)
        self.beta = type("B", (), {
            "chat": type("C", (), {"completions": self.completions})()})()


def _wrap_beta(completions):
    return type("C", (), {"beta": type("B", (), {
        "chat": type("Ch", (), {"completions": completions})()})()})()


def _client_with(exc, max_retries=2, sleep=None):
    flaky = _FakeCompletions(exc=exc)
    client = MuseSparkTriageClient(
        api_key="k", base_url="https://x", model="m",
        max_retries=max_retries,
        sleep=sleep or (lambda s: asyncio.sleep(0)))
    client._client = _wrap_beta(flaky)
    return client, flaky


class _RefusalCompletions:
    def __init__(self):
        self.calls = 0

    async def parse(self, **kwargs):
        self.calls += 1
        return _Completion(_Msg(refusal="I cannot help with that"))


class _ContentOnlyCompletions:
    """parse() path returning unbound content instead of .parsed."""

    def __init__(self, content):
        self.content = content

    async def parse(self, **kwargs):
        return _Completion(_Msg(parsed=None, content=self.content))


class _FakeCreateCompletions:
    """chat.completions.create without beta parse (older SDK shape)."""

    def __init__(self, content=None, refusal=None):
        self.content = content
        self.refusal = refusal
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _Completion(_Msg(content=self.content, refusal=self.refusal))


class _FakeCreateOpenAI:
    def __init__(self, content=None, refusal=None):
        self.completions = _FakeCreateCompletions(content, refusal)
        self.chat = type("Ch", (), {"completions": self.completions})()


# 3 + 4. Intentional overlaps filtered; genuine defects stay ----------------------
def test_intentional_badge_avatar_filtered_genuine_kept():
    state = make_state()
    intentional = detect_intentional_overlaps(
        state.anomalies, state.repair_spec["hierarchy"], state.repair_spec)
    assert set(intentional) == {"badge-el", "avatar-el"}

    # Same names but NO absolute/fixed positioning -> not intentional.
    weak = badge_hierarchy()
    weak[0]["element_css_signatures"] = {"badge-el": {"position": "static"}}
    assert detect_intentional_overlaps(state.anomalies, weak, {}) == {}


async def test_intentional_filtered_but_genuine_actionable():
    spark = FakeSpark(resolved_response(["src/components/PromoBanner.tsx"]))
    state = make_state()
    out = await triage_files_muse_spark(state, spark_client=spark)
    # Genuine CTA occlusion still localizes; intentional pair recorded.
    assert out.target_files == ["src/components/PromoBanner.tsx"]
    assert set(out.repair_spec["filtered_intentional_element_ids"]) == \
        {"badge-el", "avatar-el"}


async def test_all_intentional_no_actionable():
    state = make_state(anomalies=[
        Anomaly(element_id="badge-el", secondary_el_id="avatar-el",
                defect_type=DefectType.COLLISION, iou_score=0.4)])
    spark = FakeSpark(resolved_response(["src/components/PromoBanner.tsx"]))
    out = await triage_files_muse_spark(state, spark_client=spark)
    assert out.target_files == []
    assert out.repair_spec["triage_status"] == "no_actionable_defects"


# 5-7. Protected rejection, redirect, unresolved ------------------------------------
async def test_protected_target_rejected_high_confidence():
    # Regression: 0.99 confidence must not override BR-2.
    spark = FakeSpark(resolved_response(
        ["src/components/ui/button.tsx"], confidence=0.99))
    out = await triage_files_muse_spark(make_state(), spark_client=spark)
    assert out.target_files == []
    assert out.repair_spec["triage_status"] == "unresolved"
    reasons = {r["reason"] for r in out.repair_spec["triage_rejected_targets"]}
    assert "protected_shared_ui" in reasons


async def test_parent_layout_alternative_selected():
    spark = FakeSpark(resolved_response(
        ["src/components/ui/button.tsx"], confidence=0.95,
        candidates=[TriageCandidate(
            path="src/components/cart/CartLayout.tsx", confidence=0.9,
            evidence="CartLayout consumes ui/button inside the LCA "
                     "container and owns the flex row", kind="parent_layout")]))
    out = await triage_files_muse_spark(make_state(), spark_client=spark)
    assert out.target_files == ["src/components/cart/CartLayout.tsx"]
    assert out.repair_spec["triage_status"] == "resolved"


async def test_no_safe_alternative_unresolved():
    spark = FakeSpark(resolved_response(
        ["src/components/ui/avatar.tsx"], confidence=0.9,
        candidates=[TriageCandidate(
            path="src/components/ui/button.tsx", confidence=0.9,
            evidence="also protected", kind="sibling")]))
    out = await triage_files_muse_spark(make_state(), spark_client=spark)
    assert out.target_files == []
    assert out.repair_spec["triage_status"] == "unresolved"


# 8 + 9. Fabricated, malformed, traversal paths -----------------------------------------
@pytest.mark.parametrize("evil", [
    "src/components/DoesNotExist.tsx",       # fabricated
    "src/components/../../etc/passwd",       # traversal
    "/etc/passwd",                           # absolute
    "..\\windows\\system32",                 # backslash traversal
    "",                                      # empty
])
async def test_bad_paths_rejected(evil):
    spark = FakeSpark(resolved_response([evil] if evil else [],
                                        confidence=0.95))
    out = await triage_files_muse_spark(make_state(), spark_client=spark)
    assert evil not in out.target_files
    assert out.target_files == []


def test_path_normalization_units():
    assert normalize_path("src/components/../components/PromoBanner.tsx") \
        == "src/components/PromoBanner.tsx"
    assert normalize_path("../evil") is None
    assert normalize_path("/abs/path") is None
    assert is_protected_path("src/components/ui/button.tsx")
    assert not is_protected_path("src/components/PromoBanner.tsx")


# 10. Invalid output, endpoint errors, retries ----------------------------------------------
async def test_invalid_pydantic_output_becomes_error_state():
    class BadSpark:
        async def triage(self, context):
            return {"target_files": "not-a-list",
                    "confidence": "high"}  # fails TriageResponse validation

    out = await triage_files_muse_spark(make_state(), spark_client=BadSpark())
    assert out.repair_spec["triage_status"] == "error"
    assert "triage_error" in out.repair_spec
    assert all(not is_protected_path(f) for f in out.target_files)


async def test_endpoint_error_and_retry_exhaustion():
    spark = FakeSpark(exc=RuntimeError("endpoint down"))
    out = await triage_files_muse_spark(make_state(), spark_client=spark)
    assert out.repair_spec["triage_status"] == "error"

    class HttpError(Exception):
        status_code = 503

    flaky = _FakeCompletions(exc=HttpError())
    client = MuseSparkTriageClient(
        api_key="k", base_url="https://x", model="spark", max_retries=2,
        sleep=lambda s: asyncio.sleep(0))
    client._client = type("C", (), {"beta": type("B", (), {
        "chat": type("Ch", (), {"completions": flaky})()})()})()
    with pytest.raises(Exception):
        await client.triage({})
    assert flaky.calls == 3  # 1 initial + 2 bounded retries

    class AuthError(Exception):
        status_code = 401

    auth = _FakeCompletions(exc=AuthError())
    client2 = MuseSparkTriageClient(
        api_key="k", base_url="https://x", model="spark", max_retries=3,
        sleep=lambda s: asyncio.sleep(0))
    client2._client = type("C", (), {"beta": type("B", (), {
        "chat": type("Ch", (), {"completions": auth})()})()})()
    with pytest.raises(Exception):
        await client2.triage({})
    assert auth.calls == 1  # auth errors never retried


def test_triage_response_schema_constraints():
    with pytest.raises(ValidationError):
        TriageResponse(confidence=1.5)
    with pytest.raises(ValidationError):
        TriageResponse(target_files=["a", "b", "c"])  # max 2 targets


# 11. Downstream compatibility ------------------------------------------------------------------
async def test_downstream_graph_compatibility():
    from backend.core.orchestrator import VisorOrchestrator

    spark = FakeSpark(resolved_response(
        ["src/components/PromoBanner.tsx"], lca_element_id="hero",
        triage_summary="Promo banner overlaps the CTA"))
    orch = VisorOrchestrator(spark_client=spark)
    out = await orch.step_2_triage(make_state())
    assert out.target_files == ["src/components/PromoBanner.tsx"]
    assert out.repair_spec["lca_element_id"] == "hero"
    assert out.repair_spec["triage_summary"]
    # DIAGNOSE consumes exactly these fields.
    assert out.repair_spec["triage_status"] == "resolved"
    dumped = json.loads(json.dumps(out.model_dump(mode="json")))
    assert dumped["target_files"] == ["src/components/PromoBanner.tsx"]


def test_enforce_direct_units():
    resp = resolved_response(["src/components/ui/button.tsx"],
                             confidence=0.99)
    out = enforce_triage_response(resp, repo_tree=TREE)
    assert out.target_files == [] and out.status == "unresolved"
    resp2 = resolved_response(["src/components/PromoBanner.tsx"],
                              confidence=0.2)
    out2 = enforce_triage_response(resp2, repo_tree=TREE)
    assert out2.target_files == []  # low confidence never localizes
    assert out2.rejected_targets[-1].reason == "low_confidence"


# Meta Model API configuration ---------------------------------------------------
def test_meta_api_defaults():
    assert settings.META_BASE_URL == "https://api.meta.ai/v1"
    assert settings.MUSE_SPARK_MODEL == "muse-spark-1.3"
    client = MuseSparkTriageClient(api_key="k")
    assert client.base_url == "https://api.meta.ai/v1"
    assert client.model == "muse-spark-1.3"


def test_configuration_error_without_api_key():
    client = MuseSparkTriageClient(api_key="")
    with pytest.raises(SparkConfigurationError):
        client._get_client()


def test_asyncopenai_receives_meta_configuration(monkeypatch):
    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)
    client = MuseSparkTriageClient(api_key="k", timeout_seconds=9)
    client._get_client()
    assert captured["api_key"] == "k"
    assert captured["base_url"] == "https://api.meta.ai/v1"
    assert captured["timeout"] == 9.0
    assert captured["max_retries"] == 0


async def test_parse_uses_meta_model_and_wire_schema():
    fake = _FakeOpenAI(parsed={"target_files": [], "confidence": 0.0})
    client = MuseSparkTriageClient(api_key="k", client=fake)
    await client.triage({"anomalies": []})
    assert fake.completions.kwargs["model"] == "muse-spark-1.3"
    assert fake.completions.kwargs["response_format"] is SparkTriageSchema


# Structured-output parsing: refusal / missing / invalid --------------------------
async def test_parse_refusal_is_response_error():
    comp = _RefusalCompletions()
    client = MuseSparkTriageClient(
        api_key="k", base_url="https://x", model="m", max_retries=3,
        sleep=lambda s: asyncio.sleep(0))
    client._client = _wrap_beta(comp)
    with pytest.raises(SparkResponseError):
        await client.triage({})
    assert comp.calls == 1  # refusals are never retried


async def test_parse_missing_content_is_response_error():
    comp = _ContentOnlyCompletions(content="")
    client = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                   model="m", client=_wrap_beta(comp))
    with pytest.raises(SparkResponseError):
        await client.triage({})


async def test_parse_unbound_content_validated_explicitly():
    payload = {"target_files": ["src/app/page.tsx"], "confidence": 0.7,
               "status": "resolved", "evidence": ["LCA #app owns the row"]}
    comp = _ContentOnlyCompletions(content=json.dumps(payload))
    client = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                   model="m", client=_wrap_beta(comp))
    res = await client.triage({})
    assert isinstance(res, TriageResponse)
    assert res.target_files == ["src/app/page.tsx"]

    bad = _ContentOnlyCompletions(content="not json {{{")
    client2 = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                    model="m", client=_wrap_beta(bad))
    with pytest.raises(SparkResponseError):
        await client2.triage({})


async def test_create_fallback_sends_constrained_schema():
    payload = {"target_files": ["src/app/page.tsx"], "confidence": 0.7,
               "status": "resolved", "evidence": ["LCA #app owns the row"]}
    fake = _FakeCreateOpenAI(content=json.dumps(payload))
    client = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                   model="m", client=fake)
    res = await client.triage({"anomalies": []})
    assert isinstance(res, TriageResponse)
    assert res.target_files == ["src/app/page.tsx"]
    sent = fake.completions.kwargs["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["name"] == "SparkTriageSchema"
    assert "target_files" in sent["json_schema"]["schema"]["properties"]


async def test_create_fallback_rejects_refusal_and_invalid():
    refused = _FakeCreateOpenAI(content="", refusal="no")
    client = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                   model="m", client=refused)
    with pytest.raises(SparkResponseError):
        await client.triage({})

    empty = _FakeCreateOpenAI(content="   ")
    client2 = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                    model="m", client=empty)
    with pytest.raises(SparkResponseError):
        await client2.triage({})

    invalid = _FakeCreateOpenAI(content=json.dumps(
        {"target_files": ["a", "b", "c"], "confidence": 0.9}))
    client3 = MuseSparkTriageClient(api_key="k", base_url="https://x",
                                    model="m", client=invalid)
    with pytest.raises(SparkResponseError):
        await client3.triage({})


def test_wire_conversion_applies_domain_defaults():
    parsed = SparkTriageSchema(
        target_files=["src/app/page.tsx"], confidence=0.7,
        status="resolved", evidence=["e"], lca_element_id="hero")
    res = to_triage_response(parsed)
    assert isinstance(res, TriageResponse)
    assert res.target_files == ["src/app/page.tsx"]
    assert res.lca_element_id == "hero"
    assert res.lca_dom == {} and res.rejected_targets == []


def test_invalid_wire_output_rejected():
    with pytest.raises(SparkResponseError):
        to_triage_response({"target_files": ["a", "b", "c"],
                            "confidence": 0.9})
    with pytest.raises(SparkResponseError):
        to_triage_response({"target_files": [], "confidence": 1.5})
    with pytest.raises(SparkResponseError):
        to_triage_response("not json at all {{{")


# Wire-schema strict-subset compatibility --------------------------------------------
def _walk_schemas(node, visit):
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            _walk_schemas(value, visit)
    elif isinstance(node, list):
        for value in node:
            _walk_schemas(value, visit)


def _assert_refs_acyclic(schema):
    def resolve(ref, root):
        assert ref.startswith("#/")
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        return node

    def dfs(node, root, stack):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                assert ref not in stack, f"recursive schema: {ref}"
                dfs(resolve(ref, root), root, stack | {ref})
                return
            for value in node.values():
                dfs(value, root, stack)
        elif isinstance(node, list):
            for value in node:
                dfs(value, root, stack)

    dfs(schema, schema, set())


def test_wire_schema_satisfies_meta_strict_subset():
    raw = SparkTriageSchema.model_json_schema()
    assert raw.get("type") == "object"
    for banned in ("anyOf", "oneOf", "allOf", "enum", "not"):
        assert banned not in raw, f"root must be a plain object: {banned}"
    found = []

    def visit(node):
        for key in ("allOf", "oneOf"):
            if key in node:
                found.append(key)

    _walk_schemas(raw, visit)
    assert found == []
    _assert_refs_acyclic(raw)

    try:
        from openai.lib._pydantic import to_strict_json_schema
    except ImportError:
        pytest.skip("installed SDK lacks the strict-schema helper")
    strict = to_strict_json_schema(SparkTriageSchema)

    def visit_strict(node):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, node
            props = node.get("properties")
            if isinstance(props, dict):
                assert sorted(node.get("required", [])) == sorted(props), node

    _walk_schemas(strict, visit_strict)


def test_wire_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SparkTriageSchema.model_validate(
            {"target_files": [], "bogus_field": 1})


# Context bounds -----------------------------------------------------------------------
def test_context_bounded_and_minimal():
    big_tree = [f"src/components/X{i}.tsx" for i in range(2000)]
    state = make_state(hierarchy=badge_hierarchy() * 30,
                       repository_files=big_tree)
    ctx = build_triage_context(state)
    assert ctx.get("context_truncated") is True
    assert len(ctx["repository_files"]) == 200
    assert len(ctx["hierarchy"]) == 20
    assert set(ctx) <= {
        "anomalies", "lca_dom", "lca_element_id", "hierarchy",
        "computed_styles", "repository_files", "existing_target_files",
        "viewport_diagnostics", "context_truncated",
    }
    blob = json.dumps(ctx, default=str)
    assert "META_API_KEY" not in blob and "GITHUB_PAT" not in blob


# BR-2 on the legacy stub path ------------------------------------------------------------
class LegacyStub:
    """Legacy adapter contract: triage_anomalies dict, no .triage."""

    def __init__(self, result):
        self.result = result

    async def triage_anomalies(self, anomalies, lca_dom):
        return self.result


async def test_legacy_stub_protected_target_rejected():
    stub = LegacyStub({
        "candidate_source_file": "src/components/ui/button.tsx",
        "triage_summary": "defect appears inside the shared button",
    })
    out = await triage_files_muse_spark(make_state(), spark_client=stub)
    assert out.target_files == []
    assert out.repair_spec["triage_status"] == "unresolved"
    reasons = {r["reason"] for r in out.repair_spec["triage_rejected_targets"]}
    assert "protected_shared_ui" in reasons


async def test_legacy_stub_without_tree_preserved():
    state = make_state()
    state.repair_spec.pop("repository_files", None)
    stub = LegacyStub({
        "candidate_source_file": "src/components/PromoBanner.tsx",
        "triage_summary": "legacy deterministic adapter",
    })
    out = await triage_files_muse_spark(state, spark_client=stub)
    assert out.target_files == ["src/components/PromoBanner.tsx"]
    assert out.repair_spec["triage_status"] == "resolved"


async def test_failure_keeps_error_without_protected_targets():
    state = make_state()
    state.target_files = ["src/components/ui/button.tsx"]
    spark = FakeSpark(exc=RuntimeError("endpoint down"))
    out = await triage_files_muse_spark(state, spark_client=spark)
    assert out.repair_spec["triage_status"] == "error"
    assert "triage_error" in out.repair_spec
    assert all(not is_protected_path(f) for f in out.target_files)


# Missing repository tree -------------------------------------------------------------------
async def test_live_path_missing_tree_rejects_unverified():
    state = make_state()
    state.repair_spec.pop("repository_files", None)
    spark = FakeSpark(resolved_response(["src/components/PromoBanner.tsx"]))
    out = await triage_files_muse_spark(state, spark_client=spark)
    assert out.target_files == []
    assert out.repair_spec["triage_status"] == "unresolved"
    reasons = {r["reason"] for r in out.repair_spec["triage_rejected_targets"]}
    assert "not_in_repository_tree" in reasons


def test_enforce_require_tree_units():
    resp = resolved_response(["src/components/PromoBanner.tsx"])
    kept = enforce_triage_response(resp, repo_tree=[])
    assert kept.target_files == ["src/components/PromoBanner.tsx"]
    out = enforce_triage_response(resp, repo_tree=[], require_tree=True)
    assert out.target_files == [] and out.status == "unresolved"
    assert out.rejected_targets[-1].reason == "not_in_repository_tree"


# Retry, timeout, cancellation ------------------------------------------------------------------
async def test_rate_limit_retried_bad_request_not():
    class RateLimited(Exception):
        status_code = 429

    client, flaky = _client_with(RateLimited())
    with pytest.raises(SparkError):
        await client.triage({})
    assert flaky.calls == 3

    class BadRequest(Exception):
        status_code = 400

    client2, bad = _client_with(BadRequest(), max_retries=3)
    with pytest.raises(SparkError):
        await client2.triage({})
    assert bad.calls == 1


async def test_timeout_errors_retried_with_bounded_backoff():
    class ReadTimeout(Exception):
        pass

    waits = []

    async def record(seconds):
        waits.append(seconds)

    client, flaky = _client_with(ReadTimeout(), sleep=record)
    with pytest.raises(SparkError):
        await client.triage({})
    assert flaky.calls == 3
    assert waits == pytest.approx([0.2, 0.4])


async def test_cancellation_propagates_unwrapped():
    class CancelCompletions:
        async def parse(self, **kwargs):
            raise asyncio.CancelledError()

    client = MuseSparkTriageClient(
        api_key="k", base_url="https://x", model="m",
        sleep=lambda s: asyncio.sleep(0))
    client._client = _wrap_beta(CancelCompletions())
    with pytest.raises(asyncio.CancelledError):
        await client.triage({})
