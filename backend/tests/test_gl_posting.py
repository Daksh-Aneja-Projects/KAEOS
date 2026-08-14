"""The GL posting keystone (review theme B - Phase 3).

JournalEntry/JournalLine/ChartOfAccount existed as display-only schemas:
nothing ever posted, current_balance never moved, and no balancing check
existed - an unbalanced entry would have posted. post_journal_entry is now
the only write path: fail-closed double entry, atomic balance movement,
sequential numbering, ledger-derived trial balance, append-only reversals.
"""
import uuid

import pytest
from decimal import Decimal

from app.finance.models.core import (
    AccountType,
    ChartOfAccount,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from app.finance.services.gl import (
    GLPostingError,
    PeriodClosedError,
    balance_sheet,
    income_statement,
    post_journal_entry,
    reverse_journal_entry,
    set_period_status,
    trial_balance,
)
from sqlalchemy import select


def _t():
    return f"tenant_gl_{uuid.uuid4().hex[:6]}"


async def _accounts(db, tenant):
    cash = ChartOfAccount(tenant_id=tenant, account_code="1010",
                          account_name="Cash", account_type=AccountType.ASSET,
                          normal_balance="DEBIT")
    revenue = ChartOfAccount(tenant_id=tenant, account_code="4000",
                             account_name="Revenue", account_type=AccountType.REVENUE,
                             normal_balance="CREDIT")
    expense = ChartOfAccount(tenant_id=tenant, account_code="6000",
                             account_name="Rent Expense", account_type=AccountType.EXPENSE,
                             normal_balance="DEBIT")
    db.add_all([cash, revenue, expense])
    await db.commit()
    return cash, revenue, expense


async def test_balanced_entry_posts_and_moves_balances(db):
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)

    entry = await post_journal_entry(
        db, tenant,
        lines=[
            {"account_id": cash.id, "debit": 1500.00},
            {"account_id": revenue.id, "credit": 1500.00},
        ],
        description="Invoice INV-001 paid",
        source_module="AR",
    )
    assert entry.status == JournalEntryStatus.POSTED
    assert entry.entry_number.startswith("JE-")
    assert float(entry.total_debit) == 1500.00 == float(entry.total_credit)

    cash_id, revenue_id, entry_id = cash.id, revenue.id, entry.id
    db.expire_all()
    cash = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    revenue = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == revenue_id))).scalar_one()
    assert Decimal(str(cash.current_balance)) == Decimal("1500.00")     # asset up on debit
    assert Decimal(str(revenue.current_balance)) == Decimal("1500.00")  # revenue up on credit

    lines = (await db.execute(select(JournalLine).where(
        JournalLine.journal_entry_id == entry_id))).scalars().all()
    assert len(lines) == 2


async def test_unbalanced_entry_is_refused_and_nothing_posts(db):
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)
    cash_id, revenue_id = cash.id, revenue.id

    with pytest.raises(GLPostingError, match="unbalanced"):
        await post_journal_entry(
            db, tenant,
            lines=[
                {"account_id": cash_id, "debit": 100.00},
                {"account_id": revenue_id, "credit": 99.99},
            ],
            description="off by a cent",
        )
    await db.rollback()
    assert (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant))).scalars().all() == []
    cash = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    assert Decimal(str(cash.current_balance or 0)) == Decimal("0")


async def test_zero_amount_both_sides_and_unknown_account_are_refused(db):
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)
    cash_id, revenue_id = cash.id, revenue.id

    # A 0/0 line is invalid per-line (before the zero-total defense even runs).
    with pytest.raises(GLPostingError, match="exactly one"):
        await post_journal_entry(db, tenant, lines=[
            {"account_id": cash_id, "debit": 0},
            {"account_id": revenue_id, "credit": 0}], description="nothing")
    await db.rollback()

    with pytest.raises(GLPostingError, match="exactly one"):
        await post_journal_entry(db, tenant, lines=[
            {"account_id": cash_id, "debit": 10, "credit": 10},
            {"account_id": revenue_id, "credit": 0}], description="both sides")
    await db.rollback()

    with pytest.raises(GLPostingError, match="not found"):
        await post_journal_entry(db, tenant, lines=[
            {"account_id": "nope", "debit": 10},
            {"account_id": revenue_id, "credit": 10}], description="ghost account")
    await db.rollback()


async def test_trial_balance_derives_from_the_ledger_and_balances(db):
    tenant = _t()
    cash, revenue, expense = await _accounts(db, tenant)

    await post_journal_entry(db, tenant, lines=[
        {"account_code": "1010", "debit": 2000},
        {"account_code": "4000", "credit": 2000}], description="sale")
    await post_journal_entry(db, tenant, lines=[
        {"account_code": "6000", "debit": 750},
        {"account_code": "1010", "credit": 750}], description="rent")

    tb = await trial_balance(db, tenant)
    assert tb["in_balance"] is True
    assert tb["total_debits"] == "2750.00" == tb["total_credits"]
    by_code = {a["account_code"]: a for a in tb["accounts"]}
    assert by_code["1010"]["balance"] == "1250.00"
    assert by_code["4000"]["balance"] == "2000.00"
    assert by_code["6000"]["balance"] == "750.00"
    assert tb["balance_cache_drift"] == [], "cache must agree with the ledger"


