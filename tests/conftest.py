import pytest
from backend.db.repository import init_db

@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Ensure database tables are initialized before tests run."""
    try:
        await init_db()
    except Exception as e:
        print(f"Database init warning: {e}")
