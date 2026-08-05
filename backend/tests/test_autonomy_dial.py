"""
v3 Phase 7 — the Autonomy Dial has real teeth.

The per-domain min_confidence set via /config/autonomy is what Gate 3 reads at
runtime (resolve_min_confidence). A domain without a policy falls back to the
platform default; a set policy overrides it.
"""

from app.core.config import get_settings
from app.services.autonomy_policy import invalidate, resolve_min_confidence



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


async def test_autonomy_api_distinguishes_governor_from_human(db):
    """The dial UI has to tell a machine decision from a person's.

    /config/autonomy previously returned only is_default, so a governor-tuned
    threshold rendered identically to one an executive chose. Reporting a
    machine's decision as a human's is the failure mode this product exists to
    prevent, so auto_managed is part of the contract.
    """
    from app.api.routes.platform_config import get_autonomy
    from app.models.settings import AutonomyPolicy

    tid = "tenant_dial_attr"
    db.add(AutonomyPolicy(tenant_id=tid, domain="finance", min_confidence=0.91,
                          auto_managed=True))
    db.add(AutonomyPolicy(tenant_id=tid, domain="hr", min_confidence=0.70,
                          auto_managed=False))
    await db.commit()

    by_domain = {i.domain: i for i in await get_autonomy(tenant_id=tid, db=db)}

    assert by_domain["finance"].auto_managed is True     # governor tuned it
    assert by_domain["finance"].is_default is False
    assert by_domain["hr"].auto_managed is False         # a person set it
    assert by_domain["hr"].is_default is False
    # An untouched domain is the platform default and belongs to nobody.
    assert by_domain["sales"].is_default is True
    assert by_domain["sales"].auto_managed is False


async def test_every_governed_domain_is_visible_and_overridable(db):
    """Whatever the governor can tune, a human must be able to see and take back.

    The domain list was hardcoded to seven, but the governor derives domains from
    the executed skill's department and will happily create a dial for marketing
    or customer_support. Those dials were enforced by Gate 3 while being absent
    from this response and rejected by the PUT, so "human override wins" did not
    hold for them: you cannot override a dial you cannot see or address.
    """
    import uuid
    import pytest
    from fastapi import HTTPException
    from app.api.routes.platform_config import get_autonomy, set_autonomy, AutonomyUpdate
    from app.models.settings import AutonomyPolicy
    from app.models.domain import Skill

    tid = "tenant_dial_domains"
    admin = {"tenant_id": tid, "name": "admin@x", "role": "admin"}

    # A dial the governor created for a non-canonical department...
    db.add(AutonomyPolicy(tenant_id=tid, domain="marketing", min_confidence=0.84,
                          auto_managed=True))
    # ...and a department that exists only as a skill, with no dial yet.
    db.add(Skill(id=str(uuid.uuid4()), skill_id="cs_skill", tenant_id=tid,
                 department="customer_support", status="ACTIVE", confidence=0.8))
    await db.commit()

    domains = {i.domain for i in await get_autonomy(tenant_id=tid, db=db)}
    assert "marketing" in domains, "a governed dial must not be invisible"
    assert "customer_support" in domains
    assert {"hr", "finance", "legal"} <= domains        # canonical seven still there

    # And a human can actually take marketing back from the governor.
    out = await set_autonomy("marketing", AutonomyUpdate(min_confidence=0.93),
                             tenant=admin, db=db)
    assert out.min_confidence == 0.93
    assert out.auto_managed is False                    # governor no longer owns it

    # A department that genuinely does not exist is still rejected.
    with pytest.raises(HTTPException):
        await set_autonomy("not_a_department", AutonomyUpdate(min_confidence=0.8),
                           tenant=admin, db=db)
