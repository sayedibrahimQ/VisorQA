"""Workstream 1: artifact persistence, rich run details, verification telemetry.

Covers: deterministic on-disk persistence per run/attempt/viewport, the
rich GET /api/runs/{id} payload with valid artifact URLs, WS sequence
stamps, deterministic seeding, and pipeline -> persistence end to end
(stub adapters, no network/credentials).
"""
import json
from pathlib import Path

import httpx
import pytest

from backend.core.artifacts import (
    ArtifactStore,
    build_run_payload,
    persist_run_telemetry,
    strike_decision,
    viewport_key,
)
from backend.core.orchestrator import run_visor_agent
from backend.core.state import AgentState, Anomaly, DOMBoundingBox, DefectType
from backend.db.seed import seed_canonical_runs, seed_if_empty


def make_state(**kwargs) -> AgentState:
    defaults = {
        "run_id": "ws1-persist-test",
        "repo_name": "sayedibrahimQ/VisorQA",
        "pr_number": 42,
        "branch": "feat/ws1",
        "commit_sha": "a1b2c3d4",
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


def sample_anomaly() -> Anomaly:
    return Anomaly(
        element_id="visor-el-sample",
        defect_type=DefectType.OCCLUSION,
        visibility_ratio=0.55,
        iou_score=0.0,
        bleed_px=0.0,
        bounding_box=DOMBoundingBox(x=0, y=0, width=100, height=50),
        viewport="375px",
    )


# ---------------------------------------------------------------------------
# Artifact store
# ---------------------------------------------------------------------------

def test_store_deterministic_layout_and_urls(tmp_path):
    store = ArtifactStore(root=tmp_path)
    saved = store.save_bytes("run-abc", 1, "mobile", "screenshot_after.png", b"\x89PNG")
    assert saved["url"] == "/api/artifacts/run-abc/attempt_1/375x812/screenshot_after.png"
    assert Path(saved["path"]).read_bytes() == b"\x89PNG"
    saved = store.save_bytes("run-abc", 0, "desktop", "sam_mask.png", b"mask")
    assert saved["url"] == "/api/artifacts/run-abc/attempt_0/1440x900/sam_mask.png"
    with pytest.raises(ValueError):
        store.save_bytes("../escape", 0, "mobile", "x.png", b"no")
    with pytest.raises(ValueError):
        store.save_bytes("run-abc", 4, "mobile", "x.png", b"no")
    assert viewport_key("375px") == "375x812"
    assert viewport_key("desktop") == "1440x900"


def test_strike_decisions():
    assert strike_decision(True, 1) == "RESOLVED"
    assert strike_decision(False, 1) == "RETRY_NEXT_STRIKE"
    assert strike_decision(False, 2) == "RETRY_NEXT_STRIKE"
    assert strike_decision(False, 3) == "FALLBACK_BEST_PATCH"
    assert strike_decision(None, 3) == "FALLBACK_BEST_PATCH"


# ---------------------------------------------------------------------------
# Pipeline -> persistence (stub adapters, deterministic FSM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_persists_complete_telemetry(tmp_path):
    state = make_state(anomalies=[sample_anomaly()])
    final = await run_visor_agent(state)
    assert final.is_resolved is True

    store = ArtifactStore(root=tmp_path)
    record = persist_run_telemetry(final, store=store)

    # Registry + per-attempt/viewport telemetry files exist on disk.
    index = json.loads((tmp_path / "index.json").read_text())
    assert "ws1-persist-test" in index["runs"]
    for viewport in ("375x812", "1440x900"):
        for attempt in (0, 1):
            tele = tmp_path / "ws1-persist-test" / f"attempt_{attempt}" / viewport / "telemetry.json"
            assert tele.is_file(), tele

    payload = build_run_payload(record, record["anomalies"],
                                  record["attempts_raw"], record["artifacts"])
    assert payload["attempts"][0]["kind"] == "baseline"
    assert payload["attempts"][0]["b_dom_boxes"]["visor-el-sample"]["width"] == 100.0
    assert payload["attempts"][0]["element_metrics"][0]["trap_fired"] == "vr_below_0.85"

    strike = payload["attempts"][1]
    assert strike["attempt_number"] == 1
    assert strike["repair_spec"] is not None
    assert strike["repair_spec"]["target_file"]
    assert strike["patch_telemetry"]["unified_diff"]
    assert strike["patch_telemetry"]["diff_sha256"]
    assert strike["patch_telemetry"]["guardrails"]["br4_no_hacks"] is True
    assert strike["verification_feedback"]["strike_decision"] == "RESOLVED"
    assert strike["viewport_summary"]["mobile"]["width"] == 375
    assert strike["viewport_summary"]["desktop"]["width"] == 1440
    assert payload["triage_metadata"]["locked_shared_ui_globs"] == [
        "src/components/ui/*", "*/components/ui/*"]


# ---------------------------------------------------------------------------
# Seed runs
# ---------------------------------------------------------------------------

def test_seed_three_canonical_runs_with_real_pngs(tmp_path):
    store = ArtifactStore(root=tmp_path)
    runs = seed_canonical_runs(store)
    assert [r["pr_number"] for r in runs] == [101, 102, 103]
    by_status = {r["status"] for r in runs}
    assert by_status == {"RESOLVED", "FAILED", "RUNNING"}

    for run in runs:
        for entry in run["artifacts"]:
            path = Path(entry["path"])
            assert path.is_file()
            assert entry["url"].startswith("/api/artifacts/")
            if entry["name"].endswith(".png"):
                assert path.read_bytes()[:4] == b"\x89PNG"

    payload = build_run_payload(runs[0], runs[0]["anomalies"],
                                  runs[0]["attempts_raw"], runs[0]["artifacts"])
    baseline, strike = payload["attempts"][0], payload["attempts"][1]
    assert baseline["screenshots"]["mobile"]["before_url"].endswith("screenshot_before.png")
    assert baseline["sam_masks"]["mobile"]["mask_url"].endswith("sam_mask.png")
    assert baseline["sam_masks"]["desktop"]["overlay_url"].endswith("overlay.png")
    assert strike["screenshots"]["mobile"]["after_url"].endswith("screenshot_after.png")
    assert strike["verification_feedback"]["strike_decision"] == "RESOLVED"
    assert payload["attempts"][-1]["verification_feedback"]["github"]["commit_pushed"] is True

    failed = build_run_payload(runs[1], runs[1]["anomalies"],
                                runs[1]["attempts_raw"], runs[1]["artifacts"])
    assert len(failed["attempts"]) == 4  # baseline + 3 strikes
    assert failed["attempts"][-1]["verification_feedback"]["strike_decision"] == \
        "FALLBACK_BEST_PATCH"

    # Idempotent: a second seed pass over a populated registry is a no-op.
    assert seed_if_empty(store) == 0
    assert len(store.list_run_records()) == 3


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "BROWSER_ARTIFACTS_DIR", str(tmp_path))
    # Pin non-live mode so seed-registry listing is exercised deterministically
    # regardless of the developer's configured GitHub credentials.
    monkeypatch.setattr(settings, "GITHUB_PAT", "")
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "")
    store = ArtifactStore(root=tmp_path)
    seed_canonical_runs(store)
    return store