async def test_reversal_is_append_only_and_restores_balances(db):
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)

    entry = await post_journal_entry(db, tenant, lines=[
        {"account_id": cash.id, "debit": 500},
        {"account_id": revenue.id, "credit": 500}], description="sale")
    cash_id, revenue_id, entry_id = cash.id, revenue.id, entry.id
    mirror = await reverse_journal_entry(db, tenant, entry.id, actor="cfo@acme")
    mirror_ref = mirror.reference

    db.expire_all()
    original = (await db.execute(select(JournalEntry).where(
        JournalEntry.id == entry_id))).scalar_one()
    assert original.status == JournalEntryStatus.REVERSED
    assert mirror_ref == original.entry_number

    cash = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    revenue = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == revenue_id))).scalar_one()
    assert Decimal(str(cash.current_balance)) == Decimal("0.00")
    assert Decimal(str(revenue.current_balance)) == Decimal("0.00")

    tb = await trial_balance(db, tenant)
    assert tb["in_balance"] is True   # both entries stay in the ledger


async def test_entry_numbers_are_sequential_per_tenant(db):
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)
    e1 = await post_journal_entry(db, tenant, lines=[
        {"account_id": cash.id, "debit": 1},
        {"account_id": revenue.id, "credit": 1}], description="one")
    e2 = await post_journal_entry(db, tenant, lines=[
        {"account_id": cash.id, "debit": 2},
        {"account_id": revenue.id, "credit": 2}], description="two")
    n1 = int(e1.entry_number.rsplit("-", 1)[1])
    n2 = int(e2.entry_number.rsplit("-", 1)[1])
    assert n2 == n1 + 1


async def test_statements_derive_from_the_ledger_and_balance_sheet_balances(db):
    tenant = _t()
    cash, revenue, expense = await _accounts(db, tenant)
    ap = ChartOfAccount(tenant_id=tenant, account_code="2000",
                        account_name="Accounts Payable",
                        account_type=AccountType.LIABILITY, normal_balance="CREDIT")
    db.add(ap)
    await db.commit()

    # Earn 2000 cash revenue, incur 750 of expense on credit (unpaid payable).
    await post_journal_entry(db, tenant, lines=[
        {"account_code": "1010", "debit": 2000},
        {"account_code": "4000", "credit": 2000}], description="sale")
    await post_journal_entry(db, tenant, lines=[
        {"account_code": "6000", "debit": 750},
        {"account_code": "2000", "credit": 750}], description="accrue expense")

    pnl = await income_statement(db, tenant)
    assert pnl["total_revenue"] == "2000.00"
    assert pnl["total_expenses"] == "750.00"
    assert pnl["net_income"] == "1250.00"

    bs = await balance_sheet(db, tenant)
    assert bs["balanced"] is True                 # Assets = Liabilities + Equity
    assert bs["total_assets"] == "2000.00"        # cash
    assert bs["total_liabilities"] == "750.00"    # unpaid payable
    assert bs["total_equity"] == "1250.00"        # current-period earnings
    # Net income closes into equity as a synthetic line.
    assert any(e["account_name"] == "Current period earnings" for e in bs["equity"])


async def test_closed_period_refuses_back_dated_postings(db):
    from datetime import date
    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)
    cash_id, revenue_id = cash.id, revenue.id  # capture before any rollback expires them

    def _post(d):
        return post_journal_entry(db, tenant, lines=[
            {"account_id": cash_id, "debit": 100},
            {"account_id": revenue_id, "credit": 100}],
            description="sale", entry_date=d)

    # Open period posts fine.
    await _post(date(2026, 3, 15))
    # Close March 2026, then a back-dated entry into it is refused, nothing posts.
    await set_period_status(db, tenant, 2026, 3, close=True, actor="cfo@acme")
    with pytest.raises(PeriodClosedError, match="CLOSED"):
        await _post(date(2026, 3, 20))
    await db.rollback()
    # A different (open) month still posts.
    await _post(date(2026, 4, 1))
    # Reopen March and the correction posts.
    await set_period_status(db, tenant, 2026, 3, close=False, actor="cfo@acme")
    entry = await _post(date(2026, 3, 25))
    assert entry.status == JournalEntryStatus.POSTED


async def test_posting_lands_in_the_signed_provenance_ledger(db):
    from app.models.domain import ProvenanceLedger
    from app.services.provenance import TENANT_STREAM, verify_chain

    tenant = _t()
    cash, revenue, _ = await _accounts(db, tenant)
    await post_journal_entry(db, tenant, lines=[
        {"account_id": cash.id, "debit": 42},
        {"account_id": revenue.id, "credit": 42}], description="evidence")

    events = (await db.execute(select(ProvenanceLedger).where(
        ProvenanceLedger.tenant_id == tenant,
        ProvenanceLedger.event_type == "GL_POSTED"))).scalars().all()
    assert len(events) == 1
    verdict = await verify_chain(db, tenant, TENANT_STREAM)
    assert verdict["status"] == "VERIFIED"
