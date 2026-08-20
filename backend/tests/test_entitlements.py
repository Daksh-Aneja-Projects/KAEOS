"""Entitlements + usage rating + billing honesty (theme M / entitlements-stripe)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core import entitlements as ent
from app.models.auth import Tenant
from app.models.billing import SkillValueBaseline
from app.models.domain import SkillExecution


# ── plan -> entitlements map ────────────────────────────────────────────────
def test_plan_feature_map():
    assert ent.entitlements_for_plan("free") == frozenset()
    assert "webhooks" in ent.entitlements_for_plan("team")
    assert "sso" not in ent.entitlements_for_plan("team")
    assert ent.entitlements_for_plan("enterprise") == ent.FEATURES
    # Unknown/legacy plans fall to the most restrictive tier, never open.
    assert ent.entitlements_for_plan("standard") == frozenset()
    assert ent.entitlements_for_plan(None) == frozenset()


def test_allowance_monotonic():
    assert ent.allowance_for_plan("free") < ent.allowance_for_plan("team") < \
        ent.allowance_for_plan("business") < ent.allowance_for_plan("enterprise")


# ── require_entitlement dependency ──────────────────────────────────────────
async def test_require_entitlement_noop_selfhost(db, monkeypatch):
    monkeypatch.setattr(ent, "_managed_cloud", lambda: False)
    db.add(Tenant(tenant_id="t1", plan="free"))
    await db.commit()
    checker = ent.require_entitlement("sso")
    # Self-host: allowed regardless of plan (returns the tenant dict, no raise).
    tenant = {"tenant_id": "t1"}
    result = await _call_checker(checker, tenant, db)
    assert result == tenant


async def test_require_entitlement_denies_in_managed(db, monkeypatch):
    monkeypatch.setattr(ent, "_managed_cloud", lambda: True)
    db.add(Tenant(tenant_id="t2", plan="team"))  # team has webhooks, not sso
    await db.commit()
    checker = ent.require_entitlement("sso")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await _call_checker(checker, {"tenant_id": "t2"}, db)
    assert ei.value.status_code == 402


async def test_require_entitlement_grants_in_managed(db, monkeypatch):
    monkeypatch.setattr(ent, "_managed_cloud", lambda: True)
    db.add(Tenant(tenant_id="t3", plan="business"))
    await db.commit()
    checker = ent.require_entitlement("sso")
    result = await _call_checker(checker, {"tenant_id": "t3"}, db)
    assert result["tenant_id"] == "t3"


async def _call_checker(checker, tenant, db):
    # require_entitlement returns the closure `_checker(tenant, db)`; the FastAPI
    # Depends() defaults are bypassed by passing our args explicitly.
    return await checker(tenant=tenant, db=db)


# ── usage rating: blocked runs are counted ──────────────────────────────────
async def test_rating_counts_blocked_executions(db):
    from app.services.usage_rating import rate_tenant_period
    now = datetime.now(timezone.utc)
    db.add(Tenant(tenant_id="t4", plan="free"))
    for i, status in enumerate(["SUCCESS_CLEAN", "BLOCKED_COMPLIANCE", "PENDING_HITL"]):
        db.add(SkillExecution(
            id=f"e{i}", tenant_id="t4", skill_id_name="s", status=status,
            started_at=now,
        ))
    await db.commit()
    rating = await rate_tenant_period(db, "t4")
    # All three governed runs counted, including the blocked one.
    assert rating["metered_executions"] == 3
    assert rating["included_allowance"] == ent.allowance_for_plan("free")
    assert rating["overage_units"] == 0


async def test_rating_never_bills_unevaluated_rows(db):
    """A row the gate pipeline never evaluated is not a governed run.

    Regression for the predictive-ops ghost defect: rows stamped QUEUED (a
    status outside the ExecutionStatus vocabulary, drained by nothing) were
    counted and pushed to the billing provider as metered work.
    """
    from app.services.usage_rating import rate_tenant_period
    now = datetime.now(timezone.utc)
    db.add(Tenant(tenant_id="t4q", plan="free"))
    db.add(SkillExecution(id="q-real", tenant_id="t4q", skill_id_name="s",
                          status="SUCCESS_CLEAN", started_at=now))
    db.add(SkillExecution(id="q-ghost", tenant_id="t4q", skill_id_name="s",
                          status="QUEUED", route_type="ZERO_PROMPT_AUTO",
                          started_at=now))
    await db.commit()
    rating = await rate_tenant_period(db, "t4q")
    assert rating["metered_executions"] == 1  # the ghost is not billable


# ── ROI value delivered: honest null-with-note ──────────────────────────────
async def test_value_delivered_null_without_baseline(db):
    from app.api.routes.billing import _value_delivered
    db.add(SkillExecution(id="x1", tenant_id="t5", skill_id_name="s",
                          status="SUCCESS_CLEAN", started_at=datetime.now(timezone.utc)))
    await db.commit()
    value, note, priced = await _value_delivered(db, "t5")
    assert value is None
    assert priced == 0
    assert "baseline" in note.lower()


async def test_value_delivered_computed_with_baseline(db):
    from app.api.routes.billing import _value_delivered
    now = datetime.now(timezone.utc)
    # 30 min baseline at $120/hr = $60 per run; two clean runs = $120.
    db.add(SkillValueBaseline(tenant_id="t6", skill_id_name="triage",
                              baseline_minutes=30, loaded_hourly_rate_usd=Decimal("120.00")))
    for i in range(2):
        db.add(SkillExecution(id=f"y{i}", tenant_id="t6", skill_id_name="triage",
                              status="SUCCESS_CLEAN", started_at=now))
    # A blocked run of the same skill contributes nothing (not a clean success).
    db.add(SkillExecution(id="yb", tenant_id="t6", skill_id_name="triage",
                          status="BLOCKED_COMPLIANCE", started_at=now))
    await db.commit()
    value, note, priced = await _value_delivered(db, "t6")
    assert value == 120.0
    assert priced == 1


# ── stripe bridge: no-op self-host + webhook idempotency ────────────────────
async def test_noop_provider_disabled():
    from app.services.stripe_bridge import NoopBillingProvider
    p = NoopBillingProvider()
    assert p.enabled is False
    r = await p.report_usage(None, "t", None, 100)
    assert r["status"] == "noop"


async def test_webhook_idempotent(db):
    from app.services.stripe_bridge import handle_webhook_event
    from app.models.billing import StripeWebhookEvent
    event = {"id": "evt_1", "type": "invoice.paid", "data": {"object": {}}}
    first = await handle_webhook_event(db, event)
    assert first["status"] in ("processed", "acknowledged")
    second = await handle_webhook_event(db, event)
    assert second["status"] == "duplicate"
    rows = (await db.execute(
        __import__("sqlalchemy").select(StripeWebhookEvent)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].processed is True
