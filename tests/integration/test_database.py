import pytest
from uuid import uuid4
from sqlmodel import select
from backend.db.repository import (
    AsyncSessionLocal,
    RepositoryRecord,
    PRRun,
    AnomalyRecord,
    AttemptRecord,
)

@pytest.mark.asyncio
async def test_database_crud_flow():
    from backend.db.repository import async_engine
    await async_engine.dispose()
    async with AsyncSessionLocal() as session:
        # 1. Create RepositoryRecord
        repo_id = f"test-repo-{uuid4().hex[:8]}"
        repo = RepositoryRecord(
            id=repo_id,
            repo_full_name=f"sayedibrahimQ/repo-{uuid4().hex[:6]}",
            default_branch="main"
        )
        session.add(repo)
        await session.commit()

        # 2. Create PRRun
        run_id = f"run-{uuid4().hex[:8]}"
        pr_run = PRRun(
            id=run_id,
            repo_id=repo_id,
            repo_full_name=repo.repo_full_name,
            pr_number=99,
            branch="feature/modal-fix",
            commit_sha="a7b8c9d0e1f2",
            status="RUNNING",
            attempt=0
        )
        session.add(pr_run)
        await session.commit()

        # 3. Add AnomalyRecord adhering to check constraint: OCCLUSION requires v_r < 0.85, viewport in ('375px', '1440px')
        anomaly = AnomalyRecord(
            run_id=run_id,
            viewport="375px",
            visor_el_id="checkout-cta",
            defect_type="OCCLUSION",
            v_r=0.65,
            b_dom_box={"x": 10, "y": 20, "w": 100, "h": 40},
            lca_dom={"tag": "div", "class": "banner-overlay"}
        )
        session.add(anomaly)
        await session.commit()

        # 4. Add AttemptRecord adhering to check constraints: attempt_number BETWEEN 1 and 3, no anti-hack css
        attempt = AttemptRecord(
            run_id=run_id,
            attempt_number=1,
            target_files=["src/components/Banner.tsx"],
            repair_spec={"css_rules": ["z-index: 10"]},
            unified_diff="--- a/Banner.tsx\n+++ b/Banner.tsx\n@@ -1 +1 @@\n-z-50\n+z-10",
            post_score=0.96,
            passed=True
        )
        session.add(attempt)
        await session.commit()

        # 5. Query and Assert Relationships
        statement = select(PRRun).where(PRRun.id == run_id)
        result = await session.execute(statement)
        fetched_run = result.scalar_one()

        assert fetched_run is not None
        assert fetched_run.pr_number == 99
        assert fetched_run.branch == "feature/modal-fix"

        # Query anomalies
        anom_stmt = select(AnomalyRecord).where(AnomalyRecord.run_id == run_id)
        anom_res = await session.execute(anom_stmt)
        anomalies = anom_res.scalars().all()
        assert len(anomalies) == 1
        assert anomalies[0].visor_el_id == "checkout-cta"
        assert anomalies[0].v_r == 0.65

        # Query attempts
        att_stmt = select(AttemptRecord).where(AttemptRecord.run_id == run_id)
        att_res = await session.execute(att_stmt)
        attempts = att_res.scalars().all()
        assert len(attempts) == 1
        assert attempts[0].passed is True
        assert attempts[0].post_score == 0.96
