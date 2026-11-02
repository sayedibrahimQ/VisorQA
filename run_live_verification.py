import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("visorqa.live_run")

async def main():
    from backend.config import settings
    from backend.core.state import AgentState, FSMStep, RunStatus
    from backend.core.worktree import hydrate_pr_workspace
    from backend.adapters.sandbox_runner import E2BSandboxRunner
    from backend.core.orchestrator import run_visor_agent
    from backend.api.routes_ws import ws_broadcast
    from backend.core.artifacts import persist_run_telemetry, ArtifactStore
    from backend.db.repository import AsyncSessionLocal, RunRepository

    repo = "sayedibrahimQ/aether-hardware"
    branch = "feat/mobile-promo-banner"
    pr_number = 1
    pr_title = "feat: add mobile promotional banner component"
    
    # Generate run ID
    run_id = f"run-{uuid4().hex[:12]}"
    logger.info(f"Starting real live verification run: {run_id}")

    # 1. Hydrate PR workspace
    ws = await hydrate_pr_workspace(run_id, repo, branch, pr_number)
    root = ws.get("root")
    if not root or not Path(root).is_dir():
        raise RuntimeError(f"Workspace hydration failed: {ws}")
    logger.info(f"Hydrated PR workspace: strategy={ws.get('strategy')} root={root} files={len(ws.get('repository_files', []))}")

    # 2. Persist initial run to ArtifactStore and PostgreSQL
    record = {
        "id": run_id,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "display_label": f"PR #{pr_number}",
        "repo_name": repo,
        "repo_full_name": repo,
        "branch": branch,
        "commit_sha": "c0ffee1",
        "status": "QUEUED",
        "current_step": "1.SENSE",
        "max_attempts": 3,
        "target_files": [],
        "anomalies": [],
        "attempts_raw": [],
        "artifacts": [],
    }
    ArtifactStore().save_run_record(record)
    async with AsyncSessionLocal() as session:
        rep = RunRepository(session)
        created = await rep.create_run(
            run_id=run_id,
            pr_number=pr_number,
            repo_name=repo,
            branch=branch,
            commit_sha="c0ffee1",
            pr_title=pr_title,
        )
        logger.info(f"Created DB run: id={created.id}")

    # 3. Create AgentState
    state = AgentState(
        run_id=run_id,
        repo_full_name=repo,
        repo_name=repo,
        pr_number=pr_number,
        branch=branch,
        commit_sha="c0ffee1",
    )
    spec = dict(state.repair_spec) if isinstance(state.repair_spec, dict) else {}
    spec["repo_root"] = root
    spec["repository_files"] = ws["repository_files"]
    spec["worktree_strategy"] = ws["strategy"]
    state.repair_spec = spec

    # 4. Bind E2BSandboxRunner
    runner = E2BSandboxRunner(
        source_dir=root,
        api_key=str(getattr(settings, "E2B_API_KEY", "") or "") or None,
        sandbox_timeout=180,
    )
    await runner.ensure_and_inject(state)
    await runner.start_dev_server()
    preview_url = await runner.get_preview_url()
    logger.info(f"Sandbox dev server live at: {preview_url}")

    # 5. Execute 5-Node FSM Orchestrator
    logger.info("Executing run_visor_agent across all 5 nodes...")
    final_state = await run_visor_agent(state, ws_broadcast=ws_broadcast, sandbox_runner=runner)

    # 6. Persist telemetry and update PostgreSQL
    persist_run_telemetry(final_state)
    async with AsyncSessionLocal() as session:
        rep = RunRepository(session)
        await rep.sync_agent_state(final_state)

    logger.info(f"Live run completed: final_step={final_state.current_step} status={final_state.status} is_resolved={final_state.is_resolved}")
    logger.info(f"Baseline anomalies: {len(final_state.baseline_anomalies or [])}")
    for anom in final_state.baseline_anomalies or []:
        logger.info(f"  Baseline anomaly: {anom}")
    logger.info(f"Attempts count: {len(final_state.attempts)}")
    for a in final_state.attempts:
        logger.info(f"  Attempt {a.attempt_number}: passed={a.passed} post_score={a.post_score} vr={a.verified_vr} iou={a.verified_iou} dx={a.verified_bleed_px}")
        logger.info(f"  Attempt patch diff:\n{a.patch_diff}")

    # Clean up runner
    await runner.terminate()

    # Verify screenshots on disk
    art_dir = Path("backend/artifacts") / run_id
    before_shot = art_dir / "screenshot_before.png"
    after_shot = art_dir / "screenshot_after.png"
    logger.info(f"Artifact directory: {art_dir}")
    logger.info(f"screenshot_before.png: exists={before_shot.is_file()} size={before_shot.stat().st_size if before_shot.is_file() else 0}")
    logger.info(f"screenshot_after.png: exists={after_shot.is_file()} size={after_shot.stat().st_size if after_shot.is_file() else 0}")

if __name__ == "__main__":
    asyncio.run(main())
