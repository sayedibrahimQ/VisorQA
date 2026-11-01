"""Honest telemetry: no synthetic screenshots, metrics, anomalies, or runs.

Regression for the fake-capture purge: every screenshot/metric must come
from a real Playwright capture. Missing evidence stays missing (null /
absent), never a fabricated V_r = 0.62, visor-el-04 anomaly, seed run,
or demo run.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from backend.core.artifacts import (
    ArtifactStore,
    build_run_payload,
    capture_sense_artifacts,
    persist_run_telemetry,
)
from backend.core.state import AgentState


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (375, 812), (24, 26, 32)).save(buf, format="PNG")
    return buf.getvalue()


def test_synthetic_generator_modules_are_gone():
    assert importlib.util.find_spec("backend.core.visual_renderer") is None
    assert importlib.util.find_spec("backend.db.seed") is None


def test_payload_without_anomalies_invents_nothing():
    payload = build_run_payload(
        {"id": "run-honest-1", "status": "QUEUED", "pr_number": 0}, [], [], [])
    assert payload["anomalies"] == []
    assert payload["anomalies_count"] == 0
    baseline = payload["attempts"][0]
    assert baseline["element_metrics"] == []
    assert baseline["b_dom_boxes"] == {}
    assert baseline["viewport_summary"]["mobile"]["v_r"] is None
    assert baseline["screenshots"]["mobile"]["before_url"] is None
    # No fabricated strike for a run that never executed one.
    assert len(payload["attempts"]) == 1


def test_resolved_run_without_attempts_invents_no_strike_or_diff():
    payload = build_run_payload(
        {"id": "run-honest-2", "status": "RESOLVED", "is_resolved": True}, [], [], [])
    assert len(payload["attempts"]) == 1
    assert payload["attempts"][0]["patch_telemetry"]["unified_diff"] is None


def test_capture_without_real_bytes_writes_nothing(tmp_path):
    store = ArtifactStore(root=tmp_path)
    entries = capture_sense_artifacts(
        "run-honest-3", 0, {"mobile": {}, "desktop": {}}, [], store=store)
    assert entries == []
    assert not list(tmp_path.rglob("*.png"))


def test_capture_with_real_bytes_marks_not_synthetic(tmp_path):
    store = ArtifactStore(root=tmp_path)
    entries = capture_sense_artifacts(
        "run-honest-4", 0,
        {"mobile": {"screenshot": _png_bytes(), "masks": []}, "desktop": {}},
        [], store=store)
    kinds = {(e["viewport"], e["kind"]) for e in entries}
    assert ("mobile", "screenshot_before") in kinds
    assert ("desktop", "screenshot_before") not in kinds
    assert all(e["synthetic"] is False for e in entries)
    assert all(Path(e["path"]).is_file() for e in entries)


def test_persist_without_anomalies_invents_nothing(tmp_path):
    store = ArtifactStore(root=tmp_path)
    state = AgentState(run_id="run-honest-5", repo_name="org/repo",
                       pr_number=3, branch="feat/x")
    record = persist_run_telemetry(state, store=store)
    assert record["anomalies"] == []
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.asyncio
async def test_unknown_run_details_is_404_not_demo():
    from backend.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/runs/run-honest-unknown")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sense_without_geometry_fabricates_nothing():
    from backend.core.orchestrator import sense_with_playwright_and_sam

    class EmptySandbox:
        worktree_enabled = False

        async def extract_dom_geometry(self, w, h):
            return []

        async def capture_screenshot(self, w, h):
            return b""

    state = AgentState(run_id="run-honest-6", repo_name="org/repo",
                       pr_number=1, branch="feat/x")
    out = await sense_with_playwright_and_sam(state, sandbox_runner=EmptySandbox())
    assert out.anomalies == []
    spec = out.repair_spec if isinstance(out.repair_spec, dict) else {}
    assert spec.get("sense_status") == "capture_failed"


def test_b_dom_includes_all_sensed_elements_not_just_defects():
    sensed = [
        {"element_id": eid, "bounding_box": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 10.0},
         "viewport": "375px"}
        for eid in ("visor-el-01", "visor-el-02", "visor-el-04", "visor-el-09")
    ]
    payload = build_run_payload(
        {"id": "run-honest-7", "status": "RESOLVED", "is_resolved": True,
         "repair_spec": {"baseline_sensed_elements": sensed}},
        [], [], [])
    boxes = payload["attempts"][0]["b_dom_boxes"]
    assert set(boxes) >= {"visor-el-01", "visor-el-02", "visor-el-04", "visor-el-09"}
    assert payload["anomalies"] == []
