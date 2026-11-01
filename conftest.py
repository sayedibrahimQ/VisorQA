"""Root pytest fixtures.

``backend.config.settings`` loads ambient ``.env`` at import, which may
carry a real ``META_API_KEY`` on dev machines. Since the Meta base URL
and model now carry code defaults, that key alone would select the live
Muse Spark client. Scrub it for every test so the deterministic stub
adapters stay selected unless a test opts into live credentials
explicitly via ``monkeypatch``.
"""
import os
import pytest

# Ensure all tests run against an isolated test database, never the live DB
if "DATABASE_URL" not in os.environ or "visorqa_test" not in os.environ.get("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://visorqa:visorqa@localhost:5432/visorqa_test"
    )

from backend.config import settings


@pytest.fixture(autouse=True)
def _scrub_meta_credentials(monkeypatch):
    monkeypatch.setattr(settings, "META_API_KEY", "")
    yield


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path_factory, monkeypatch):
    """Ensure tests write to an isolated temporary directory and never touch live artifacts."""
    test_artifacts = tmp_path_factory.mktemp("test_artifacts")
    monkeypatch.setattr(settings, "BROWSER_ARTIFACTS_DIR", str(test_artifacts))
    yield

