"""Muse Spark source-localization client (Meta Model API, direct).

Calls ``https://api.meta.ai/v1`` with model ``muse-spark-1.3`` via
``AsyncOpenAI(api_key=META_API_KEY, base_url=META_BASE_URL)``. Typed
structured output uses ``client.beta.chat.completions.parse(
response_format=SparkTriageSchema)`` per the Meta structured-output
documentation (https://dev.meta.ai/docs/structured-output); the parsed
result is converted into the domain :class:`TriageResponse` and
validated locally. When ``parse`` is unavailable, the client sends the
same schema as an explicit ``response_format`` ``json_schema`` through
``chat.completions.create`` (Meta constrains decoding to the schema)
and validates the JSON content explicitly. Failures raise
:class:`SparkError` subclasses -- the client never fabricates a
successful triage. BR-2 itself is enforced in application code
(``backend.core.triage``), not here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import settings
from backend.core.state import TriageCandidate, TriageResponse

logger = logging.getLogger("visorqa.spark")

SYSTEM_PROMPT = """You are Muse Spark, a source-localization triage \
engine for visual UI defects. You do NOT write or propose code fixes.

Given visual defect evidence (anomalies), the LCA DOM hierarchy with \
computed CSS signatures, and the repository file tree, identify the \
1-2 source files most likely RESPONSIBLE for each defect.

