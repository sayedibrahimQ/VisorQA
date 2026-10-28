"""Async point-guided SAM 3.1 client (Meta endpoint, DOM-guided prompts).

Verified from project documentation (TDS/ADR-003/SRS FR-02, TC-3)
----------------------------------------------------------------
* Meta endpoints are called via ``AsyncOpenAI(api_key=META_API_KEY,
  base_url=META_BASE_URL)``; this client uses the same base URL and
  bearer credential through an ``httpx`` transport (the OpenAI SDK's own
  HTTP layer), keeping one async stack.
* Every prompt is DOM-guided: center point ``(c_x, c_y)`` + ``B_DOM``
  for a specific ``visor-el-id``; 1:1 element-to-mask binding is the
  application contract; unprompted 64x64 "Everything Mode" grid
  inference is prohibited and is never invoked or used as a fallback.

NOT verified (no source in this repo or its docs states them)
-------------------------------------------------------------
* The concrete SAM segmentation endpoint path, model identifier,
  request field names, batch-size limit, and mask wire encoding.
Those unknowns are isolated in :class:`MetaSAMTransport`: its JSON
payload (see ``_build_payload``) is an explicit adapter assumption.
When Meta publishes the real contract, only that class should change.
The transport raises :class:`SAMConfigurationError` unless both
``META_BASE_URL`` and ``SAM31_ENDPOINT_PATH`` are configured, rather
than guessing a URL.

Coordinate convention (adapter assumption, consistent in-repo)
--------------------------------------------------------------
Screenshots are uploaded at native viewport size (no resizing), and
prompts use screenshot pixel coordinates with a top-left origin --
exactly the ``B_DOM`` convention of ``backend.browser`` /
``backend.core.vision_math``. Partially off-screen boxes are clipped to
the screenshot and their centers clamped into the clipped box (flagged
``clipped=True``); fully off-screen elements fail per-element and are
never sent. ``to_normalized`` is provided in the transport if the real
endpoint requires 0..1 coordinates.
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple
from uuid import uuid4

import numpy as np
from pydantic import BaseModel

from backend.config import settings

PROMPT_MODE = "point_box"  # the only mode this client ever sends


class SAMError(Exception):
    """Base class for SAM client failures."""


class SAMConfigurationError(SAMError):
    """Endpoint/credentials not configured (nothing was sent)."""


class SAMInputError(SAMError):
    """Invalid screenshot or prompt set (nothing was sent)."""


class SAMTransportError(SAMError):
    def __init__(self, message: str, status_code: Optional[int] = None,
                 retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Typed contracts
# ---------------------------------------------------------------------------

class ElementPrompt(BaseModel):
    """One explicit point-plus-box prompt bound to a visor-el-id."""

    visor_el_id: str
    center_point: Tuple[float, float]  # (c_x, c_y) screenshot pixels
    bounding_box: Tuple[float, float, float, float]  # B_DOM x, y, w, h
    clipped: bool = False


@dataclass
class ElementSegmentation:
    visor_el_id: str
    viewport: str = ""
    mask: Optional[np.ndarray] = None
    status: str = "error"  # ok | error
    error: Optional[str] = None
    clipped: bool = False


@dataclass
class LatencyBreakdown:
    """Phase timings in ms. ``inference_ms`` is the endpoint round-trip
    only (request transfer + server inference, as observed client-side);
    it is never conflated with total latency."""

    prepare_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.prepare_ms + self.inference_ms + self.postprocess_ms


@dataclass
class SegmentationBatchResult:
    viewport: str = ""
    elements: List[ElementSegmentation] = field(default_factory=list)
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    request_id: str = ""
    batches_sent: int = 0
    unexpected_ids: List[str] = field(default_factory=list)

    @property
    def masks_by_id(self) -> Dict[str, Optional[np.ndarray]]:
        return {e.visor_el_id: e.mask for e in self.elements}

    @property
    def ok(self) -> bool:
        return all(e.status == "ok" for e in self.elements)


class SAMTransport(Protocol):
    """Isolated endpoint adapter. One call = one batched image request."""

    async def submit_batch(
        self, image_png_base64: str, prompts: List[ElementPrompt],
        request_id: str,
    ) -> List[Dict[str, Any]]:
        """Return raw result dicts, each echoing ``visor_el_id``."""
        ...


# ---------------------------------------------------------------------------
# Prompt construction / validation
# ---------------------------------------------------------------------------

def build_prompts(
    elements: Sequence[Any], image_width: int, image_height: int
) -> Tuple[List[ElementPrompt], Dict[str, str]]:
    """Build validated prompts from ElementGeometry-like objects/dicts.

    Returns ``(prompts, errors)`` where errors maps visor_el_id (or a
    positional placeholder) to the per-element failure reason. Invalid,
    duplicate, and fully off-screen elements are excluded from prompts
    and reported, never silently dropped or sent.
    """
    prompts: List[ElementPrompt] = []
    errors: Dict[str, str] = {}
    seen: set = set()
    for idx, el in enumerate(elements or []):
        if isinstance(el, dict):
            eid = str(el.get("visor_el_id") or el.get("element_id") or "")
            box = el.get("B_DOM") or el.get("b_dom") or el.get("box") or {}
            cx, cy = el.get("c_x"), el.get("c_y")
            if isinstance(box, dict):
                bx, by, bw, bh = (box.get("x"), box.get("y"),
                                  box.get("width"), box.get("height"))
            else:
                bx, by, bw, bh = (getattr(box, "x", None), getattr(box, "y", None),
                                  getattr(box, "width", None),
                                  getattr(box, "height", None))
        else:
            eid = str(getattr(el, "visor_el_id", "") or "")
            b = getattr(el, "b_dom", None)
            bx = getattr(b, "x", None) if b else None
            by = getattr(b, "y", None) if b else None
            bw = getattr(b, "width", None) if b else None
            bh = getattr(b, "height", None) if b else None
            cx, cy = getattr(el, "c_x", None), getattr(el, "c_y", None)
        key = eid or f"<index-{idx}>"
        if not eid:
            errors[key] = "missing_element_id"
            continue
        if eid in seen:
            errors[eid] = "duplicate_element_id"
            # Ambiguous: withdraw the earlier prompt for this ID too.
            prompts[:] = [p for p in prompts if p.visor_el_id != eid]
            continue
        seen.add(eid)
        try:
            bx, by, bw, bh = float(bx), float(by), float(bw), float(bh)
            if cx is None or cy is None:
                cx, cy = bx + bw / 2.0, by + bh / 2.0
            cx, cy = float(cx), float(cy)
        except (TypeError, ValueError):
            errors[eid] = "invalid_box"
            continue
        if not all(math.isfinite(v) for v in (bx, by, bw, bh, cx, cy)) \
                or bw <= 0 or bh <= 0:
            errors[eid] = "invalid_box"
            continue
        # Clip box to screenshot bounds; clamp center into clipped box.
        x0, y0 = max(0.0, bx), max(0.0, by)
        x1, y1 = min(float(image_width), bx + bw), min(float(image_height), by + bh)
        if x1 <= x0 or y1 <= y0:
            errors[eid] = "off_screen"
            continue
        clipped = (x0, y0, x1, y1) != (bx, by, bx + bw, by + bh)
        ccx = min(max(cx, x0), x1)
        ccy = min(max(cy, y0), y1)
        clipped = clipped or (ccx, ccy) != (cx, cy)
        prompts.append(ElementPrompt(
            visor_el_id=eid, center_point=(ccx, ccy),
            bounding_box=(x0, y0, x1 - x0, y1 - y0), clipped=clipped))
    return prompts, errors


# ---------------------------------------------------------------------------
# Mask decoding (offloaded to a thread by the client)
# ---------------------------------------------------------------------------

def _decode_mask(raw: Any, shape: Tuple[int, int]) -> np.ndarray:
    if isinstance(raw, dict) and "mask_png_base64" in raw:
        from PIL import Image
        data = base64.b64decode(raw["mask_png_base64"])
        with Image.open(io.BytesIO(data)) as img:
            arr = np.asarray(img.convert("L"))
    elif isinstance(raw, dict) and "mask" in raw:
        arr = np.asarray(raw["mask"])
    else:
        raise SAMTransportError("malformed mask payload in response")
    if arr.ndim != 2:
        raise SAMTransportError(f"mask must be 2D, got {arr.shape}")
    if arr.shape != shape:
        raise SAMTransportError(
            f"mask shape {arr.shape} != screenshot shape {shape}")
    return (arr > 0).astype(np.uint8)


# ---------------------------------------------------------------------------
# Default Meta transport (adapter assumption isolated here)
# ---------------------------------------------------------------------------

class MetaSAMTransport:
    """HTTP transport to the configured Meta SAM endpoint.

    Assumed wire format (UNVERIFIED, see module docstring): POST JSON
    ``{request_id, prompt_mode: "point_box", image_png_base64,
    prompts: [{visor_el_id, center_point, bounding_box}]}`` with a
    bearer credential; response ``{results: [{visor_el_id, ...mask}]}``.
    """

    def __init__(self, api_key: str, base_url: str, endpoint_path: str,
                 timeout_seconds: float = 10.0, client: Any = None):
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._endpoint_path = endpoint_path or ""
        self._timeout = timeout_seconds
        self._client = client  # injectable httpx.AsyncClient (tests)
        self._owns_client = client is None

    @staticmethod
    def to_normalized(prompt: ElementPrompt, width: int,
                      height: int) -> Dict[str, Any]:
        """Adapter utility if the real endpoint wants 0..1 coordinates."""
        x, y, w, h = prompt.bounding_box
        return {"visor_el_id": prompt.visor_el_id,
                "center_point": [prompt.center_point[0] / width,
                                 prompt.center_point[1] / height],
                "bounding_box": [x / width, y / height, w / width, h / height]}

    def _build_payload(self, image_b64: str, prompts, request_id: str):
        return {
            "request_id": request_id,  # stable across retries (dedup)
            "prompt_mode": PROMPT_MODE,
            "image_png_base64": image_b64,
            "prompts": [
                {"visor_el_id": p.visor_el_id,
                 "center_point": list(p.center_point),
                 "bounding_box": list(p.bounding_box)}
                for p in prompts
            ],
        }

    async def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def submit_batch(self, image_png_base64, prompts, request_id):
        if not self._base_url or not self._endpoint_path:
            raise SAMConfigurationError(
                "META_BASE_URL and SAM31_ENDPOINT_PATH must be configured "
                "for the Meta SAM endpoint (no default URL is assumed)")
        if not self._api_key:
            raise SAMConfigurationError("META_API_KEY is not configured")
        client = await self._get_client()
        try:
            resp = await client.post(
                self._endpoint_path,
                json=self._build_payload(image_png_base64, prompts, request_id),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except Exception as exc:  # httpx timeouts/connect errors
            import httpx
            if isinstance(exc, httpx.TimeoutException):
                raise SAMTransportError("endpoint timeout", retryable=True)
            if isinstance(exc, httpx.HTTPError):
                raise SAMTransportError(f"network error: {type(exc).__name__}",
                                        retryable=True)
            raise
        if resp.status_code in (401, 403):
            raise SAMTransportError(
                f"authentication failed (HTTP {resp.status_code})",
                status_code=resp.status_code, retryable=False)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise SAMTransportError(
                f"transient endpoint error (HTTP {resp.status_code})",
                status_code=resp.status_code, retryable=True)
        if resp.status_code != 200:
            raise SAMTransportError(
                f"endpoint error (HTTP {resp.status_code})",
                status_code=resp.status_code, retryable=False)
        try:
            body = resp.json()
            results = body["results"]
            if not isinstance(results, list):
                raise TypeError("results is not a list")
            return results
        except Exception:
            raise SAMTransportError("malformed endpoint response")


# ---------------------------------------------------------------------------
# Point-guided client
# ---------------------------------------------------------------------------

class PointGuidedSAM31Client:
    """Batched, point-guided SAM 3.1 segmentation with 1:1 binding.

    Binding rule: masks are matched to elements solely by the
    ``visor_el_id`` echoed in each result. Response ordering is never
    trusted; missing, duplicate, or unexpected IDs become explicit
    per-element errors and a mask is never reassigned to a neighbour.
    Only prompts that were actually sent can produce ``ok`` results.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        transport: Optional[SAMTransport] = None,
        max_batch_size: Optional[int] = None,
        max_concurrency: int = 2,
        max_retries: int = 2,
        timeout_seconds: Optional[float] = None,
        deadline_seconds: Optional[float] = None,
        backoff_base_seconds: float = 0.2,
        sleep: Any = None,
    ):
        self.api_key = api_key if api_key is not None else settings.META_API_KEY
        self.base_url = base_url if base_url is not None else \
            getattr(settings, "META_BASE_URL", "")
        self.endpoint_path = endpoint_path if endpoint_path is not None else \
            getattr(settings, "SAM31_ENDPOINT_PATH", "")
        self.max_batch_size = max(1, int(
            max_batch_size or getattr(settings, "SAM31_MAX_BATCH_SIZE", 40)))
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_retries = max(0, int(max_retries))
        self.timeout_seconds = float(
            timeout_seconds or getattr(settings, "SAM31_TIMEOUT_SECONDS", 10.0))
        self.deadline_seconds = deadline_seconds
        self.backoff_base_seconds = float(backoff_base_seconds)
        self._sleep = sleep or asyncio.sleep
        self.transport = transport or MetaSAMTransport(
            self.api_key, self.base_url, self.endpoint_path,
            timeout_seconds=self.timeout_seconds)

    async def aclose(self) -> None:
        close = getattr(self.transport, "aclose", None)
        if close is not None:
            await close()

    async def __aenter__(self) -> "PointGuidedSAM31Client":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _submit_with_retries(self, image_b64, prompts, request_id):
        attempt = 0
        while True:
            try:
                return await self.transport.submit_batch(
                    image_b64, prompts, request_id)
            except SAMTransportError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                # Bounded exponential backoff; CancelledError propagates.
                await self._sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1

    async def segment_viewport(
        self,
        screenshot_png: bytes,
        elements: Sequence[Any],
        viewport: str = "",
    ) -> SegmentationBatchResult:
        """Segment one viewport screenshot for the given elements."""
        request_id = uuid4().hex
        result = SegmentationBatchResult(viewport=viewport,
                                         request_id=request_id)
        t0 = time.perf_counter()
        # --- prepare: validate screenshot + prompts (CPU-light) ---
        dims = await asyncio.to_thread(_png_dimensions, screenshot_png)
        if dims is None:
            raise SAMInputError("screenshot is not a valid PNG image")
        width, height = dims
        prompts, errors = build_prompts(elements, width, height)
        by_id: Dict[str, ElementSegmentation] = {}
        for eid, reason in errors.items():
            by_id[eid] = ElementSegmentation(
                visor_el_id=eid, viewport=viewport, error=reason)
        prompt_by_id = {p.visor_el_id: p for p in prompts}
        result.latency.prepare_ms = (time.perf_counter() - t0) * 1000.0

        if not prompts:
            result.elements = [by_id[k] for k in errors]
            return result

        # Encode once; the same payload image is reused across batches.
        image_b64 = base64.b64encode(screenshot_png).decode("ascii")
        chunks = [prompts[i:i + self.max_batch_size]
                  for i in range(0, len(prompts), self.max_batch_size)]
        result.batches_sent = len(chunks)
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_chunk(chunk):
            async with semaphore:
                return await self._submit_with_retries(
                    image_b64, chunk, request_id)

        # --- inference: endpoint round-trips (batched, bounded) ---
        t1 = time.perf_counter()
        try:
            if self.deadline_seconds:
                chunk_results = await asyncio.wait_for(
                    asyncio.gather(*(run_chunk(c) for c in chunks),
                                   return_exceptions=True),
                    timeout=self.deadline_seconds)
            else:
                chunk_results = await asyncio.gather(
                    *(run_chunk(c) for c in chunks),
                    return_exceptions=True)
        except asyncio.TimeoutError:
            chunk_results = [SAMTransportError(
                f"deadline {self.deadline_seconds}s exceeded",
                retryable=False)] * len(chunks)
        result.latency.inference_ms = (time.perf_counter() - t1) * 1000.0

        # --- postprocess: bind masks by echoed visor_el_id only ---
        t2 = time.perf_counter()
        sent_ids = [p.visor_el_id for c in chunks for p in c]
        raw_by_chunk: Dict[str, Dict[str, Any]] = {}
        chunk_error: Dict[str, str] = {}
        for chunk, raw in zip(chunks, chunk_results):
            if isinstance(raw, Exception):
                for p in chunk:
                    chunk_error[p.visor_el_id] = (
                        f"{type(raw).__name__}: {raw}"[:200])
                continue
            seen_counts: Dict[str, int] = {}
            for item in raw or []:
                rid = str(item.get("visor_el_id") or "") \
                    if isinstance(item, dict) else ""
                if rid not in sent_ids:
                    if rid and rid not in result.unexpected_ids:
                        result.unexpected_ids.append(rid)
                    continue
                seen_counts[rid] = seen_counts.get(rid, 0) + 1
                raw_by_chunk.setdefault(rid, item)
            for rid, count in seen_counts.items():
                if count > 1:
                    # Ambiguous duplicate: refuse to pick one.
                    raw_by_chunk.pop(rid, None)
                    chunk_error[rid] = "duplicate_result"
        for eid in sent_ids:
            if eid in chunk_error:
                by_id[eid] = ElementSegmentation(
                    visor_el_id=eid, viewport=viewport,
                    error=chunk_error[eid],
                    clipped=prompt_by_id[eid].clipped)
            elif eid in raw_by_chunk:
                try:
                    mask = await asyncio.to_thread(
                        _decode_mask, raw_by_chunk[eid], (height, width))
                    by_id[eid] = ElementSegmentation(
                        visor_el_id=eid, viewport=viewport, mask=mask,
                        status="ok", clipped=prompt_by_id[eid].clipped)
                except Exception as exc:
                    by_id[eid] = ElementSegmentation(
                        visor_el_id=eid, viewport=viewport,
                        error=f"malformed_mask: {exc}"[:200],
                        clipped=prompt_by_id[eid].clipped)
            else:
                by_id[eid] = ElementSegmentation(
                    visor_el_id=eid, viewport=viewport,
                    error="missing_result",
                    clipped=prompt_by_id[eid].clipped)
        result.latency.postprocess_ms = (time.perf_counter() - t2) * 1000.0
        # Stable output order: original element order, errors included.
        ordered: List[ElementSegmentation] = []
        emitted: set = set()
        for el in elements or []:
            eid = el.get("visor_el_id") if isinstance(el, dict) else \
                getattr(el, "visor_el_id", None)
            if eid and eid in by_id and eid not in emitted:
                ordered.append(by_id[eid])
                emitted.add(eid)
        for eid, seg in by_id.items():  # any remainder (defensive)
            if eid not in emitted:
                ordered.append(seg)
        result.elements = ordered
        return result


def _png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if not data or len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    import struct
    return struct.unpack(">II", data[16:24])
