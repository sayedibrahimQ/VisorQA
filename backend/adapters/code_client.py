"""Muse Code patch client (Meta Model API, direct).

Muse Code is Meta's coding agent built on Muse Spark; on the Model
API the same Spark model serves the code role, so this client calls
``https://api.meta.ai/v1`` (model ``muse-spark-1.3`` by default) via
``AsyncOpenAI(api_key=META_API_KEY, base_url=META_BASE_URL)``. Diff
output is free text by design -- no structured-output mode produces
Unified Diffs -- so the raw response is returned verbatim and every
safety decision (normalization, parsing, authorization, BR-2/BR-4,
stale checks, atomic apply) happens in application code
(``backend.core.patch`` / ``backend.core.orchestrator``). Failures
raise :class:`CodeError` subclasses; the client never fabricates a
patch.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from backend.config import settings

logger = logging.getLogger("visorqa.code")

SYSTEM_PROMPT = """You are Muse Code, Meta's coding model. Return \
EXACTLY one Unified Diff and nothing else: no explanations, no \
Markdown fences, no commentary before or after.

Rules you must follow:
- Produce the SMALLEST change that fixes the diagnosed root cause in \
the single target file given. Do not rewrite the file or touch \
unrelated code.
- Headers must be exactly `--- a/<target path>` and \
`+++ b/<target path>` with correct @@ hunk counts against the exact \
original content supplied.
- Never target src/components/ui/* (shared primitives) or any file \
other than the target file.
- Desktop preservation is a HARD constraint: at 1440px the existing \
desktop layout and styles must keep working unless the RepairSpec \
explicitly requires a desktop change. For viewport-isolated defects \
prefer breakpoint-specific Tailwind classes or media-scoped CSS over \
changing shared base classes.
- Respect the supplied Tailwind configuration breakpoints and the \
classes already used in the file.
- Never use !important, z-index: 9999 (or arbitrary z-index \
escalation), global selector overrides, or hide/remove/disable \
content to make a collision disappear.
- If previous verification feedback reports a desktop regression, the \
new diff MUST correct that regression while keeping the fixes that \
already passed."""


class CodeError(Exception):
    pass


class CodeConfigurationError(CodeError):
    pass


class CodeResponseError(CodeError):
    pass


def build_patch_messages(context: Dict[str, Any]) -> List[Dict[str, str]]:
    spec = context.get("repair_spec") or {}
    sections = [
        "## Validated RepairSpec (Node 3 -- implement exactly this)\n"
        + json.dumps(spec, default=str, indent=1)[:8000],
        "## Defect and diagnostic evidence\n"
        + json.dumps(context.get("defect") or {}, default=str, indent=1),
        "## Desktop preservation (HARD constraint)\n"
        "The repair must preserve desktop layout at 1440px and mobile "
        "layout at 375px except where the defect requires change.\n"
        + json.dumps(spec.get("desktop_preservation_constraints") or [],
                     default=str),
        "## Tailwind configuration\n"
        + (context.get("tailwind_config")
           or "No tailwind.config found at the repository root; follow "
              "the class conventions already present in the file."),
    ]
    feedback = context.get("feedback")
    if feedback is not None:
        sections.append(
            "## Previous verification feedback (historical evidence)\n"
            "Address any reported regression (especially desktop) in "
            "this diff; do not repeat a failed approach unchanged.\n"
            + json.dumps(feedback, default=str, indent=1)[:6000])
    for entry in context.get("files") or []:
        if entry.get("status") == "ready":
            sections.append(
                f"## File: {entry['path']} ({entry.get('language')}, "
                f"sha256 {entry.get('sha256')})\n"
                f"Exact original content:\n{entry.get('content')}")
        else:
            sections.append(
                f"## File: {entry.get('path')} -- content unavailable "
                f"({entry.get('reason')})")
    sections.append(
        f"## Output requirement\nReturn one Unified Diff for "
        f"{context.get('target_file')} ONLY, based on the exact "
        "original content above. No prose, no fences.")
    text = "\n\n".join(sections)[:60000]
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}]


class MuseCodePatchClient:
    """AsyncOpenAI-backed Muse Code client with bounded retries."""

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
            getattr(settings, "MUSE_CODE_MODEL", "")
        self.timeout_seconds = float(
            timeout_seconds or getattr(settings, "CODE_TIMEOUT_SECONDS", 30.0))
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_seconds = float(backoff_base_seconds)
        self._sleep = sleep or asyncio.sleep
        self._client = client  # injectable AsyncOpenAI (tests)

    def _get_client(self):
        if self._client is None:
            if not self.api_key or not self.base_url or not self.model:
                raise CodeConfigurationError(
                    "META_API_KEY, META_BASE_URL and MUSE_CODE_MODEL "
                    "must be configured for Muse Code patching")
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url,
                timeout=self.timeout_seconds, max_retries=0)
        return self._client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        # Retry transient failures only: 429/5xx, timeouts, connection
        # errors. Auth (401/403) and malformed requests (400) are
        # never retried.
        status = getattr(exc, "status_code", None)
        if status is not None:
            return status == 429 or status >= 500
        name = type(exc).__name__
        return any(k in name for k in ("Timeout", "RateLimit", "Connection"))

    async def _create_once(self, messages) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.model, messages=messages)
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise CodeResponseError("model refused patch request")
        content = getattr(message, "content", None) or ""
        if not content.strip():
            raise CodeResponseError("empty patch response")
        return content

    async def generate_diff(self, context: Dict[str, Any]) -> str:
        """Raw model text (may be fenced); validated downstream."""
        messages = build_patch_messages(context)
        attempt = 0
        while True:
            try:
                result = await self._create_once(messages)
                logger.info("code patch response: %d chars", len(result))
                return result
            except (CodeResponseError, CodeConfigurationError):
                raise  # refusal/empty/config: retrying will not help
            except Exception as exc:
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    raise CodeError(
                        f"Muse Code patch failed: {type(exc).__name__}"
                    ) from exc
                await self._sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1
