"""KAEOS — Database Engine & Session Factory"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.models.domain import Base
# Import all model modules to register their tables with Base.metadata
# Wrapped in try/except so a broken subsystem doesn't crash the entire DB init
import logging as _logging
_db_logger = _logging.getLogger(__name__)

_model_modules = [
    "app.models.settings",
    "app.models.agent_factory",
    "app.models.fairness",
    "app.models.calendar",
    "app.models.infrastructure",
    "app.models.auth",
    "app.models.events",
    "app.workforce.models.core",
    "app.workforce.models.domain_pack",
    "app.workforce.models.integration",
    "app.workforce.models.runtime",
    "app.workforce.models.memory",
    "app.hr.models.core",
    "app.hr.models.recruiting",
    "app.hr.models.onboarding",
    "app.hr.models.benefits",
    "app.hr.models.compensation",
    "app.hr.models.performance",
    "app.hr.models.learning",
    "app.hr.models.employee_relations",
    "app.hr.models.workforce_planning",
    "app.hr.models.time_attendance",
    "app.hr.models.payroll",
    "app.hr.models.compliance",
    "app.hr.models.analytics",
    "app.finance.models",
    "app.legal.models",
    "app.support.models",
    "app.sales.models",
    "app.operations.models",
    # Engineering was missing here: its tables were therefore absent from
    # create_all at bootstrap, got created later (once a router imported the
    # models), and so were never swept by the RLS migration - shipping the
    # whole department with NO tenant isolation. init_db now re-sweeps after
    # create_all as a backstop, but every model module still belongs here.
    "app.engineering.models",
]
for _mod in _model_modules:
    try:
        __import__(_mod)
    except Exception as _exc:
        _db_logger.warning(f"[Database] Could not import {_mod}: {_exc}. Tables from this module will not be created.")

settings = get_settings()

# SQLite doesn't support pool_size/max_overflow
engine_kwargs = {
    "echo": settings.DEBUG,
}
if not settings.is_sqlite:
    engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
elif ":memory:" in settings.DATABASE_URL:
    # A SQLite ":memory:" database is per-connection by default, so tables created
    # on one connection are invisible to others. Use a StaticPool so every session
    # shares a single in-memory connection (needed for the dev/test stack where
    # AsyncSessionLocal and request sessions must see the same schema/data).
    from sqlalchemy.pool import StaticPool
    engine_kwargs["poolclass"] = StaticPool
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_engine = engine

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# ── Bind every transaction to the ambient tenant (for Postgres RLS) ──────────
#
# Service and agent code opens ~94 sessions directly rather than through the
# `get_db` dependency, so those sessions carried no tenant context and RLS
# correctly refused their writes. Rather than touch 94 call sites, the tenant
# is applied here.
#
# It MUST be per-transaction, not per-session: `set_config(..., is_local=true)`
# lasts only for the current transaction, so a commit dropped it and the very
# next statement (e.g. SQLAlchemy refreshing the row it just inserted) ran with
# no tenant - RLS then hid that row and the ORM raised "Could not refresh
# instance". `after_begin` fires for every transaction, including the ones
# opened after a commit, so the binding is never lost.
#
# is_local=true also means the setting cannot leak to the next request that
# reuses this pooled connection - a cross-tenant hazard if it were session-wide.
from sqlalchemy import event as _event  # noqa: E402
from sqlalchemy.orm import Session as _SyncSession  # noqa: E402


@_event.listens_for(_SyncSession, "after_begin")
def _bind_tenant_to_transaction(session, transaction, connection):
    if connection.dialect.name != "postgresql":
        return
    try:
        from app.core.context import current_tenant_id
        tenant_id = current_tenant_id.get()
    except Exception:
        return
    if not tenant_id:
        return  # no context: RLS shows nothing (fails closed), by design
    try:
        # Go through SQLAlchemy's compiler, not exec_driver_sql: the raw driver
        # path uses asyncpg's own paramstyle and a mismatch here aborts the
        # whole transaction, after which every later statement fails with
        # InFailedSQLTransactionError and the true cause is invisible.
        from sqlalchemy import text as _text
        connection.execute(
            _text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
        )
    except Exception as e:
        # Do NOT swallow silently: a failure here means the transaction is
        # already poisoned, and hiding it turns one clear error into dozens of
        # confusing downstream ones.
        _db_logger.error(f"[RLS] failed to bind tenant to transaction: {e}")
        raise

# ── Maintenance engine (DDL + seeding) ───────────────────────────────────────
# Under Postgres row-level security the application connects as a NON-OWNER
# role so the policies apply to it. That role deliberately cannot create tables
# or insert rows outside a tenant context - which is exactly what schema
# creation and seeding do. KAEOS_OWNER_DB_URL points at the owning role for
# those maintenance paths; without it we fall back to the app connection
# (correct for SQLite dev, and for Postgres set-ups that skip RLS).
import os as _os  # noqa: E402

_OWNER_URL = _os.environ.get("KAEOS_OWNER_DB_URL")
maintenance_engine = (
    create_async_engine(_OWNER_URL, **engine_kwargs) if _OWNER_URL else engine
)
MaintenanceSessionLocal = sessionmaker(
    maintenance_engine, class_=AsyncSession, expire_on_commit=False
)


async def ensure_rls_policies(conn) -> list[str]:
    """Put every tenant-scoped table under RLS. Returns the tables it repaired.

    The RLS migration sweeps information_schema at ONE POINT IN TIME, so any
    table created afterwards - by create_all for a model module registered
    later, or by runtime DDL - silently ships with NO tenant isolation. That
    is not hypothetical: the entire Engineering department shipped unprotected
    exactly this way.

    So the sweep runs on every init_db, after create_all: cheap when there is
    nothing to fix (one query), and it closes the hole permanently rather than
    once. Anything it repairs is logged as a WARNING - a table reaching here
    unprotected means it escaped the migration, and that is worth seeing.

    Must run on the OWNER connection (only the owner may ALTER these tables).
    """
    from sqlalchemy import text as _text

    from app.core.rls import (
        GLOBAL_TABLES,
        UNPROTECTED_TENANT_TABLES_SQL,
        rls_enable_statements,
    )

    rows = (await conn.execute(_text(UNPROTECTED_TENANT_TABLES_SQL))).fetchall()
    repaired: list[str] = []
    for (table,) in rows:
        if table in GLOBAL_TABLES:
            continue
        for stmt in rls_enable_statements(table):
            await conn.execute(_text(stmt))
        repaired.append(table)

    if repaired:
        _db_logger.warning(
            f"[RLS] {len(repaired)} tenant table(s) had no isolation policy and "
            f"were repaired at startup: {', '.join(repaired)}. They were created "
            f"after the RLS migration swept the schema - verify with scripts/verify_rls.py."
        )
    return repaired


async def ensure_app_role(conn) -> bool:
    """Create the non-owner `kaeos_app` login role + grants, idempotently.

    The app connects as `kaeos_app` (DATABASE_URL) so RLS actually applies - the
    table OWNER bypasses its own policies. That role and its DML grants are
    created by migration b7c1d9e4a201, but the Docker image runs bare `uvicorn`
    with no `alembic upgrade` step: on a FRESH database (empty volume) the role
    would not exist and the app could not connect at all. init_db already runs as
    the owner, which is exactly the privilege needed to create it, so we bootstrap
    it here too. Fully idempotent - a no-op when the role already exists.

    Runs AFTER create_all so GRANT ON ALL TABLES covers the freshly-made tables;
    ALTER DEFAULT PRIVILEGES covers any created later. Never touches the password
    of an existing role (CREATE is guarded by IF NOT EXISTS).
    """
    from sqlalchemy import text as _text

    app_pw = _os.environ.get("KAEOS_APP_DB_PASSWORD", "kaeos_app_dev")
    # Only the owner may create roles / grant; init_db's conn is the owner.
    await conn.execute(_text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kaeos_app') THEN
                CREATE ROLE kaeos_app LOGIN PASSWORD '{app_pw}';
            END IF;
        END
        $$;
    """))
    await conn.execute(_text("GRANT USAGE ON SCHEMA public TO kaeos_app"))
    await conn.execute(_text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kaeos_app"))
    await conn.execute(_text(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kaeos_app"))
    await conn.execute(_text("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kaeos_app
    """))
    return True


async def init_db():
    """Create all tables (for dev/demo — use Alembic in production)."""
    async with maintenance_engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Semantic-memory tables use pgvector's `vector` type; the compose
            # image (pgvector/pgvector) ships the extension but nothing enables
            # it, so create_all fails on a fresh database without this.
            from sqlalchemy import text as _text
            await conn.execute(_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            # Bootstrap the non-owner app role so a fresh Docker deploy (no
            # alembic step) can connect as kaeos_app - MUST be before the app
            # serves a request. Owner-only, idempotent.
            if _OWNER_URL:
                try:
                    await ensure_app_role(conn)
                except Exception as _exc:
                    _db_logger.warning(f"[DB] ensure_app_role skipped: {_exc}")
            # Tables just created by create_all are not covered by the earlier
            # migration sweep - protect them before the app serves a request.
            await ensure_rls_policies(conn)


async def get_db():
    """Request-scoped session.

    Tenant binding for RLS happens in the `after_begin` listener above, which
    covers EVERY transaction on EVERY session - including the ~94 opened
    directly by service code that never sees a request, and the ones opened
    after a commit. Doing it here as well was redundant and, worse, only
    covered the first transaction of request-scoped sessions.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