@pytest.mark.asyncio
async def test_rich_run_details_api(api_env):
    from backend.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/runs/run-seed-101")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "run-seed-101"
        assert data["attempts"][0]["kind"] == "baseline"
        assert data["attempts"][1]["repair_spec"]["target_file"] == \
            "src/components/CheckoutPage.tsx"
        assert data["attempts"][1]["unified_diff"].startswith("--- a/")
        url = data["attempts"][0]["screenshots"]["mobile"]["before_url"]
        assert url.startswith("/api/artifacts/run-seed-101/")

        arts = await client.get("/api/runs/run-seed-101/artifacts")
        assert arts.status_code == 200
        assert len(arts.json()["artifacts"]) >= 6

        listing = await client.get("/api/runs")
        assert listing.status_code == 200
        ids = {r["id"] for r in listing.json()}
        assert {"run-seed-101", "run-seed-102", "run-seed-103"} <= ids

        created = await client.post("/api/runs", json={
            "pr_number": 777, "repo_name": "org/repo", "branch": "feat/x"})
        assert created.status_code == 202
        assert created.json()["status"] == "QUEUED"


def test_capture_sense_artifacts_writes_images(tmp_path):
    import numpy as np
    from PIL import Image
    import io
    from backend.core.artifacts import ArtifactStore, capture_sense_artifacts

    store = ArtifactStore(root=tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (375, 812), (20, 20, 24)).save(buf, format="PNG")
    mask = np.zeros((812, 375), dtype=np.uint8)
    mask[80:140, 12:200] = 1
    entries = capture_sense_artifacts(
        "run-cap", 0,
        {"mobile": {"screenshot": buf.getvalue(), "masks": [mask]}, "desktop": {}},
        [{"element_id": "visor-el-04", "defect_type": "OCCLUSION",
          "bounding_box": {"x": 12, "y": 80, "width": 350, "height": 60}}],
        store=store)
    kinds = {(e["viewport"], e["kind"]) for e in entries}
    assert ("mobile", "screenshot_before") in kinds
    assert ("mobile", "sam_mask") in kinds
    assert ("mobile", "overlay") in kinds
    # Desktop had no real bytes: flagged synthetic canvas, still valid PNG.
    desktop = [e for e in entries if e["viewport"] == "desktop"][0]
    assert desktop["synthetic"] is True
    assert Path(desktop["path"]).read_bytes()[:4] == b"\x89PNG"


