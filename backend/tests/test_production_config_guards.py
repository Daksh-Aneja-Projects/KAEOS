"""The boot-time production configuration guard, pinned.

`Settings.validate_production_security()` is what stands between a careless
deploy and an open one: main.py refuses to start when it returns anything. It
had no test at all, so every control in it was one careless edit from silently
returning [] forever. These pin the controls that must never regress.

Constructed with explicit kwargs (which win over the dotenv files), so the
result does not depend on whatever backend/.env happens to hold.
"""
import pytest

from app.core.config import Settings

GOOD = dict(
    DEV_MODE=False,
    ENVIRONMENT="development",          # keep the DB half out of these cases
    SECRET_KEY="a" * 40,
    ADMIN_SECRET="a-real-unique-admin-secret-value",
    ADMIN_TENANT="acme_bank_prod",
    ADMIN_PASSWORD="a-strong-admin-password",
)


def _problems(**overrides) -> list[str]:
    return Settings(**{**GOOD, **overrides}).validate_production_security()


def test_a_correct_production_config_has_no_problems():
    assert _problems() == []


def test_dev_mode_short_circuits_every_check():
    # DEV_MODE is the explicit "I am a laptop" switch; it must not be possible
    # for it to report problems, or local work would be unbootable.
    assert Settings(**{**GOOD, "DEV_MODE": True, "SECRET_KEY": "short",
                       "ADMIN_SECRET": "", "ADMIN_TENANT": "tenant_acme"}
                    ).validate_production_security() == []


@pytest.mark.parametrize("secret", ["", "short", "CHANGE_ME_" + "x" * 30,
                                    "your-secret-key-" + "x" * 30])
def test_a_weak_or_placeholder_secret_key_is_refused(secret):
    assert any("SECRET_KEY" in p for p in _problems(SECRET_KEY=secret))


def test_a_placeholder_admin_secret_is_refused():
    assert any("ADMIN_SECRET" in p for p in _problems(ADMIN_SECRET="changeme"))


def test_a_weak_admin_password_is_refused():
    assert any("ADMIN_PASSWORD" in p for p in _problems(ADMIN_PASSWORD="short"))


@pytest.mark.parametrize("tenant", ["tenant_acme", "TENANT_ACME", "  tenant_acme  ", ""])
def test_the_demo_tenant_may_not_be_the_production_admin_tenant(tenant):
    """Found by the pre-launch audit: a production boot against a fresh,
    migrated Postgres created its root admin under `tenant_acme` - the id every
    fixture path in the tree writes to (core/seed.py, domain_seed,
    workforce_seed.SEED_TENANT, scripts/seed_master). Real records would then
    share a tenant with the demo data, and one mis-set ENVIRONMENT would mix
    fictional employees and invoices into live rows."""
    assert any("ADMIN_TENANT" in p for p in _problems(ADMIN_TENANT=tenant))


@pytest.mark.parametrize("origins", [["*"], ["https://app.kaeos.ai", "*"], [" * "]])
def test_a_wildcard_cors_origin_is_refused(origins):
    """The app mounts CORSMiddleware with allow_credentials=True. Starlette
    reflects the caller's Origin back for a wildcard, so any site a logged-in
    operator visits could read authenticated responses."""
    assert any("CORS_ORIGINS" in p for p in _problems(CORS_ORIGINS=origins))


def test_explicit_cors_origins_pass():
    assert _problems(CORS_ORIGINS=["https://app.kaeos.ai"]) == []


def test_sqlite_is_refused_in_a_production_environment():
    problems = _problems(ENVIRONMENT="production",
                         DATABASE_URL="sqlite+aiosqlite:///./kaeos.db")
    assert any("SQLite" in p for p in problems)


def test_postgres_passes_the_production_database_check():
    # A full production config (hosts, no demo seed, a data key) on Postgres.
    assert _problems(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql+asyncpg://db:5432/kaeos",
        ALLOWED_HOSTS=["api.kaeos.example.com"], SEED_DEMO_DATA=False, DEBUG=False,
        CONNECTOR_ENCRYPTION_KEY="b" * 44,
    ) == []


# ── launch audit 2026-10-17 ──────────────────────────────────────────────────

PROD = dict(GOOD, ENVIRONMENT="production", DATABASE_URL="postgresql+asyncpg://localhost:5432/kaeos",
            ALLOWED_HOSTS=["api.kaeos.example.com"], SEED_DEMO_DATA=False, DEBUG=False,
            CONNECTOR_ENCRYPTION_KEY="b" * 44)


def _prod(**overrides) -> list[str]:
    return Settings(**{**PROD, **overrides}).validate_production_security()


def test_a_correct_hosted_config_has_no_problems():
    assert _prod() == []
    assert _prod(KAEOS_MANAGED_CLOUD=True, STRIPE_API_KEY="sk_test_x",
                 STRIPE_WEBHOOK_SECRET="whsec_x") == []


def test_managed_stripe_without_a_webhook_secret_is_refused():
    """P3: an empty secret lets anyone forge a subscription.updated and take the
    Enterprise plan."""
    assert any("STRIPE_WEBHOOK_SECRET" in p for p in _prod(
        KAEOS_MANAGED_CLOUD=True, STRIPE_API_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET=""))


@pytest.mark.parametrize("override,needle", [
    (dict(ALLOWED_HOSTS=["*"]), "ALLOWED_HOSTS"),
    (dict(DEBUG=True), "DEBUG"),
    (dict(SEED_DEMO_DATA=True), "SEED_DEMO_DATA"),
    (dict(CONNECTOR_ENCRYPTION_KEY=""), "CONNECTOR_ENCRYPTION_KEY"),
])
def test_production_controls(override, needle):
    assert any(needle in p for p in _prod(**override))


@pytest.mark.parametrize("env", ["prd", "live", "eu-1", "Production", "staging"])
def test_unknown_environment_names_are_production_like(env):
    assert Settings(**{**PROD, "ENVIRONMENT": env}).is_production_like
    assert not Settings(**{**PROD, "ENVIRONMENT": "ci"}).is_production_like


def test_stripe_webhook_refuses_an_empty_secret():
    from app.services.stripe_bridge import StripeBillingProvider
    with pytest.raises(ValueError):
        StripeBillingProvider(object(), "").verify_webhook(b"{}", "t=1,v1=abc")
