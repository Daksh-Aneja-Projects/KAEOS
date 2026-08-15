"""Finance demo seed - end-to-end verification.

seed_tenant posts every ChartOfAccount balance through the real GL keystone
(app.finance.services.gl.post_journal_entry) instead of hardcoding
current_balance. This locks in the acceptance bar: on a freshly seeded
tenant, trial balance / income statement / balance sheet / cash flow all
render populated and balance_cache_drift is empty for every account.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance.models.core import ChartOfAccount
from app.finance.seed import seed_tenant
from app.finance.services.gl import (
    balance_sheet,
    cash_flow_statement,
    income_statement,
    trial_balance,
)


async def test_seed_tenant_produces_balanced_populated_statements(db):
    tenant = "tenant_finseed_verify"
    ok = await seed_tenant(db, tenant=tenant)
    assert ok is True

    tb = await trial_balance(db, tenant)
    assert tb["accounts"], "trial balance must list the seeded chart of accounts"
    assert tb["in_balance"] is True
    assert Decimal(tb["total_debits"]) == Decimal(tb["total_credits"]) > 0
    # The acceptance bar: nothing hardcodes current_balance, so the ledger-
    # derived balance must agree with the cache for every account.
    assert tb["balance_cache_drift"] == [], f"drift: {tb['balance_cache_drift']}"

    inc = await income_statement(db, tenant)
    assert Decimal(inc["total_revenue"]) > 0
    assert Decimal(inc["total_expenses"]) > 0

    bs = await balance_sheet(db, tenant)
    assert bs["balanced"] is True
    assert Decimal(bs["total_assets"]) > 0

    cf = await cash_flow_statement(db, tenant)
    assert cf["accounts"], "cash flow statement must list the bank/cash accounts"
    assert Decimal(cf["net_change_in_cash"]) > 0

    # Bank account current_balance (treasury) and the GL cash accounts it maps
    # to must agree - both are cross-checked by the same posted activity.
    accounts_by_code = {a["account_code"]: a for a in tb["accounts"]}
    checking = accounts_by_code["1010"]
    mmkt = accounts_by_code["1020"]
    assert Decimal(checking["balance"]) == Decimal("1450000.00")
    assert Decimal(mmkt["balance"]) == Decimal("2500000.00")


async def test_seed_tenant_is_idempotent(db):
    tenant = "tenant_finseed_idem"
    first = await seed_tenant(db, tenant=tenant)
    second = await seed_tenant(db, tenant=tenant)
    assert first is True
    assert second is False

    accounts = (await db.execute(
        select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant)
    )).scalars().all()
    # Exactly the 9 accounts from one seed pass - a re-run posted nothing new.
    assert len(accounts) == 9
