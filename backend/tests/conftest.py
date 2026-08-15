"""
KAEOS Test Root Conftest
Unit/integration tests use in-memory SQLite with ASGI transport.
E2E tests (tests/e2e/) use the live backend — see tests/e2e/conftest.py.

NOTE: e2e-mode used to be detected with `any("e2e" in arg for arg in sys.argv)`,
which matched `--ignore=tests/e2e` too - the fixture block silently vanished
for the whole unit batch and some tests fell through to the LIVE dev database.
The fixtures are now defined unconditionally: e2e tests never request them
(they use their own HTTP client), so there is nothing to gate.

TWO ENGINES, BOTH SCHEMA'D — this shape is deliberate, do not "unify" it:

* ``test_engine`` backs the ``db`` fixture and the ``get_db`` dependency
  override — everything a test or an API call under test can see.
* The APP's own engine (``app/core/database.py``'s StaticPool ":memory:")
  backs the runtime's direct ``AsyncSessionLocal`` side-writes: the activity
  feed, autonomy-policy reads, durable HITL records. It is a SIDECAR: schema'd
  so those writes succeed, but its rows are invisible to the test engine.

Why not one shared engine? Two attempts, two distinct failures:
  - Reusing the app's StaticPool engine puts every session on ONE physical
    SQLite connection, so an internal session's commit/rollback silently ends
    the test session's open transaction (StaleDataError: "expected to update
    1 row(s); 0 were matched" in mission planning).
  - A named shared-cache database gives sessions their own connections, but
    then internal lookups (autonomy thresholds, LLM narrative enrichment)
    genuinely resolve — changing the fail-closed behaviour hundreds of
    existing tests were authored against.
Why schema the sidecar at all? Unschema'd, its writes raise "no such table:
activity_feed_events" — non-fatal where wrapped, but a hard 500 on the paths
that are not (the CI backend-test red, and the long-standing local
test_consequence failure). Schema'd, those writes succeed and stay invisible,
which is exactly the behaviour the suite was green against.
"""
import os

import pytest

# Unit/integration tests must never touch a real database file. E2E tests are
# unaffected: they talk to a live server over HTTP, so this process-local
# environment default does not reach them.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.database import async_engine as app_engine  # noqa: E402
from app.main import app  # noqa: E402

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def setup_db(request):
    # e2e tests talk to the live server - skip the in-memory schema churn.
    if "e2e" in str(getattr(request.node, "fspath", "")):
        yield
        return
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # The sidecar app engine must have the schema too (see module docstring).
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db():
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
