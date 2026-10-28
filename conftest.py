"""Root pytest fixtures.

``backend.config.settings`` loads ambient ``.env`` at import, which may
carry a real ``META_API_KEY`` on dev machines. Since the Meta base URL
and model now carry code defaults, that key alone would select the live
Muse Spark client. Scrub it for every test so the deterministic stub
adapters stay selected unless a test opts into live credentials
explicitly via ``monkeypatch``.
"""
import pytest

from backend.config import settings


@pytest.fixture(autouse=True)
def _scrub_meta_credentials(monkeypatch):
    monkeypatch.setattr(settings, "META_API_KEY", "")
    yield