Rules you must follow:
- Distinguish where a defect APPEARS from the file RESPONSIBLE for it.
- src/components/ui/* are atomic shared UI primitives. NEVER return \
them as direct fix targets, even when a defect appears inside them. \
Instead localize to the consuming component, parent layout, or \
relevant sibling file that uses the primitive, and explain that \
redirect in your evidence.
- Some overlaps are intentional (for example a badge positioned \
absolute/fixed over an avatar). Treat such evidence-supported \
intentional overlaps as non-defects; do not localize a fix for them. \
Do not call an overlap intentional merely because elements are nested \
or intersecting.
- Only return paths that appear verbatim in the supplied repository \
file tree. Never invent file paths.
- Ground every target in specific evidence from the DOM hierarchy, \
computed CSS, or file tree. Prefer the smallest responsible \
application-level component or layout file, not a global stylesheet.
- If the evidence is insufficient for any file, return status \
"unresolved" with empty target_files rather than speculating. Low \
confidence is an acceptable and honest outcome."""


class SparkTriageSchema(BaseModel):
    """Structured-output wire schema for the Meta Model API.

    Mirrors :class:`TriageResponse` minus the fields that cannot satisfy
    Meta's strict structured-output subset: ``lca_dom`` is a free-form
    ``Dict[str, Any]`` (an object the strict schema cannot describe) and
    ``rejected_targets`` is server-side BR-2 enforcement output the model
    must not produce. ``extra`` is forbidden so every object carries
    ``additionalProperties: false``. The SDK expands this into
    ``strict: true`` JSON Schema: optional fields surface as ``anyOf``
    (supported below the root), and there are no ``allOf``/``oneOf``
    branches, no enums, and no recursive ``$ref`` cycles.
    """

    model_config = ConfigDict(extra="forbid")

    target_files: List[str] = Field(default_factory=list, max_length=2)
    candidates: List[TriageCandidate] = Field(default_factory=list)
    candidate_source_file: Optional[str] = None
    lca_element_id: Optional[str] = None
    triage_summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = "unresolved"
    evidence: List[str] = Field(default_factory=list)
    filtered_intentional_element_ids: List[str] = Field(default_factory=list)


class SparkError(Exception):
    pass


class SparkConfigurationError(SparkError):
    pass


class SparkResponseError(SparkError):
    pass


def build_triage_messages(context: Dict[str, Any]) -> List[Dict[str, str]]:
    payload = json.dumps(context, default=str)[:16000]
    user = (
        "Localize the responsible source files for these visual "
        "defects.\n\nEvidence (anomalies, LCA DOM hierarchy, computed "
        "CSS signatures, viewport diagnostics, repository file tree):\n"
        f"{payload}\n\nReturn at most 2 target_files, each grounded "
        "in cited evidence, plus candidates for any parent-layout, "
        "consumer, or sibling alternatives you considered."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def json_schema_response_format() -> Dict[str, Any]:
    """Explicit ``response_format`` for ``chat.completions.create``.

    Used only when the SDK has no ``beta.chat.completions.parse``. Meta
    constrains decoding to the supplied schema on this path as well.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "SparkTriageSchema",
            "schema": SparkTriageSchema.model_json_schema(),
            "strict": False,
        },
    }


def to_triage_response(parsed: Any) -> TriageResponse:
    """Validate parsed structured output into the domain contract."""
    try:
        if isinstance(parsed, BaseModel):
            return TriageResponse.model_validate(parsed.model_dump())
        if isinstance(parsed, str):
            return TriageResponse.model_validate_json(parsed)
        return TriageResponse.model_validate(parsed)
    except ValidationError as exc:
        raise SparkResponseError(
            f"invalid structured response: {exc.error_count()} errors")


class MuseSparkTriageClient:
    """AsyncOpenAI-backed Muse Spark client with bounded retries."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 1,
        backoff_base_seconds: float = 0.2,
        sleep: Any = None,
    ):
        self.api_key = api_key if api_key is not None else settings.META_API_KEY
        self.base_url = base_url if base_url is not None else settings.META_BASE_URL
        self.model = model if model is not None else \
            getattr(settings, "MUSE_SPARK_MODEL", "")
        self.timeout_seconds = float(
            timeout_seconds or getattr(settings, "SPARK_TIMEOUT_SECONDS", 15.0))
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_seconds = float(backoff_base_seconds)
        self._sleep = sleep or asyncio.sleep
        self._client = client  # injectable AsyncOpenAI (tests)

    def _get_client(self):
        if self._client is None:
            if not self.api_key or not self.base_url or not self.model:
                raise SparkConfigurationError(
                    "META_API_KEY, META_BASE_URL and MUSE_SPARK_MODEL "
                    "must be configured for Muse Spark triage")
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url,
                timeout=self.timeout_seconds, max_retries=0)
        return self._client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        # Retry transient failures only: 429/5xx, timeouts, connection
        # errors. Auth (401/403) and malformed request/schema (400)
        # failures are never retried.
        status = getattr(exc, "status_code", None)
        if status is not None:
            return status == 429 or status >= 500
        name = type(exc).__name__
        return any(k in name for k in ("Timeout", "RateLimit", "Connection"))

    async def _parse_once(self, messages) -> TriageResponse:
        client = self._get_client()
        beta = getattr(client, "beta", None)
        completions = getattr(getattr(beta, "chat", None), "completions", None)
        parse = getattr(completions, "parse", None)
        if callable(parse):
            response = await parse(
                model=self.model, messages=messages,
                response_format=SparkTriageSchema)
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise SparkResponseError("model refused triage request")
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                content = getattr(message, "content", None)
                if content:
                    # Server-constrained output the SDK did not bind to
                    # the Pydantic type: validate explicitly, never
                    # trust raw text as a valid result.
                    return to_triage_response(content)
                raise SparkResponseError("structured response missing")
            return to_triage_response(parsed)
        # SDK without beta parse: same schema through create(), then
        # explicit local validation of the JSON content.
        response = await client.chat.completions.create(
            model=self.model, messages=messages,
            response_format=json_schema_response_format())
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise SparkResponseError("model refused triage request")
        content = getattr(message, "content", None) or ""
        if not content.strip():
            raise SparkResponseError("structured response missing")
        return to_triage_response(content)

    async def triage(self, context: Dict[str, Any]) -> TriageResponse:
        messages = build_triage_messages(context)
        attempt = 0
        while True:
            try:
                result = await self._parse_once(messages)
                logger.info("spark triage ok: %d target(s), status=%s",
                            len(result.target_files), result.status)
                return result
            except (SparkResponseError, SparkConfigurationError):
                raise  # validation/refusal/config: retrying will not help
            except Exception as exc:
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    raise SparkError(
                        f"Muse Spark triage failed: {type(exc).__name__}"
                    ) from exc
                await self._sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1
