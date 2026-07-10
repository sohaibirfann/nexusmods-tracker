import os
import tempfile

# settings read env at import time, so set everything before the app is imported
_fd, _db = tempfile.mkstemp(suffix=".db")
os.environ["NEXUS_API_KEY"] = "test"
os.environ["INTERNAL_API_KEY"] = "test-key"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db}"
os.environ["DISCORD_BOT_TOKEN"] = "test"
os.environ["BACKEND_URL"] = "http://test"

import httpx  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport  # noqa: E402

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
async def client():
    from backend.database import Base, engine
    from backend.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
