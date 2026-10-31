"""Muse Wonder diagnosis client (Meta Model API, direct, multimodal).

Calls ``https://api.meta.ai/v1`` with model ``muse-wonder-1.0`` via
``AsyncOpenAI(api_key=META_API_KEY, base_url=META_BASE_URL)``. The red
collision-mask overlay image (when available) rides in the ``user``
message as an ``image_url`` data URL per the Meta image-understanding
documentation; typed output uses ``beta.chat.completions.parse(
response_format=RepairSpec)`` with a ``chat.completions.create`` +
explicit ``json_schema`` fallback when ``parse`` is unavailable.
Results are validated locally; failures raise :class:`WonderError`
subclasses -- the client never fabricates a successful diagnosis.
Authorization (Node 2 targets, BR-2) is enforced in application code
(``backend.core.diagnose``), not here.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ValidationError

from backend.config import settings
from backend.core.state import RepairSpec

logger = logging.getLogger("visorqa.wonder")

SYSTEM_PROMPT = """You are Muse Wonder, a multimodal visual-defect \
diagnosis architect. You produce a declarative RepairSpec only: do \
NOT write code, patches, diffs, replacement files, or shell commands.

Given the red collision-mask overlay image (when supplied), the \
mathematical discrepancy metrics (V_r, IoU, Delta_x), the LCA DOM \
hierarchy with computed CSS, and the Node 2 authorized source files, \
identify the most likely root cause and a minimal, evidence-backed \
CSS/layout strategy.

