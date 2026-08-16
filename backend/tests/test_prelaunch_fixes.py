"""Regression tests for the pre-launch audit fixes.

Each test pins one confirmed audit finding so it cannot silently return:
  * retention.sweep_all_tenants used the wrong PK column and crashed every run;
  * skills.py HITL approve/reject skipped the department-scope gate hitl.py enforces;
  * neural /brain/ingest stored operator uploads with no injection/PII scrub;
  * privacy erasure covered HR only, never the lending applicant/borrower names;
  * Stripe webhooks never wrote Tenant.plan, decoupling entitlements from billing.
"""
import pytest
from sqlalchemy import select

TENANT = "tenant_acme"


def test_sweep_all_tenants_uses_real_pk_column():
    """sweep_all_tenants enumerates the tenants table by its real PK (tenant_id).

    The bug selected tenants_tbl.c.id, which raises AttributeError every run
    because the tenants PK is tenant_id. Pin it by source so it cannot regress;
    the function itself binds to the app AsyncSessionLocal, which the in-memory
    unit harness does not schema, so we assert the fix statically.
    """
    import inspect
    from app.services import retention
    src = inspect.getsource(retention.sweep_all_tenants)
    assert "tenants_tbl.c.tenant_id" in src
    assert "tenants_tbl.c.id)" not in src


def test_skills_hitl_endpoints_enforce_department_scope():
    """Both skills.py HITL resolve endpoints call check_department_scope, like hitl.py."""
    import inspect
    from app.api.routes import skills
    approve = inspect.getsource(skills.approve_hitl)
    reject = inspect.getsource(skills.reject_hitl)
    assert "check_department_scope" in approve, "approve_hitl lost its department gate"
    assert "check_department_scope" in reject, "reject_hitl lost its department gate"


def test_plan_from_items_reads_price_tier():
    """The Stripe plan tier is derived from price metadata/lookup_key/nickname."""
    from app.services.stripe_bridge import _plan_from_items
    assert _plan_from_items([{"price": {"metadata": {"plan": "business"}}}]) == "business"
    assert _plan_from_items([{"price": {"lookup_key": "team"}}]) == "team"
    assert _plan_from_items([{"price": {"nickname": "Enterprise"}}]) == "enterprise"
    # An unrecognised tier does not silently masquerade as a real plan.
    assert _plan_from_items([{"price": {"nickname": "mystery"}}]) is None
    assert _plan_from_items([]) is None


@pytest.mark.asyncio
async def test_stripe_subscription_deleted_falls_tenant_back_to_free(db):
    """A cancelled subscription resets Tenant.plan and drops the metered linkage."""
    from app.models.auth import Tenant
    from app.models.billing import BillingAccount
    from app.services.stripe_bridge import handle_webhook_event

    db.add(Tenant(tenant_id="tenant_cancel", name="Cancelme", plan="business"))
    db.add(BillingAccount(
        tenant_id="tenant_cancel", stripe_customer_id="cus_x",
        stripe_subscription_id="sub_x", stripe_meter_item_id="si_x", seats=5,
    ))
    await db.commit()

    res = await handle_webhook_event(db, {
        "id": "evt_del_1", "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_x", "id": "sub_x"}},
    })
    assert res["status"] == "processed"
    plan = await db.scalar(select(Tenant.plan).where(Tenant.tenant_id == "tenant_cancel"))
    assert plan == "free"
    acct = await db.scalar(
        select(BillingAccount).where(BillingAccount.tenant_id == "tenant_cancel"))
    assert acct.stripe_subscription_id is None
    assert acct.stripe_meter_item_id is None


