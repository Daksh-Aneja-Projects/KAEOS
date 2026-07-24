"""
KAEOS — main.py (updated)
Changes from original:
  1. TenantMiddleware registered before all routers
  2. Platform config API routes added for API key management
"""
import logging
import asyncio
import os

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, MaintenanceSessionLocal
from app.core.seed import seed_database
from app.core.tenant import TenantMiddleware                # ← NEW
from app.core.logging import setup_logging
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    logger.warning("[Observability] prometheus_fastapi_instrumentator not installed — /metrics disabled")

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from app.core.telemetry import setup_telemetry
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False
    logger.warning("[Observability] opentelemetry not installed — tracing disabled")

from app.api.routes import (
    rules, skills, dashboard, elicitation,
    extraction, provenance, redteam, benchmark, topology,
    connectors, conflicts, marketplace, security, pipeline,
    predictive, polymorphic, federated, kaeos10x,
    platform_config, enterprise, agent_factory, pioneer,
    infrastructure, auth, brain, departments, hitl, ws, executive, chat,
    privacy,
)
from app.hr.api.v1.router import router as hr_router
from app.finance.api.v1.router import router as finance_router
from app.legal.api.v1.router import router as legal_router
from app.support.api.v1.router import router as support_router
from app.engineering.api.v1.router import router as engineering_router
from app.sales.api.v1.router import router as sales_router
from app.operations.api.v1.router import router as operations_router

