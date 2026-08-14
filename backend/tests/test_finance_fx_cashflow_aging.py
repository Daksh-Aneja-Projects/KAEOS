"""Finance upgrades (theme A): multi-currency FX safety in the GL, a
GL-derived cash-flow statement, and AR/AP aging from live invoice balances.

Before this, post_journal_entry copied the raw amount into amount_in_base with
no FX and balanced in nominal units, so a EUR line and a USD line would happily
"balance" at face value. Now every line converts to the tenant base currency
(USD default) via fin_fx_rates; a foreign line with no rate is refused.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor
from app.finance.models.accounts_receivable import (
    Customer,
    CustomerInvoice,
    CustomerInvoiceStatus,
)
from app.finance.models.core import AccountType, ChartOfAccount, FXRate, JournalEntry
from app.finance.services.gl import (
    GLPostingError,
    aging_report,
    cash_flow_statement,
    income_statement,
    post_journal_entry,
    trial_balance,
)


def _t():
    return f"tenant_fx_{uuid.uuid4().hex[:6]}"


# ── Multi-currency FX ──────────────────────────────────────────────────────

async def _fx_accounts(db, tenant):
    cash_eur = ChartOfAccount(tenant_id=tenant, account_code="1010",
                              account_name="Cash EUR", account_type=AccountType.ASSET,
                              normal_balance="DEBIT", currency="EUR", is_bank_account=True)
    revenue = ChartOfAccount(tenant_id=tenant, account_code="4000",
                             account_name="Revenue", account_type=AccountType.REVENUE,
                             normal_balance="CREDIT", currency="USD")
    db.add_all([cash_eur, revenue])
    await db.commit()
    return cash_eur, revenue


async def test_foreign_line_without_a_rate_is_refused(db):
    tenant = _t()
    cash_eur, revenue = await _fx_accounts(db, tenant)
    with pytest.raises(GLPostingError, match="no FX rate for EUR"):
        await post_journal_entry(db, tenant, lines=[
            {"account_id": cash_eur.id, "debit": 100},
            {"account_id": revenue.id, "credit": 110}],
            description="EUR sale, no rate loaded")
    await db.rollback()
    assert (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant))).scalars().all() == []


async def test_multicurrency_entry_balances_after_fx_conversion(db):
    tenant = _t()
    cash_eur, revenue = await _fx_accounts(db, tenant)
    db.add(FXRate(tenant_id=tenant, currency="EUR", base_currency="USD",
                  rate=Decimal("1.10"), as_of=date(2026, 1, 1)))
    await db.commit()

    cash_id = cash_eur.id  # capture before expire_all so the where-clause id is not reloaded
    # DR 100 EUR (=110 USD) / CR 110 USD -> balances in base only after FX.
    entry = await post_journal_entry(db, tenant, lines=[
        {"account_id": cash_eur.id, "debit": 100},
        {"account_id": revenue.id, "credit": 110}],
        description="EUR sale", entry_date=date(2026, 2, 1))
    assert float(entry.total_debit) == 110.00 == float(entry.total_credit)

    from app.finance.models.core import JournalLine
    lines = {l.currency: l for l in (await db.execute(select(JournalLine).where(
        JournalLine.journal_entry_id == entry.id))).scalars().all()}
    assert Decimal(str(lines["EUR"].amount_in_base)) == Decimal("110.00")  # 100 * 1.10
    assert float(lines["EUR"].exchange_rate) == 1.10
    # The EUR account's native balance stays in EUR (not converted).
    db.expire_all()
    acc = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    assert Decimal(str(acc.current_balance)) == Decimal("100.00")


async def test_face_value_multicurrency_no_longer_falsely_balances(db):
    tenant = _t()
    cash_eur, revenue = await _fx_accounts(db, tenant)
    db.add(FXRate(tenant_id=tenant, currency="EUR", base_currency="USD",
                  rate=Decimal("1.10"), as_of=date(2026, 1, 1)))
    await db.commit()
    # 100 EUR debit vs 100 USD credit: equal at face value, unbalanced in base.
    with pytest.raises(GLPostingError, match="unbalanced"):
        await post_journal_entry(db, tenant, lines=[
            {"account_id": cash_eur.id, "debit": 100},
            {"account_id": revenue.id, "credit": 100}],
            description="face-value mismatch", entry_date=date(2026, 2, 1))
    await db.rollback()


async def test_reports_aggregate_in_base_currency_not_native(db):
    """Regression: trial_balance / income_statement must sum amount_in_base, not
    the native debit/credit columns. Before the fix a 100 EUR (=110 USD) debit
    and a 110 USD credit reported as debits=100 / credits=110 - a fake trial-
    balance mismatch - and revenue read 110 only by luck of being USD. With a
    second currency the native sums are meaningless. Here we assert both sides
    reconcile at the base value 110.00."""
    tenant = _t()
    cash_eur, revenue = await _fx_accounts(db, tenant)
    db.add(FXRate(tenant_id=tenant, currency="EUR", base_currency="USD",
                  rate=Decimal("1.10"), as_of=date(2026, 1, 1)))
    await db.commit()
    await post_journal_entry(db, tenant, lines=[
        {"account_id": cash_eur.id, "debit": 100},   # 100 EUR -> 110 USD base
        {"account_id": revenue.id, "credit": 110}],  # 110 USD
        description="EUR sale", entry_date=date(2026, 2, 1))

    tb = await trial_balance(db, tenant)
    # Both totals are the BASE value; a native sum would give debits=100.00.
    assert tb["total_debits"] == "110.00"
    assert tb["total_credits"] == "110.00"
    eur_row = next(a for a in tb["accounts"] if a["account_code"] == "1010")
    assert eur_row["debits"] == "110.00"   # converted, not the native 100

    inc = await income_statement(db, tenant)
    assert inc["total_revenue"] == "110.00"


# ── Cash-flow statement ────────────────────────────────────────────────────

async def _cash_accounts(db, tenant):
    bank = ChartOfAccount(tenant_id=tenant, account_code="1010", account_name="Bank",
                          account_type=AccountType.ASSET, normal_balance="DEBIT",
                          is_bank_account=True)
    revenue = ChartOfAccount(tenant_id=tenant, account_code="4000", account_name="Revenue",
                             account_type=AccountType.REVENUE, normal_balance="CREDIT")
    expense = ChartOfAccount(tenant_id=tenant, account_code="6000", account_name="Rent",
                             account_type=AccountType.EXPENSE, normal_balance="DEBIT")
    db.add_all([bank, revenue, expense])
    await db.commit()
    return bank, revenue, expense


async def test_cash_flow_statement_nets_bank_movement_over_a_window(db):
    tenant = _t()
    bank, revenue, expense = await _cash_accounts(db, tenant)
    # Jan: +2000 cash in. Feb: -500 cash out. Only Feb is in the window.
    await post_journal_entry(db, tenant, lines=[
        {"account_code": "1010", "debit": 2000},
        {"account_code": "4000", "credit": 2000}],
        description="Jan sale", entry_date=date(2026, 1, 15))
    await post_journal_entry(db, tenant, lines=[
        {"account_code": "6000", "debit": 500},
        {"account_code": "1010", "credit": 500}],
        description="Feb rent", entry_date=date(2026, 2, 10))

    cf = await cash_flow_statement(db, tenant,
                                   period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
    assert cf["net_change_in_cash"] == "-500.00"
    bank_row = next(a for a in cf["accounts"] if a["account_code"] == "1010")
    assert bank_row["opening_balance"] == "2000.00"   # Jan inflow, before window
    assert bank_row["net_change"] == "-500.00"
    assert bank_row["closing_balance"] == "1500.00"

    # Inception-to-date sees both movements.
    full = await cash_flow_statement(db, tenant)
    assert full["net_change_in_cash"] == "1500.00"


# ── AR/AP aging ────────────────────────────────────────────────────────────

async def test_aging_buckets_open_balances_by_days_past_due(db):
    tenant = _t()
    today = date(2026, 6, 30)
    vendor = Vendor(tenant_id=tenant, vendor_code="V1", name="Acme Supply")
    customer = Customer(tenant_id=tenant, customer_code="C1", name="Beta Corp")
    db.add_all([vendor, customer])
    await db.commit()

    def _inv(due_offset, bal, status=InvoiceStatus.APPROVED):
        return Invoice(tenant_id=tenant, vendor_id=vendor.id,
                       invoice_number=f"INV-{uuid.uuid4().hex[:6]}",
                       invoice_date=today - timedelta(days=120),
                       due_date=today - timedelta(days=due_offset),
                       subtotal=bal, total_amount=bal, balance_due=bal, status=status)

    db.add_all([
        _inv(-10, 100),    # not yet due -> current
        _inv(15, 200),     # 1-30
        _inv(45, 400),     # 31-60
        _inv(200, 800),    # over_90
        _inv(5, 999, status=InvoiceStatus.PAID),   # closed -> excluded
    ])
    # An AR invoice too.
    db.add(CustomerInvoice(tenant_id=tenant, customer_id=customer.id,
                           invoice_number="AR-1", invoice_date=today - timedelta(days=100),
                           due_date=today - timedelta(days=75), subtotal=300,
                           total_amount=300, balance_due=300,
                           status=CustomerInvoiceStatus.OVERDUE))
    await db.commit()

    rep = await aging_report(db, tenant, side="both", as_of=today)
    ap = rep["accounts_payable"]["buckets"]
    assert ap["current"] == "100.00"
    assert ap["1_30"] == "200.00"
    assert ap["31_60"] == "400.00"
    assert ap["over_90"] == "800.00"
    assert rep["accounts_payable"]["total_outstanding"] == "1500.00"  # PAID excluded
    assert rep["accounts_payable"]["open_count"] == 4

    ar = rep["accounts_receivable"]["buckets"]
    assert ar["61_90"] == "300.00"       # 75 days past due
    assert rep["accounts_receivable"]["total_outstanding"] == "300.00"