Rules you must follow:
- target_file MUST be one of the Node 2 authorized files. Never \
target src/components/ui/* or invent file paths.
- Never invent selectors: every affected selector must come from the \
supplied element identifiers, LCA hierarchy, or computed CSS keys.
- desktop_preservation_constraints are mandatory: state explicitly \
what desktop behavior must remain intact when repairing a mobile \
defect, and vice versa. Never recommend hiding content, removing \
functionality, or global override hacks.
- forbidden_hacks must list techniques the repair must not use \
(forbidden policy includes: !important, z-index: 9999 and arbitrary \
z-index escalation, global selectors that restyle unrelated \
components, hiding or removing defective elements).
- Previous-attempt feedback, when supplied, is historical evidence \
only: do not treat its metrics as current measurements, do not repeat \
the failed approach without a justified correction, and preserve \
constraints it satisfied.
- Ground every claim in the supplied evidence (metrics, overlay, \
LCA, CSS, source). If the evidence is insufficient, say so in \
root_cause and keep the strategy conservative."""


class WonderError(Exception):
    pass


class WonderConfigurationError(WonderError):
    pass


class WonderResponseError(WonderError):
    pass


def _section(title: str, body: Any) -> str:
    if isinstance(body, str):
        text = body
    else:
        text = json.dumps(body, default=str, indent=1)[:6000]
    return f"## {title}\n{text}"


def build_diagnose_messages(
    context: Dict[str, Any],
    overlay_image: Optional[Tuple[bytes, str]] = None,
) -> List[Dict[str, Any]]:
    """Bounded multimodal messages with clearly separated sections."""
    overlay = context.get("overlay") or {}
    if overlay_image:
        image_note = (
            "The red collision-mask overlay image for the defective "
            "viewport is attached to this message. Red regions mark SAM "
            "collision/occlusion pixels; dashed cyan outlines are DOM "
            "boxes.")
    else:
        reason = overlay.get("reason") or overlay.get("status") or "missing"
        image_note = (
            f"Collision overlay image unavailable ({reason}). Diagnose "
            "from the metrics, LCA, and CSS evidence only; do not "
            "imagine pixels.")
    parts = [
        _section("Current defect and viewport", context.get("defect")),
        _section("Collision overlay image", image_note),
        _section("Current mathematical metrics",
                 context.get("metrics")),
        _section("LCA and computed CSS evidence", {
            "lca": context.get("lca"),
            "computed_styles": context.get("computed_styles"),
        }),
        _section("Node 2 authorized source files", {
            "targets": context.get("targets"),
            "triage_summary": context.get("triage_summary"),
            "source_context": context.get("sources"),
        }),
        _section("Desktop preservation requirements",
                 "Preserve desktop (1440px) layout and behavior exactly "
                 "when the defect is mobile (375px), and preserve "
                 "mobile layout when the defect is desktop. State the "
                 "concrete constraints in "
                 "desktop_preservation_constraints."),
    ]
    feedback = context.get("feedback")
    if feedback is not None:
        parts.append(_section(
            "Previous-attempt feedback (historical evidence only)",
            feedback))
    parts.append(_section(
        "Required output",
        "Return exactly one RepairSpec: root_cause (evidence-backed), "
        "affected_selectors (only selectors present in the supplied "
        "evidence), target_file (one authorized file), css_strategy "
        "(declarative layout/CSS approach, no code), "
        "desktop_preservation_constraints, forbidden_hacks."))
    text = "\n\n".join(parts)[:24000]
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    if overlay_image:
        image_bytes, media_type = overlay_image
        data_url = (f"data:{media_type};base64,"
                    + base64.b64encode(image_bytes).decode("ascii"))
        content.append({"type": "image_url",
                        "image_url": {"url": data_url}})
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}]


def json_schema_response_format() -> Dict[str, Any]:
    """Explicit ``response_format`` for ``chat.completions.create``.

    Used only when the SDK has no ``beta.chat.completions.parse``. Meta
    constrains decoding to the supplied schema on this path as well.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "RepairSpec",
            "schema": RepairSpec.model_json_schema(),
            "strict": False,
        },
    }


def to_repair_spec(parsed: Any) -> RepairSpec:
    """Validate parsed structured output into the domain contract."""
    try:
        if isinstance(parsed, BaseModel):
            return RepairSpec.model_validate(parsed.model_dump())
        if isinstance(parsed, str):
            return RepairSpec.model_validate_json(parsed)
        return RepairSpec.model_validate(parsed)
    except ValidationError as exc:
        raise WonderResponseError(
            f"invalid structured response: {exc.error_count()} errors")


class MuseWonderDiagnosisClient:
    """AsyncOpenAI-backed Muse Wonder client with bounded retries."""

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
            getattr(settings, "MUSE_WONDER_MODEL", "")
        self.timeout_seconds = float(
            timeout_seconds or getattr(settings, "WONDER_TIMEOUT_SECONDS", 30.0))
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_seconds = float(backoff_base_seconds)
        self._sleep = sleep or asyncio.sleep
        self._client = client  # injectable AsyncOpenAI (tests)

    def _get_client(self):
        if self._client is None:
            if not self.api_key or not self.base_url or not self.model:
                raise WonderConfigurationError(
                    "META_API_KEY, META_BASE_URL and MUSE_WONDER_MODEL "
                    "must be configured for Muse Wonder diagnosis")
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

    async def _parse_once(self, messages) -> RepairSpec:
        client = self._get_client()
        beta = getattr(client, "beta", None)
        completions = getattr(getattr(beta, "chat", None), "completions", None)
        parse = getattr(completions, "parse", None)
        if callable(parse):
            response = await parse(
                model=self.model, messages=messages,
                response_format=RepairSpec)
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise WonderResponseError("model refused diagnosis request")
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                content = getattr(message, "content", None)
                if content:
                    # Server-constrained output the SDK did not bind to
                    # the Pydantic type: validate explicitly, never
                    # trust raw text as a valid result.
                    return to_repair_spec(content)
                raise WonderResponseError("structured response missing")
            return to_repair_spec(parsed)
        # SDK without beta parse: same schema through create(), then
        # explicit local validation of the JSON content.
        response = await client.chat.completions.create(
            model=self.model, messages=messages,
            response_format=json_schema_response_format())
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise WonderResponseError("model refused diagnosis request")
        content = getattr(message, "content", None) or ""
        if not content.strip():
            raise WonderResponseError("structured response missing")
        return to_repair_spec(content)

    async def diagnose(
        self,
        context: Dict[str, Any],
        overlay_image: Optional[Tuple[bytes, str]] = None,
    ) -> RepairSpec:
        messages = build_diagnose_messages(context, overlay_image)
        attempt = 0
        while True:
            try:
                result = await self._parse_once(messages)
                logger.info("wonder diagnosis ok: target=%s",
                            result.target_file)
                return result
            except (WonderResponseError, WonderConfigurationError):
                raise  # validation/refusal/config: retrying will not help
            except Exception as exc:
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    raise WonderError(
                        f"Muse Wonder diagnosis failed: "
                        f"{type(exc).__name__}") from exc
                await self._sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1
