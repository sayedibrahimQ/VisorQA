"""Tests for the point-guided SAM 3.1 client with a mocked endpoint.

No live endpoint or credentials are used. The Meta wire format is an
isolated adapter assumption (see backend.adapters.sam31 docstring).
"""
import asyncio
import base64
import io
import json

import numpy as np
import pytest
from PIL import Image

from backend.adapters.sam31 import (
    MetaSAMTransport,
    PointGuidedSAM31Client,
    SAMConfigurationError,
    SAMInputError,
    SAMTransportError,
    build_prompts,
)
from backend.browser.schemas import ElementGeometry
from backend.core.state import DOMBoundingBox

W, H = 100, 80


def png_bytes(size=(W, H), color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def mask_list(rect=(0, 0, 5, 5), shape=(H, W)):
    m = np.zeros(shape, dtype=int)
    m[rect[1]:rect[3], rect[0]:rect[2]] = 1
    return m.tolist()


def el(eid, x=0, y=0, w=20, h=10, cx=None, cy=None):
    return {"visor_el_id": eid,
            "B_DOM": {"x": x, "y": y, "width": w, "height": h},
            "c_x": x + w / 2 if cx is None else cx,
            "c_y": y + h / 2 if cy is None else cy}


class FakeTransport:
    """Records batches; behavior maps prompt ids -> raw result dicts."""

    def __init__(self, behavior=None, delay=0.0):
        self.calls = []
        self.behavior = behavior or (
            lambda prompts: [
                {"visor_el_id": p.visor_el_id,
                 "mask": mask_list((0, 0, 3, 3))} for p in prompts])
        self.delay = delay

    async def submit_batch(self, image_b64, prompts, request_id):
        self.calls.append((image_b64, list(prompts), request_id))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.behavior(prompts)


def client(transport, **kw):
    kw.setdefault("sleep", lambda s: asyncio.sleep(0))
    return PointGuidedSAM31Client(api_key="test-key", transport=transport,
                                  **kw)


# --- request construction ------------------------------------------------------

async def test_meta_transport_request_construction():
    import httpx
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [
            {"visor_el_id": "el-1", "mask": mask_list()}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="https://meta.example")
    transport = MetaSAMTransport("secret-key", "https://meta.example",
                                 "/sam/segment", client=http)
    prompts, errors = build_prompts([el("el-1", 10, 10, 20, 10)], W, H)
    assert not errors
    results = await transport.submit_batch(
        base64.b64encode(png_bytes()).decode(), prompts, "req-1")
    body = captured["body"]
    assert captured["auth"] == "Bearer secret-key"
    assert body["prompt_mode"] == "point_box"
    assert body["request_id"] == "req-1"
    assert body["prompts"] == [{
        "visor_el_id": "el-1", "center_point": [20.0, 15.0],
        "bounding_box": [10.0, 10.0, 20.0, 10.0]}]
    assert base64.b64decode(body["image_png_base64"]) == png_bytes()
    assert results[0]["visor_el_id"] == "el-1"
    assert "secret-key" not in json.dumps(body)


async def test_multiple_elements_one_batch():
    fake = FakeTransport()
    res = await client(fake).segment_viewport(
        png_bytes(), [el("a"), el("b", x=40), el("c", x=60)], "mobile")
    assert res.ok and len(fake.calls) == 1 and res.batches_sent == 1
    assert len(fake.calls[0][1]) == 3


# --- 1:1 binding ------------------------------------------------------------------

async def test_binding_survives_shuffled_response():
    def shuffled(prompts):
        out = [{"visor_el_id": p.visor_el_id,
                "mask": mask_list((i * 10, 0, i * 10 + 2, 2))}
               for i, p in enumerate(prompts)]
        return list(reversed(out))  # response order must not matter

    fake = FakeTransport(shuffled)
    res = await client(fake).segment_viewport(
        png_bytes(), [el("a"), el("b", x=40), el("c", x=60)])
    by_id = {e.visor_el_id: e for e in res.elements}
    # Each element keeps its own mask (distinct column offsets).
    assert by_id["a"].mask[:, 0].sum() > 0 and by_id["a"].mask[:, 10].sum() == 0
    assert by_id["b"].mask[:, 10].sum() > 0
    assert by_id["c"].mask[:, 20].sum() > 0


async def test_missing_duplicate_unexpected_malformed():
    def behavior(prompts):
        return [
            {"visor_el_id": "a", "mask": mask_list()},
            {"visor_el_id": "b", "mask": mask_list()},  # duplicate for b
            {"visor_el_id": "b", "mask": mask_list((5, 5, 8, 8))},
            {"visor_el_id": "zzz-unexpected", "mask": mask_list()},
            {"visor_el_id": "d", "mask": [[1, 2], [3, 4]]},  # wrong shape
        ]  # c missing entirely

    res = await client(FakeTransport(behavior)).segment_viewport(
        png_bytes(), [el("a"), el("b", x=30), el("c", x=50), el("d", x=70)])
    by_id = {e.visor_el_id: e for e in res.elements}
    assert by_id["a"].status == "ok"
    assert by_id["b"].error == "duplicate_result" and by_id["b"].mask is None
    assert by_id["c"].error == "missing_result" and by_id["c"].mask is None
    assert by_id["d"].error.startswith("malformed_mask")
    assert res.unexpected_ids == ["zzz-unexpected"]
    assert not res.ok
    # No neighbouring mask was substituted for b/c/d.
    assert res.masks_by_id["c"] is None


# --- coordinates / validation -------------------------------------------------------

def test_prompt_clipping_and_offscreen():
    prompts, errors = build_prompts([
        el("partial", x=-10, y=0, w=30, h=10, cx=-5, cy=5),
        el("outside", x=500, y=0, w=20, h=10),
        el("bad", x=0, y=0, w=0, h=10),
        el("nan", x=float("nan"), y=0, w=10, h=10),
        {"B_DOM": {"x": 0, "y": 0, "width": 5, "height": 5}},
    ], W, H)
    by_id = {p.visor_el_id: p for p in prompts}
    assert by_id["partial"].bounding_box == (0.0, 0.0, 20.0, 10.0)
    assert by_id["partial"].center_point == (0.0, 5.0)  # clamped inside
    assert by_id["partial"].clipped is True
    assert errors["outside"] == "off_screen"
    assert errors["bad"] == "invalid_box" and errors["nan"] == "invalid_box"

    dup_prompts, dup_errors = build_prompts(
        [el("dup"), el("dup", x=40)], W, H)
    assert dup_errors["dup"] == "duplicate_element_id"
    assert dup_prompts == []  # ambiguous duplicates are never sent


def test_normalized_coordinate_adapter():
    prompts, _ = build_prompts([el("a", 10, 20, 40, 20)], W, H)
    norm = MetaSAMTransport.to_normalized(prompts[0], W, H)
    assert norm["center_point"] == pytest.approx([0.3, 0.375])
    assert norm["bounding_box"] == pytest.approx([0.1, 0.25, 0.4, 0.25])


async def test_prompts_from_element_geometry_objects():
    geo = [ElementGeometry(visor_el_id="g1",
                           B_DOM=DOMBoundingBox(x=0, y=0, width=20, height=10),
                           c_x=10.0, c_y=5.0)]
    res = await client(FakeTransport()).segment_viewport(png_bytes(), geo)
    assert res.ok and res.elements[0].visor_el_id == "g1"


async def test_invalid_screenshot_rejected():
    with pytest.raises(SAMInputError):
        await client(FakeTransport()).segment_viewport(b"not a png", [el("a")])


# --- batch limits / partial failure -----------------------------------------------------

async def test_batch_limit_chunks_without_dropping():
    fake = FakeTransport()
    els = [el(f"e{i}", x=i * 5, w=10) for i in range(5)]
    res = await client(fake, max_batch_size=2).segment_viewport(png_bytes(), els)
    assert res.ok and len(res.elements) == 5 and len(fake.calls) == 3
    assert res.batches_sent == 3


async def test_partial_batch_failure_isolated():
    def behavior(prompts):
        ids = [p.visor_el_id for p in prompts]
        if "bad-1" in ids:
            raise SAMTransportError("boom", retryable=False)
        return [{"visor_el_id": p.visor_el_id, "mask": mask_list()}
                for p in prompts]

    class FlakyTransport(FakeTransport):
        async def submit_batch(self, image_b64, prompts, request_id):
            self.calls.append((image_b64, list(prompts), request_id))
            return self.behavior(prompts)

    els = [el("good-1"), el("bad-1", x=30), el("good-2", x=60)]
    res = await client(FlakyTransport(behavior), max_batch_size=1) \
        .segment_viewport(png_bytes(), els)
    by_id = {e.visor_el_id: e for e in res.elements}
    assert by_id["good-1"].status == "ok" and by_id["good-2"].status == "ok"
    assert by_id["bad-1"].status == "error" and "boom" in by_id["bad-1"].error


# --- retries / auth / deadline / cancellation ------------------------------------------------

async def test_retry_only_transient_with_backoff():
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    class TwiceFlaky(FakeTransport):
        async def submit_batch(self, image_b64, prompts, request_id):
            self.calls.append((image_b64, list(prompts), request_id))
            if len(self.calls) < 3:
                raise SAMTransportError("HTTP 503", status_code=503,
                                        retryable=True)
            return [{"visor_el_id": p.visor_el_id, "mask": mask_list()}
                    for p in prompts]

    res = await client(TwiceFlaky(), max_retries=2, sleep=fake_sleep,
                       backoff_base_seconds=0.1).segment_viewport(
        png_bytes(), [el("a")])
    assert res.ok and sleeps == [0.1, 0.2]

    class AuthFail(FakeTransport):
        async def submit_batch(self, image_b64, prompts, request_id):
            self.calls.append((image_b64, list(prompts), request_id))
            raise SAMTransportError("authentication failed (HTTP 401)",
                                    status_code=401, retryable=False)

    auth = AuthFail()
    res = await client(auth, max_retries=3).segment_viewport(
        png_bytes(), [el("a")])
    assert len(auth.calls) == 1  # auth failures are never retried
    assert res.elements[0].status == "error"


async def test_unconfigured_endpoint_fails_per_element():
    c = PointGuidedSAM31Client(api_key="", base_url="", endpoint_path="")
    res = await c.segment_viewport(png_bytes(), [el("a")])
    assert res.elements[0].status == "error"
    assert "SAMConfigurationError" in res.elements[0].error


async def test_deadline_exceeded_is_clear_failure():
    res = await client(FakeTransport(delay=0.5), deadline_seconds=0.05) \
        .segment_viewport(png_bytes(), [el("a")])
    assert res.elements[0].status == "error"
    assert "deadline" in res.elements[0].error


async def test_cancellation_propagates():
    task = asyncio.create_task(
        client(FakeTransport(delay=5.0)).segment_viewport(
            png_bytes(), [el("a")]))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- no-grid regression + latency ---------------------------------------------------------------

async def test_never_uses_unprompted_grid_mode():
    import backend.adapters.sam31 as module
    import inspect
    source = inspect.getsource(module)
    # No grid/everything invocation machinery exists in the client.
    assert not hasattr(module.PointGuidedSAM31Client, "segment_grid")
    assert "grid_points" not in source and "everything_mode" not in source
    fake = FakeTransport()
    await client(fake).segment_viewport(png_bytes(), [el("a"), el("b", x=40)])
    for _, prompts, _ in fake.calls:
        assert prompts, "every request must carry explicit prompts"
        assert all(p.visor_el_id for p in prompts)
        assert all(len(p.bounding_box) == 4 for p in prompts)


async def test_latency_instrumentation_separates_phases():
    res = await client(FakeTransport(delay=0.02)).segment_viewport(
        png_bytes(), [el("a")], "desktop")
    lat = res.latency
    assert lat.prepare_ms >= 0 and lat.postprocess_ms >= 0
    assert lat.inference_ms >= 10  # transport delay lands in inference only
    assert lat.total_ms == pytest.approx(
        lat.prepare_ms + lat.inference_ms + lat.postprocess_ms)
    assert res.viewport == "desktop" and res.request_id