# ── Workforce Layer API routers ────────────────────────────────────────────────
from app.workforce.api.departments import router as wf_departments_router
from app.workforce.api.deployment import router as wf_deployment_router
from app.workforce.api.domain_packs import router as wf_domain_packs_router
from app.workforce.api.processes import router as wf_processes_router
from app.workforce.api.analytics import router as wf_analytics_router


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: validate config, create tables, seed data. Shutdown: cleanup."""
    # ── Security checks ──────────────────────────────────────────────────
    # Outside DEV_MODE we FAIL FAST on insecure config rather than silently
    # generating throwaway secrets or leaving admin endpoints wide open.
    security_problems = settings.validate_production_security()
    if security_problems:
        for p in security_problems:
            logger.error(f"[SECURITY] {p}")
        raise RuntimeError(
            "Refusing to start with insecure configuration: "
            + " ".join(security_problems)
            + " Set DEV_MODE=true only for local development."
        )

    # Hard guard: DEV_MODE bypasses auth AND honors an X-Tenant-ID override -
    # catastrophic on a shared deployment. Because it disables authentication,
    # enabling it must be a deliberate, explicit act. We require BOTH:
    #   1. ENVIRONMENT was explicitly configured (env var or .env) — not left at
    #      the "development" default. `model_fields_set` is True only when a
    #      config source actually set the field, so an operator who sets
    #      DEV_MODE=true but forgets ENVIRONMENT is refused rather than sliding
    #      through on the default.
    #   2. That explicit value names a known local environment; anything else
    #      (incl. typos like "prod1", "live", "staging-eu") is treated as
    #      production and refused.
    # Both conditions must hold, so the unset case and the unrecognised case
    # both fail closed: DEV_MODE never disables auth by omission.
    _DEV_ENVIRONMENTS = {"development", "dev", "local", "test", "testing", "ci"}
    _env_explicit = "ENVIRONMENT" in settings.model_fields_set
    if settings.DEV_MODE and (
        not _env_explicit or settings.ENVIRONMENT.lower() not in _DEV_ENVIRONMENTS
    ):
        _env_desc = (
            f"ENVIRONMENT={settings.ENVIRONMENT!r}" if _env_explicit
            else "ENVIRONMENT unset (defaulted)"
        )
        raise RuntimeError(
            f"DEV_MODE=true with {_env_desc}: refusing to start. "
            "DEV_MODE disables authentication and tenant isolation — it is allowed "
            "only when ENVIRONMENT is explicitly set to one of "
            f"{sorted(_DEV_ENVIRONMENTS)}."
        )

    if settings.DEV_MODE:
        logger.warning(
            "[SECURITY] DEV_MODE is ON — authentication is bypassed and a dev tenant "
            "is used. Do NOT enable DEV_MODE in production."
        )
        if not settings.SECRET_KEY:
            import secrets
            settings.SECRET_KEY = secrets.token_urlsafe(32)
            logger.warning(
                "[SECURITY] SECRET_KEY is empty — generated an ephemeral key for this "
                "dev session. Set SECRET_KEY in .env to persist JWT sessions."
            )

    setup_logging()

    await init_db()
    # Verify Postgres RLS is actually in force (not inert due to owner-role
    # misconfig) before serving any traffic. Fails closed in production.
    from app.core.database import assert_rls_effective
    try:
        await assert_rls_effective()
    except RuntimeError:
        raise
    except Exception as _rls_exc:
        logger.warning(f"[RLS] effectiveness check could not run: {_rls_exc}")
    # Seeding is maintenance: run it on the owner connection. Under RLS the
    # app role cannot insert rows without a tenant context (by design), so
    # seeding through it fails closed - which is the policy working, not a bug.
    async with MaintenanceSessionLocal() as session:
        # Demo/fictional dataset (tenant_acme) is opt-out: set SEED_DEMO_DATA=false
        # in a real deployment so dashboards only reflect genuinely ingested data.
        if settings.SEED_DEMO_DATA:
            seeded = await seed_database(session)
            if seeded:
                logger.info("Database seeded with KAEOS demo data")
            else:
                logger.info("Database already contains data, skipping seed")
        else:
            logger.info("SEED_DEMO_DATA=false — skipping fictional demo dataset")
        # Provision the root admin account from configuration (no public default).
        from app.services.auth import AuthService
        await AuthService.seed_admin_user(session)

        # Sync built-in domain packs (HR, etc.) from YAML into DB
        try:
            from app.workforce.domain_packs.engine import DomainPackEngine
            await DomainPackEngine.sync_built_in_packs(session)
            logger.info("Built-in domain packs synced to database")
        except Exception as e:
            logger.warning(f"Domain pack sync failed (non-fatal): {e}")

    # Seed department domain data (HR/Finance/Legal/Sales/Support/Operations)
    # when empty, then roll up department KPI metrics. Idempotent per domain.
    from app.core.domain_seed import seed_domains_if_empty
    await seed_domains_if_empty()
            
    # Initialize Redis
    from app.core.redis import init_redis, close_redis
    await init_redis()

    # Background Service 1: PreCog Engine (L24 Ambient Intelligence)
    # Background Service 2: Event Bus Queue Worker
    # Background Service 3: APScheduler for Decay Checks
    from app.services.precog_engine import PreCogEngine
    from app.services.event_bus import event_bus
    from app.services.scheduler import init_scheduler
    
    # These are SINGLETON loops. Running them on every replica means N× the LLM
    # spend and read-then-write races on the same rows. Leadership is now
    # AUTOMATIC (Redis lock → Postgres advisory → local single-instance), so
    # every replica boots identically and only the elected leader runs them.
    # RUN_BACKGROUND_JOBS=false still lets an operator pin a replica to pure API
    # duty (it never even contends for leadership). Default true keeps
    # single-instance dev/demo working exactly as before (local backend → always
    # leader).
    from app.services.leader_lock import leader_lock, run_election

    _bg = {"precog": None, "event_bus": None, "scheduler": None}

    def _start_background_loops():
        if _bg["scheduler"] is not None:
            return  # already running — an idempotent re-acquire must not double-start
        _bg["precog"] = asyncio.create_task(PreCogEngine().run_ambient_loop())
        _bg["event_bus"] = asyncio.create_task(event_bus._worker_loop())
        sched = init_scheduler()
        sched.start()
        _bg["scheduler"] = sched
        logger.info("[Background] leader — singleton loops started (precog, event bus, scheduler)")

    def _stop_background_loops():
        if _bg["scheduler"] is not None:
            _bg["scheduler"].shutdown(wait=False)
            _bg["scheduler"] = None
        for _k in ("precog", "event_bus"):
            if _bg[_k] is not None:
                _bg[_k].cancel()
                _bg[_k] = None

    election_task = None
    if settings.RUN_BACKGROUND_JOBS:
        if await leader_lock.acquire():
            _start_background_loops()
        election_task = asyncio.create_task(
            run_election(leader_lock, on_acquire=_start_background_loops,
                         on_release=_stop_background_loops)
        )
        logger.info("[Background] leader election running (backend=%s)", leader_lock.backend)
    else:
        logger.info("[Background] RUN_BACKGROUND_JOBS=false — this instance stays API-only (no leadership)")

    yield

    # Shutdown: stop electing, then stop the loops, draining cancelled tasks.
    _precog_t, _eventbus_t = _bg.get("precog"), _bg.get("event_bus")
    if election_task is not None:
        election_task.cancel()
        try:
            await election_task
        except asyncio.CancelledError:
            pass
    _stop_background_loops()
    await close_redis()

    for _t in (_precog_t, _eventbus_t):
        if _t is not None:
            try:
                await _t
            except asyncio.CancelledError:
                pass


# Interactive docs and the OpenAPI schema hand out the full endpoint map
# unauthenticated. settings.docs_enabled defaults OFF for a production-like
# ENVIRONMENT even if the operator forgot to flip a flag (fail-closed), and can
# be forced with ENABLE_DOCS.
_docs_enabled = settings.docs_enabled

app = FastAPI(
    title=f"{settings.APP_NAME} API",
    version=settings.APP_VERSION,
    description="KAEOS — Enterprise Workforce Operating System (EWOS), powered by AEOS",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Instrument Prometheus Metrics (optional). /metrics leaks per-endpoint traffic
# and is scraped over an internal network, not the public internet — only expose
# it when EXPOSE_METRICS is explicitly set. Instrumentation (the counters) still
# runs; we just don't publish the public endpoint by default.
if _HAS_PROMETHEUS:
    _inst = Instrumentator().instrument(app)
    if settings.EXPOSE_METRICS:
        _inst.expose(app, endpoint="/metrics")
        logger.info("[Observability] /metrics exposed (EXPOSE_METRICS=true)")
    else:
        logger.info("[Observability] /metrics NOT exposed (set EXPOSE_METRICS=true to publish)")
# Instrument OpenTelemetry (optional).
#
# Only instrument when a collector is actually configured. Instrumenting with
# nowhere to export is pure overhead, and it also means a version skew between
# the OTel FastAPI instrumentation and FastAPI itself cannot take down a
# deployment that never asked for tracing. (An older instrumentation raised
# "'_IncludedRouter' object has no attribute 'path'" on every routed request.)
# Set OTEL_EXPORTER_OTLP_ENDPOINT to enable tracing.
if _HAS_OTEL and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    try:
        setup_telemetry()
        FastAPIInstrumentor.instrument_app(app)
        logger.info("[Observability] OpenTelemetry tracing enabled")
    except Exception as _otel_exc:  # never let tracing break the app
        logger.warning(f"[Observability] OpenTelemetry setup failed, continuing without tracing: {_otel_exc}")
elif _HAS_OTEL:
    logger.info("[Observability] OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")

# ── Middleware (order matters — outermost is added LAST) ─────────────────────────

from app.core.middleware import RequestIdMiddleware, RequestLoggingMiddleware, RateLimitMiddleware

# Innermost → Outermost: Tenant → RequestID → Logging → RateLimit → CORS
app.add_middleware(TenantMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(RequestLoggingMiddleware)
# 1000/min per tenant: live dashboards poll several endpoints per page, and
# 200/min throttled legitimate single-tenant use (seen as 429s in e2e). Still
# a real burst guard; production multi-instance should move this to Redis.
app.add_middleware(RateLimitMiddleware, requests_per_minute=1000)

# CORS must be outermost, so it is added LAST
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if hasattr(settings, "CORS_ORIGINS") else ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

PREFIX = settings.API_PREFIX  # "/api/v1"

app.include_router(dashboard.router,       prefix=PREFIX)
app.include_router(rules.router,           prefix=PREFIX)
app.include_router(skills.router,          prefix=PREFIX)
app.include_router(elicitation.router,     prefix=PREFIX)
app.include_router(extraction.router,      prefix=PREFIX)
app.include_router(provenance.router,      prefix=PREFIX)
app.include_router(redteam.router,         prefix=PREFIX)
app.include_router(benchmark.router,       prefix=PREFIX)

# RateLimitMiddleware already registered above (line 132) — no duplicate needed
app.include_router(topology.router,        prefix=PREFIX)
app.include_router(connectors.router,      prefix=PREFIX)
app.include_router(conflicts.router,       prefix=PREFIX)
app.include_router(marketplace.router,     prefix=PREFIX)
app.include_router(security.router,        prefix=PREFIX)
app.include_router(pipeline.router,        prefix=PREFIX)
app.include_router(predictive.router,      prefix=PREFIX)
app.include_router(polymorphic.router,     prefix=PREFIX)
app.include_router(federated.router,       prefix=PREFIX)
app.include_router(kaeos10x.router,    prefix=PREFIX)
app.include_router(platform_config.router, prefix=PREFIX)
app.include_router(privacy.router,         prefix=PREFIX)
app.include_router(enterprise.router,      prefix=PREFIX)
app.include_router(agent_factory.router,   prefix=PREFIX)
from app.api.routes import reality
app.include_router(reality.router, prefix="/api/v1/reality", tags=["Reality Experience"])
app.include_router(pioneer.router,         prefix=PREFIX)
app.include_router(infrastructure.router,  prefix=PREFIX)
app.include_router(auth.router,            prefix=PREFIX)
app.include_router(brain.router,           prefix=PREFIX)
from app.api.routes import billing
app.include_router(billing.router,         prefix=PREFIX)
from app.api.routes import genome_evolution
app.include_router(genome_evolution.router, prefix=PREFIX)
from app.api.routes import foundry
app.include_router(foundry.router, prefix=PREFIX)
from app.api.routes import safe_autonomy
app.include_router(safe_autonomy.router, prefix=PREFIX)
from app.api.routes import outcomes
app.include_router(outcomes.router, prefix=PREFIX)
app.include_router(departments.router,     prefix=PREFIX)
app.include_router(hitl.router,            prefix=PREFIX)
app.include_router(ws.router) # No prefix to keep it cleanly at /ws/tenant_id
app.include_router(hr_router,              prefix=PREFIX)
app.include_router(finance_router,         prefix=PREFIX)
app.include_router(legal_router,           prefix=PREFIX)
app.include_router(support_router,         prefix=PREFIX)
app.include_router(engineering_router,     prefix=PREFIX)
app.include_router(sales_router,           prefix=PREFIX)
app.include_router(operations_router,      prefix=PREFIX)

from app.api.routes import org_pulse  # noqa: E402 — cross-domain pulse layer
app.include_router(org_pulse.router,       prefix=PREFIX)

from app.api.routes import workspace  # noqa: E402 — assignment/comments/notifications/segments/export
app.include_router(workspace.router,       prefix=PREFIX)

from app.api.routes import automation  # noqa: E402 — automation rules engine
app.include_router(automation.router,      prefix=PREFIX)
# NOTE: app.api.routes.workforce (graph-twin overview) is intentionally NOT
# registered: it shadowed the Workforce Layer routes below at
# /workforce/overview and /workforce/departments with zeroed metrics.
# The wf_* routers serve those paths from the real Department tables.
app.include_router(executive.router,   prefix=PREFIX)
app.include_router(chat.router,            prefix=PREFIX)

# Workforce Layer (EWOS)
app.include_router(wf_departments_router,  prefix=PREFIX)
app.include_router(wf_deployment_router,   prefix=PREFIX)
app.include_router(wf_domain_packs_router, prefix=PREFIX)
app.include_router(wf_processes_router,    prefix=PREFIX)
app.include_router(wf_analytics_router,    prefix=PREFIX)


# ── Health checks ───────────────────────────────────────────────────────────

@app.get("/health/live")
async def health_live():
    """Liveness: is the PROCESS up? Always 200 while the app is running.
    Point k8s livenessProbe here (restarting on a dead DB would just loop)."""
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health")
async def health(response: Response):
    """Readiness: process up AND critical backends reachable.

    Returns **503** when a critical backend (the primary database) is
    unavailable, so Docker/k8s and load balancers stop routing traffic to a
    broken instance instead of being told everything is fine. Point
    readinessProbe (and the compose healthcheck) here.
    """
    payload = {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
    ready = True
    try:
        from app.core.polystore import polystore_health
        backends = await polystore_health()
        payload["backends"] = backends
        # The vector store is DB-backed; if it is not available, the primary
        # datastore is down and the instance is NOT ready to serve.
        vs = backends.get("vector_store", {}) if isinstance(backends, dict) else {}
        if isinstance(vs, dict) and vs.get("available") is False:
            ready = False
    except Exception as e:  # a failed health probe means not ready
        payload["backends"] = {"error": str(e)}
        ready = False

    if not ready:
        payload["status"] = "degraded"
        response.status_code = 503
    return payload


# ── API Key management endpoints (admin bootstrap) ────────────────────────────
# These are intentionally NOT behind TenantMiddleware auth (bootstrap scenario).
# In production, secure these behind network-level ACLs or a separate admin service.

from fastapi import HTTPException, Header

# Admin API-key management lives under /admin/security/api-keys and is guarded by a
# constant-time comparison against a CONFIGURED ADMIN_SECRET. If ADMIN_SECRET is not
# set the endpoints are disabled (503) rather than falling back to a shared default.
_ADMIN_ROUTER_PREFIX = "/admin/security/api-keys"


# Single implementation, shared with the route modules that also gate on it
# (see app/core/admin.py) - two copies of an authorization check drift, and the
# one that drifts is the one nobody re-reads.
from app.core.admin import verify_admin_secret as _verify_admin_secret  # noqa: E402


@app.post(_ADMIN_ROUTER_PREFIX, include_in_schema=False)
async def create_api_key(tenant_id: str, name: str, role: str = "operator", x_admin_secret: str = Header(None)):
    """Bootstrap: create an API key for a tenant. Requires a configured ADMIN_SECRET."""
    _verify_admin_secret(x_admin_secret)
    from app.core.auth import generate_api_key
    key_data = generate_api_key(tenant_id=tenant_id, name=name, role=role)
    logger.info(f"[Admin] API key created for tenant={tenant_id} role={role}")
    return key_data


@app.delete(_ADMIN_ROUTER_PREFIX + "/{key_prefix}", include_in_schema=False)
async def revoke_api_key(key_prefix: str, x_admin_secret: str = Header(None)):
    """Revoke an API key by its first 12 characters. Requires a configured ADMIN_SECRET."""
    _verify_admin_secret(x_admin_secret)
    from app.core.auth import revoke_api_key as _revoke
    revoked = _revoke(key_prefix)
    if not revoked:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "key_prefix": key_prefix}