@pytest.mark.asyncio
async def test_stripe_subscription_created_syncs_plan(db):
    """A subscription create with a plan-bearing price writes Tenant.plan."""
    from app.models.auth import Tenant
    from app.models.billing import BillingAccount
    from app.services.stripe_bridge import handle_webhook_event

    db.add(Tenant(tenant_id="tenant_up", name="Upgrademe", plan="free"))
    db.add(BillingAccount(tenant_id="tenant_up", stripe_customer_id="cus_up"))
    await db.commit()

    res = await handle_webhook_event(db, {
        "id": "evt_up_1", "type": "customer.subscription.created",
        "data": {"object": {"customer": "cus_up", "id": "sub_up", "status": "active",
                            "items": {"data": [
            {"id": "si_up", "quantity": 3,
             "price": {"lookup_key": "team", "recurring": {"usage_type": "metered"}}},
        ]}}},
    })
    assert res["status"] == "processed"
    plan = await db.scalar(select(Tenant.plan).where(Tenant.tenant_id == "tenant_up"))
    assert plan == "team"


@pytest.mark.asyncio
async def test_stripe_incomplete_subscription_does_not_grant_plan(db):
    """Fail-closed: a non-paying (incomplete/unpaid) subscription must NOT grant the
    paid tier — only active/trialing may. Locks in the status gate on entitlements."""
    from app.models.auth import Tenant
    from app.models.billing import BillingAccount
    from app.services.stripe_bridge import handle_webhook_event

    db.add(Tenant(tenant_id="tenant_inc", name="Incomplete", plan="free"))
    db.add(BillingAccount(tenant_id="tenant_inc", stripe_customer_id="cus_inc"))
    await db.commit()

    await handle_webhook_event(db, {
        "id": "evt_inc_1", "type": "customer.subscription.created",
        "data": {"object": {"customer": "cus_inc", "id": "sub_inc", "status": "incomplete",
                            "items": {"data": [
            {"id": "si_inc", "quantity": 1,
             "price": {"lookup_key": "team", "recurring": {"usage_type": "metered"}}},
        ]}}},
    })
    plan = await db.scalar(select(Tenant.plan).where(Tenant.tenant_id == "tenant_inc"))
    assert plan == "free", "an unpaid subscription must not unlock the paid tier"


@pytest.mark.asyncio
async def test_erasure_tombstones_lending_applicant_and_borrower(db):
    """Erasure by subject_ref clears lending applicant/borrower names, not just HR."""
    from app.lending.models.core import LoanApplication
    from app.lending.models.servicing import ServicedLoan
    from app.services.privacy_erasure import erase_subject

    app_row = LoanApplication(
        tenant_id=TENANT, application_number="APP-777",
        applicant_name="Jane Borrower", applicant_ref="cust-777",
        amount=25000, product="personal_loan", status="RECEIVED",
    )
    db.add(app_row)
    await db.commit()
    await db.refresh(app_row)
    db.add(ServicedLoan(
        tenant_id=TENANT, application_id=app_row.id, loan_number="LN-777",
        borrower_name="Jane Borrower", principal=25000, outstanding_principal=25000,
        apr=9.5, term_months=36, monthly_payment=800,
    ))
    await db.commit()

    receipt = await erase_subject(db, TENANT, subject_ref="cust-777", _journal=False)
    assert receipt["tables"].get("lnd_loan_applications", 0) >= 1
    assert receipt["tables"].get("lnd_serviced_loans", 0) >= 1

    name = await db.scalar(
        select(LoanApplication.applicant_name).where(LoanApplication.id == app_row.id))
    assert name != "Jane Borrower"
    bname = await db.scalar(
        select(ServicedLoan.borrower_name).where(ServicedLoan.application_id == app_row.id))
    assert bname != "Jane Borrower"


