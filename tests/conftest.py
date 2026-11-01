import os
import pytest

# Ensure all tests run against an isolated test database, never the live DB
if "DATABASE_URL" not in os.environ or "visorqa_test" not in os.environ.get("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://visorqa:visorqa@localhost:5432/visorqa_test"
    )

from backend.config import settings
from backend.db.repository import init_db


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Ensure test database tables are initialized before tests run."""
    try:
        await init_db()
    except Exception as e:
        print(f"Database init warning: {e}")


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path_factory, monkeypatch):
    """Ensure tests write to an isolated temporary directory and never touch live artifacts."""
    test_artifacts = tmp_path_factory.mktemp("test_artifacts")
    monkeypatch.setattr(settings, "BROWSER_ARTIFACTS_DIR", str(test_artifacts))
    yield

