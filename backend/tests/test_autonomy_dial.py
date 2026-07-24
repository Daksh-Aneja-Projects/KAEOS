"""
v3 Phase 7 — the Autonomy Dial has real teeth.

The per-domain min_confidence set via /config/autonomy is what Gate 3 reads at
runtime (resolve_min_confidence). A domain without a policy falls back to the
platform default; a set policy overrides it.
"""
import pytest

from app.core.config import get_settings
from app.services.autonomy_policy import invalidate, resolve_min_confidence

pytestmark = pytest.mark.asyncio


async def _ensure_app_tables():
    # resolve_min_confidence reads the app engine (AsyncSessionLocal), which the
    # unit harness does not migrate by default; create the schema on it once.
    from app.core.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_default_when_no_policy():
    invalidate("tenant_ad_none")
    assert await resolve_min_confidence("tenant_ad_none", "finance") == get_settings().CONFIDENCE_AUTONOMOUS_EXEC


async def test_no_domain_returns_default():
    assert await resolve_min_confidence("t", None) == get_settings().CONFIDENCE_AUTONOMOUS_EXEC


async def test_policy_overrides_default():
    await _ensure_app_tables()
    from app.core.database import AsyncSessionLocal
    from app.models.settings import AutonomyPolicy

    invalidate("tenant_adx")
    async with AsyncSessionLocal() as s:
        s.add(AutonomyPolicy(tenant_id="tenant_adx", domain="finance", min_confidence=0.95))
        await s.commit()
    invalidate("tenant_adx", "finance")

    # Set domain uses its policy; unset domain falls back to the default.
    assert await resolve_min_confidence("tenant_adx", "finance") == 0.95
    assert await resolve_min_confidence("tenant_adx", "hr") == get_settings().CONFIDENCE_AUTONOMOUS_EXEC