@pytest.mark.asyncio
async def test_erasure_preserves_rows_under_legal_hold(db):
    """Legal/litigation hold OVERRIDES right-to-erasure: a row with
    on_legal_hold=True must survive erase_subject untouched (GDPR Art.17(3);
    FRCP 37(e) anti-spoliation). Without the on_legal_hold column + guard this
    silently regresses to destroying held evidence."""
    from app.lending.models.core import LoanApplication
    from app.services.privacy_erasure import erase_subject

    held = LoanApplication(
        tenant_id=TENANT, application_number="APP-HOLD",
        applicant_name="Held Subject", applicant_ref="cust-hold",
        amount=25000, product="personal_loan", status="RECEIVED",
        on_legal_hold=True,
    )
    db.add(held)
    await db.commit()
    await db.refresh(held)

    await erase_subject(db, TENANT, subject_ref="cust-hold", _journal=False)

    name = await db.scalar(
        select(LoanApplication.applicant_name).where(LoanApplication.id == held.id))
    assert name == "Held Subject", "a row under legal hold must not be erased"


def test_recent_migrations_downgrade_and_reupgrade(tmp_path):
    """The 0045-0049 downgrades are exercised (they were never run by any test).

    Full round trip on a scratch SQLite DB: upgrade to head, downgrade back to
    the pre-session head, then re-upgrade. A broken downgrade fails here instead
    of during a production rollback.
    """
    import subprocess
    import sys
    import os
    import pathlib
    backend = pathlib.Path(__file__).resolve().parents[1]
    db = tmp_path / "mig_roundtrip.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "DEV_MODE": "true"}

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(backend), env=env, capture_output=True, text=True, timeout=300)

    up = alembic("upgrade", "head")
    assert up.returncode == 0, f"upgrade failed: {up.stderr[-800:]}"
    down = alembic("downgrade", "0044_tenant_branding")
    assert down.returncode == 0, f"downgrade failed: {down.stderr[-800:]}"
    reup = alembic("upgrade", "head")
    assert reup.returncode == 0, f"re-upgrade failed: {reup.stderr[-800:]}"


def test_rate_limiter_runs_after_tenant_resolution():
    """TenantMiddleware must be OUTER of RateLimitMiddleware so the limiter can
    key per-tenant. In Starlette user_middleware, index 0 is outermost, so the
    Tenant layer must sit at a lower index than the RateLimit layer.
    """
    from app.main import app
    from app.core.tenant import TenantMiddleware
    from app.core.middleware import RateLimitMiddleware

    names = [m.cls for m in app.user_middleware]
    tenant_i = names.index(TenantMiddleware)
    rate_i = names.index(RateLimitMiddleware)
    assert tenant_i < rate_i, (
        "TenantMiddleware must run before RateLimitMiddleware, or the limiter "
        "never sees request.state.tenant and silently keys by IP."
    )


def test_smtp_fails_closed_when_starttls_unsupported():
    """A TLS-configured SMTP send refuses cleartext unless explicitly allowed."""
    import smtplib
    from unittest.mock import MagicMock, patch
    from app.services import notifier

    def make_ctx():
        server = MagicMock()
        server.starttls.side_effect = smtplib.SMTPNotSupportedError()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=server)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx, server

    ctx, server = make_ctx()
    with patch.object(notifier.smtplib, "SMTP", return_value=ctx):
        with pytest.raises(RuntimeError):
            notifier._send_smtp_sync(
                {"host": "h", "to_addrs": ["a@b.c"], "use_tls": True}, "s", "b")
        server.sendmail.assert_not_called()

    ctx2, server2 = make_ctx()
    with patch.object(notifier.smtplib, "SMTP", return_value=ctx2):
        notifier._send_smtp_sync(
            {"host": "h", "to_addrs": ["a@b.c"], "use_tls": True,
             "allow_plaintext_fallback": True}, "s", "b")
        server2.sendmail.assert_called_once()


def test_brain_ingest_scrubs_untrusted_upload():
    """brain_ingest neutralizes injection and redacts PII before storing (source check)."""
    import inspect
    from app.api.routes import neural
    src = inspect.getsource(neural.brain_ingest)
    assert "prompt_guard.neutralize" in src, "ingest no longer neutralizes injection"
    assert "redact_structured_pii" in src, "ingest no longer redacts PII"
    assert "_INGEST_EXTS" in src, "ingest lost its file-type allowlist"
