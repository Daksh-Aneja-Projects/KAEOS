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


# ── Schema lifecycle (M9.4) ──────────────────────────────────────────────────
# The schema is built ONCE per pytest process (per xdist worker), not per test:
# the old autouse fixture ran create_all + drop_all on BOTH engines around EVERY
# test - four DDL passes over 256 tables each, which was most of the suite's
# wall time. Isolation between tests is per-test DATA cleanup instead: endpoints
# commit mid-request, so transaction-rollback isolation is impossible, and a
# DELETE sweep in reverse FK order preserves exactly what drop_all/create_all
# gave each test - empty tables at start.
#
# The schema fixture is deliberately SYNC + asyncio.run: pytest.ini pins
# asyncio_default_fixture_loop_scope = function (see its comment for why), so a
# session-scoped ASYNC fixture would need a session loop and re-open that bug.
# Running DDL on a private throwaway loop is safe because aiosqlite binds each
# operation's future to the loop RUNNING AT CALL TIME, not the loop the pooled
# connection was created on - the same property today's per-test function loops
# already relied on against the module-global engines.

_SWEEP_TABLES = None  # resolved lazily: model modules register during imports


async def _create_schema_once() -> None:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # The sidecar app engine must have the schema too (see module docstring).
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def _schema_for_worker():
    import asyncio
    asyncio.run(_create_schema_once())
    yield
    # No drop_all at session end: both engines are in-memory and die with the
    # process; dropping 256 tables per worker would only slow the exit.


@pytest.fixture(autouse=True)
async def setup_db(request):
    """Per-test DATA isolation: sweep every row after the test (name kept -
    it is the anchor other fixtures order themselves against)."""
    # e2e tests talk to the live server - skip the in-memory data churn.
    if "e2e" in str(getattr(request.node, "fspath", "")):
        yield
        return
    yield
    global _SWEEP_TABLES
    if _SWEEP_TABLES is None:
        # Children before parents: 0055 added real FKs, and while this SQLite
        # harness does not enforce them, the order documents (and future-proofs)
        # the dependency the Postgres schema enforces.
        _SWEEP_TABLES = list(reversed(Base.metadata.sorted_tables))
    from sqlalchemy.exc import OperationalError
    for eng in (test_engine, app_engine):
        try:
            async with eng.begin() as conn:
                for table in _SWEEP_TABLES:
                    await conn.execute(table.delete())
        except OperationalError:
            # "no such table": this engine's StaticPool connection was
            # invalidated mid-session (e.g. a task cancelled mid-DB-op poisoned
            # it), so the pool handed back a FRESH, EMPTY :memory: database.
            # Without healing, every later test on this xdist worker fails the
            # same way - one poisoned test cascaded into 31 teardown errors on
            # CI. Rebuild the schema on the fresh connection and sweep again;
            # a second failure is real and propagates.
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with eng.begin() as conn:
                for table in _SWEEP_TABLES:
                    await conn.execute(table.delete())


@pytest.fixture
async def db():
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