def test_patch_hashes_and_token_ratio_non_null(tmp_path):
    import hashlib
    from backend.core.artifacts import (
        build_run_payload, record_patch_hashes)
    from backend.core.state import AgentState

    target = tmp_path / "src" / "components" / "CheckoutPage.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    state = AgentState(run_id="run-hash", repo_name="org/repo", pr_number=5,
                       target_files=["src/components/CheckoutPage.tsx"])
    state.sandbox.working_dir = str(tmp_path)
    record_patch_hashes(state, "pre")
    target.write_text("after", encoding="utf-8")
    record_patch_hashes(state, "post")
    hashes = state.repair_spec["patch_file_hashes"]["src/components/CheckoutPage.tsx"]
    assert hashes["pre_sha256"] == hashlib.sha256(b"before").hexdigest()
    assert hashes["post_sha256"] == hashlib.sha256(b"after").hexdigest()

    payload = build_run_payload(
        {"id": "run-hash", "repair_spec": state.repair_spec,
         "target_files": state.target_files},
        [], [{"attempt_number": 1, "unified_diff": "diff", "passed": False,
              "repair_spec": state.repair_spec}], [])
    tele = payload["attempts"][1]["patch_telemetry"]
    assert tele["target_pre_sha256"] == hashes["pre_sha256"]
    assert tele["target_post_sha256"] == hashes["post_sha256"]
    assert payload["triage_metadata"]["token_reduction_ratio"] == 0.885


@pytest.mark.asyncio
async def test_post_runs_dispatch_streams_and_persists(api_env):
    from backend.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/runs", json={
            "pr_number": 888, "repo_name": "org/repo", "dispatch": True})
        assert created.status_code == 202
        body = created.json()
        assert body["dispatched"] is True
        run_id = body["id"]
        # Background lifecycle persists telemetry for the dispatched run.
        import asyncio
        payload = None
        for _ in range(50):
            resp = await client.get(f"/api/runs/{run_id}")
            payload = resp.json()
            if payload.get("status") in ("RESOLVED", "FAILED"):
                break
            await asyncio.sleep(0.1)
        assert payload is not None
        assert payload["attempts"][0]["kind"] == "baseline"


def test_ws_envelopes_carry_monotonic_sequence():
    from backend.api.routes_ws import ConnectionManager

    manager = ConnectionManager()
    first = manager.format_envelope("SENSE_STARTED", {"run_id": "run-x"})
    second = manager.format_envelope("SENSE_COMPLETE", {"run_id": "run-x"})
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["sequence"] > first["sequence"]
    assert first["updated_at"] == first["timestamp"]
