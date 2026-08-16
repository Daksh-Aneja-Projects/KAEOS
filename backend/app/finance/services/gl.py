"""KAEOS Finance — the General Ledger posting keystone.

The review's ERP verdict was blunt: correct GL schemas that nothing ever
writes - `current_balance` never moved, no balancing check existed, an
unbalanced entry would have posted. This module is the missing transactional
core: EVERY ledger mutation goes through ``post_journal_entry``, which

  * refuses anything unbalanced (sum(debits) == sum(credits), Decimal math,
    no float drift) or empty, against inactive/foreign accounts,
  * assigns a race-safe sequential entry number per tenant (the composite
    unique (tenant_id, entry_number) arbitrates; the loser retries),
  * moves each account's ``current_balance`` by normal-balance convention in
    the SAME transaction as the entry and its lines, and
  * appends a signed provenance-ledger event atomically with the posting.

Statements derive from the ledger: ``trial_balance`` aggregates POSTED lines
(not the cached balances) and cross-checks the cache for drift. Corrections
are append-only: ``reverse_journal_entry`` posts a mirror entry - nothing is
ever edited or deleted.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.models.core import (
    ChartOfAccount,
    FiscalPeriod,
    FiscalPeriodStatus,
    FXRate,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")
_NUMBER_RETRIES = 5


class GLPostingError(ValueError):
    """The entry violates double-entry rules and was NOT posted."""


class PeriodClosedError(GLPostingError):
    """The entry falls in a CLOSED fiscal period and was NOT posted."""


async def _period_is_closed(db: AsyncSession, tenant_id: str, entry_date: date) -> bool:
    """A period blocks posting only if an explicit CLOSED row exists (absence =
    OPEN, so months need not be pre-created)."""
    status = (await db.execute(select(FiscalPeriod.status).where(
        FiscalPeriod.tenant_id == tenant_id,
        FiscalPeriod.fiscal_year == entry_date.year,
        FiscalPeriod.fiscal_period == entry_date.month,
    ))).scalar_one_or_none()
    return status == FiscalPeriodStatus.CLOSED


def _money(value) -> Decimal:
    """Parse a caller-supplied amount into exact cents; floats go through
    str() so 0.1+0.2 artifacts never reach the ledger."""
    try:
        d = Decimal(str(value if value is not None else 0)).quantize(_CENT)
    except (InvalidOperation, ValueError) as e:
        raise GLPostingError(f"unparseable amount {value!r}") from e
    if d < 0:
        raise GLPostingError(
            f"negative amount {d}; post the opposite side instead of a negative"
        )
    return d


async def _next_entry_number(db: AsyncSession, tenant_id: str, year: int) -> str:
    count = (await db.execute(
        select(sqlfunc.count(JournalEntry.id)).where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.fiscal_year == year,
        )
    )).scalar() or 0
    return f"JE-{year}-{count + 1:06d}"


def base_currency() -> str:
    """The tenant base (reporting) currency. Settings-driven, USD default."""
    from app.core.config import get_settings
    return (getattr(get_settings(), "FINANCE_BASE_CURRENCY", "USD") or "USD").upper()


async def _fx_rate(
    db: AsyncSession, tenant_id: str, currency: str, as_of: date, base: str,
) -> Optional[Decimal]:
    """Base units per 1 unit of ``currency`` at the most recent rate on/before
    ``as_of``. The base currency is always 1. Returns None when no rate exists -
    the caller refuses the line rather than posting an unconverted amount."""
    if (currency or base).upper() == base:
        return Decimal("1")
    rate = (await db.execute(
        select(FXRate.rate).where(
            FXRate.tenant_id == tenant_id,
            FXRate.currency == currency.upper(),
            FXRate.as_of <= as_of,
        ).order_by(FXRate.as_of.desc()).limit(1)
    )).scalar_one_or_none()
    return Decimal(str(rate)) if rate is not None else None


def _balance_delta(account: ChartOfAccount, debit: Decimal, credit: Decimal) -> Decimal:
    """A debit increases a normal-DEBIT account (assets, expenses); a credit
    increases a normal-CREDIT account (liabilities, equity, revenue)."""
    if (account.normal_balance or "DEBIT").upper() == "CREDIT":
        return credit - debit
    return debit - credit


# Reporting must aggregate in the tenant BASE currency, never native. A line's
# amount_in_base holds the FX-converted magnitude of its single non-zero side;
# CASE picks it back onto the right column. coalesce(...) falls back to the
# native amount for pre-FX rows (amount_in_base NULL) so historic ledgers still
# report. Without this, a multi-currency tenant would add e.g. EUR + USD
# magnitudes into one meaningless sum.
def _base_debits_sum():
    return sqlfunc.sum(
        case((JournalLine.debit > 0,
              sqlfunc.coalesce(JournalLine.amount_in_base, JournalLine.debit)),
             else_=0)
    )


def _base_credits_sum():
    return sqlfunc.sum(
        case((JournalLine.credit > 0,
              sqlfunc.coalesce(JournalLine.amount_in_base, JournalLine.credit)),
             else_=0)
    )


async def post_journal_entry(
    db: AsyncSession,
    tenant_id: str,
    *,
    lines: list[dict],
    description: str,
    entry_date: Optional[date] = None,
    reference: Optional[str] = None,
    source_module: str = "MANUAL",
    source_document_id: Optional[str] = None,
    created_by: Optional[str] = None,
    approved_by: Optional[str] = None,
    ai_categorized: bool = False,
    ai_confidence: Optional[float] = None,
) -> JournalEntry:
    """Post a balanced journal entry. The ONLY way anything reaches the GL.

    ``lines``: [{"account_id" | "account_code", "debit"?, "credit"?,
    "description"?, "department"?, "cost_center"?}]. Each line carries exactly
    one positive side. Raises GLPostingError (and posts NOTHING) on any
    violation - fail-closed is the point of a ledger.
    """
    if not description or not str(description).strip():
        raise GLPostingError("a journal entry requires a description")
    if not lines or len(lines) < 2:
        raise GLPostingError("double entry requires at least two lines")

    entry_date = entry_date or datetime.now(timezone.utc).date()
    if await _period_is_closed(db, tenant_id, entry_date):
        raise PeriodClosedError(
            f"fiscal period {entry_date.year}-{entry_date.month:02d} is CLOSED; "
            "post to an open period or reopen it before back-dating an entry"
        )

    # Resolve accounts (id or code), tenant-scoped, active only.
    ids = {str(l["account_id"]) for l in lines if l.get("account_id")}
    codes = {str(l["account_code"]) for l in lines if not l.get("account_id") and l.get("account_code")}
    if any(not l.get("account_id") and not l.get("account_code") for l in lines):
        raise GLPostingError("every line needs an account_id or account_code")

    accounts: dict[str, ChartOfAccount] = {}
    if ids:
        for acc in (await db.execute(select(ChartOfAccount).where(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.id.in_(ids)))).scalars().all():
            accounts[acc.id] = acc  # type: ignore[index]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
    if codes:
        for acc in (await db.execute(select(ChartOfAccount).where(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.account_code.in_(codes)))).scalars().all():
            accounts[acc.account_code] = acc  # type: ignore[index]  # sa-plugin: Numeric/PK column typed as unresolved _N | None

    base = base_currency()
    total_debit = Decimal("0")   # in tenant base currency, after FX
    total_credit = Decimal("0")
    resolved: list[tuple[ChartOfAccount, Decimal, Decimal, Decimal, Decimal, Decimal, dict]] = []
    for l in lines:
        key = str(l.get("account_id") or l.get("account_code"))
        acc = accounts.get(key)  # type: ignore[assignment]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
        if acc is None:
            raise GLPostingError(f"account {key!r} not found for this tenant")
        if not acc.is_active:
            raise GLPostingError(f"account {acc.account_code} is inactive")
        debit, credit = _money(l.get("debit")), _money(l.get("credit"))
        if (debit > 0) == (credit > 0):
            raise GLPostingError(
                f"line on {acc.account_code}: exactly one of debit/credit "
                f"must be positive (got debit={debit}, credit={credit})"
            )
        # Convert to base for balancing and amount_in_base. A foreign line with
        # no rate on/before entry_date is refused (fail-closed): the ledger never
        # holds an unconverted amount masquerading as base.
        acc_ccy = (acc.currency or base).upper()
        rate = await _fx_rate(db, tenant_id, acc_ccy, entry_date, base)
        if rate is None:
            raise GLPostingError(
                f"no FX rate for {acc_ccy}->{base} on/before {entry_date.isoformat()} "
                f"(account {acc.account_code}); load a fin_fx_rates row or post in {base}"
            )
        base_debit = (debit * rate).quantize(_CENT)
        base_credit = (credit * rate).quantize(_CENT)
        total_debit += base_debit
        total_credit += base_credit
        resolved.append((acc, debit, credit, base_debit, base_credit, rate, l))

    if total_debit != total_credit:
        raise GLPostingError(
            f"unbalanced entry: base debits {total_debit} != base credits {total_credit} "
            f"({base}); multi-currency entries must balance after FX conversion"
        )
    if total_debit == 0:
        raise GLPostingError("zero-amount entries are not postable")

    year = entry_date.year
    last_error: Exception | None = None
    for _attempt in range(_NUMBER_RETRIES):
        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_number=await _next_entry_number(db, tenant_id, year),
            entry_date=entry_date,
            posting_date=datetime.now(timezone.utc).date(),
            description=str(description).strip(),
            reference=reference,
            source_module=source_module,
            source_document_id=source_document_id,
            status=JournalEntryStatus.POSTED,
            total_debit=total_debit,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            total_credit=total_credit,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            created_by=created_by,
            # Maker-checker evidence: the API route records the preparer as
            # created_by and the distinct posting operator as approved_by. Service
            # callers (accruals, payments) leave approved_by None.
            approved_by=approved_by,
            approved_at=datetime.now(timezone.utc) if approved_by else None,
            ai_categorized=ai_categorized,
            ai_confidence=ai_confidence,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            fiscal_year=year,
            fiscal_period=entry_date.month,
        )
        try:
            async with db.begin_nested():
                db.add(entry)
        except IntegrityError as e:
            last_error = e  # lost the entry-number race; re-count and retry
            continue
        break
    else:
        raise GLPostingError(
            f"could not allocate an entry number after {_NUMBER_RETRIES} attempts"
        ) from last_error

    for i, (acc, debit, credit, base_debit, base_credit, rate, l) in enumerate(resolved, start=1):
        db.add(JournalLine(
            tenant_id=tenant_id,
            journal_entry_id=entry.id,
            account_id=acc.id,
            description=(l.get("description") or None),
            debit=debit,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            credit=credit,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            department=l.get("department"),
            cost_center=l.get("cost_center"),
            currency=acc.currency or base,
            exchange_rate=float(rate),  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            amount_in_base=base_debit if base_debit > 0 else base_credit,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            line_number=i,
        ))
        # Balance moves in the SAME transaction as the entry: a crash between
        # the two cannot exist.
        acc.current_balance = (  # type: ignore[assignment]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
            Decimal(str(acc.current_balance or 0)) + _balance_delta(acc, debit, credit)
        ).quantize(_CENT)

    # Signed evidence, atomic with the posting (the ledger writer commits this
    # session - entry, lines, balances and provenance land together).
    from app.services.provenance import append_ledger_event
    await append_ledger_event(
        db,
        tenant_id=tenant_id,
        event_type="GL_POSTED",
        actor_hash=None,
        actor_role=created_by or source_module,
        confidence_at=ai_confidence,
        reasoning=(f"Journal entry {entry.entry_number}: {entry.description} "
                   f"(debits {total_debit}, credits {total_credit}, "
                   f"{len(resolved)} lines, source {source_module})"),
    )
    await db.refresh(entry)
    logger.info("[GL] posted %s for %s: %s dr/cr %s",
                entry.entry_number, tenant_id, total_debit, total_credit)
    return entry


async def reverse_journal_entry(
    db: AsyncSession, tenant_id: str, entry_id: str, *, actor: Optional[str] = None,
) -> JournalEntry:
    """Reverse a POSTED entry with a mirror entry (append-only correction)."""
    original = (await db.execute(select(JournalEntry).where(
        JournalEntry.id == entry_id, JournalEntry.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if original is None:
        raise GLPostingError("journal entry not found")
    if original.status != JournalEntryStatus.POSTED:
        raise GLPostingError(f"only POSTED entries can be reversed "
                             f"(status={getattr(original.status, 'value', original.status)})")

    orig_lines = (await db.execute(select(JournalLine).where(
        JournalLine.journal_entry_id == original.id,
        JournalLine.tenant_id == tenant_id,
    ))).scalars().all()

    mirror = await post_journal_entry(
        db, tenant_id,
        lines=[{
            "account_id": l.account_id,
            "debit": l.credit,       # sides swapped
            "credit": l.debit,
            "description": f"Reversal of {original.entry_number}",
        } for l in orig_lines],
        description=f"Reversal of {original.entry_number}: {original.description}",
        # Reverse AT THE ORIGINAL ENTRY DATE so FX re-converts at the same rate
        # and amount_in_base offsets to exactly zero. Defaulting to today would
        # re-run FX at today's rate, leaving a residual base-currency imbalance
        # for multi-currency entries (native offsets, base would not).
        entry_date=original.entry_date,
        reference=original.entry_number,
        source_module=original.source_module or "MANUAL",
        source_document_id=original.id,
        created_by=actor,
    )
    original.status = JournalEntryStatus.REVERSED
    await db.commit()
    return mirror


async def trial_balance(db: AsyncSession, tenant_id: str,
                        as_of: Optional[date] = None) -> dict:
    """Derive the trial balance from POSTED lines - the ledger is the source
    of truth, not the cached ``current_balance`` (which is cross-checked and
    reported as drift when it disagrees)."""
    # POSTED lines only, aggregated first: with the status filter merely in an
    # outer-join condition, lines of DRAFT/VOIDED entries would still leak
    # their amounts into the sums.
    line_filters = [
        JournalLine.tenant_id == tenant_id,
        JournalEntry.status == JournalEntryStatus.POSTED,
    ]
    if as_of:
        line_filters.append(JournalEntry.entry_date <= as_of)
    line_agg = (
        select(
            JournalLine.account_id.label("account_id"),
            _base_debits_sum().label("debits"),
            _base_credits_sum().label("credits"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(*line_filters)
        .group_by(JournalLine.account_id)
        .subquery()
    )
    q = (
        select(
            ChartOfAccount.id,
            ChartOfAccount.account_code,
            ChartOfAccount.account_name,
            ChartOfAccount.account_type,
            ChartOfAccount.normal_balance,
            ChartOfAccount.current_balance,
            sqlfunc.coalesce(line_agg.c.debits, 0).label("debits"),
            sqlfunc.coalesce(line_agg.c.credits, 0).label("credits"),
        )
        .outerjoin(line_agg, line_agg.c.account_id == ChartOfAccount.id)
        .where(ChartOfAccount.tenant_id == tenant_id)
        .order_by(ChartOfAccount.account_code)
    )
    rows = (await db.execute(q)).all()

    accounts = []
    total_debits = Decimal("0")
    total_credits = Decimal("0")
    drift = []
    for r in rows:
        debits = Decimal(str(r.debits or 0)).quantize(_CENT)
        credits = Decimal(str(r.credits or 0)).quantize(_CENT)
        # NOTE: with as_of set, joined lines are date-filtered so drift vs the
        # live cache is expected; only the as_of=None view cross-checks.
        if (r.normal_balance or "DEBIT").upper() == "CREDIT":
            balance = credits - debits
        else:
            balance = debits - credits
        total_debits += debits
        total_credits += credits
        if as_of is None:
            cached = Decimal(str(r.current_balance or 0)).quantize(_CENT)
            if cached != balance:
                drift.append({"account_code": r.account_code,
                              "cached": str(cached), "derived": str(balance)})
        accounts.append({
            "account_id": r.id,
            "account_code": r.account_code,
            "account_name": r.account_name,
            "account_type": getattr(r.account_type, "value", r.account_type),
            "debits": str(debits),
            "credits": str(credits),
            "balance": str(balance),
        })

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "accounts": accounts,
        "total_debits": str(total_debits.quantize(_CENT)),
        "total_credits": str(total_credits.quantize(_CENT)),
        "in_balance": total_debits == total_credits,
        "balance_cache_drift": drift,
        "note": ("Derived from POSTED journal lines - the ledger is the "
                 "source of truth. balance_cache_drift lists accounts whose "
                 "cached running balance disagrees with the ledger."),
    }


# Account types whose balance sits on the debit side (a debit increases them).
# Statements sign by account TYPE, not the mutable normal_balance string, so a
# mis-seeded normal_balance can never flip a P&L or unbalance a balance sheet.
_DEBIT_NORMAL_TYPES = {"ASSET", "EXPENSE", "CONTRA_ASSET"}


async def _posted_balances(
    db: AsyncSession, tenant_id: str,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> list[dict]:
    """Per-account net balance over POSTED lines in [date_from, date_to],
    tenant-scoped. ``balance`` is signed by account type (positive = the
    account's natural side). Accounts with no activity in the window return a
    zero balance."""
    filters = [
        JournalLine.tenant_id == tenant_id,
        JournalEntry.status == JournalEntryStatus.POSTED,
    ]
    if date_from:
        filters.append(JournalEntry.entry_date >= date_from)
    if date_to:
        filters.append(JournalEntry.entry_date <= date_to)
    agg = (
        select(
            JournalLine.account_id.label("account_id"),
            _base_debits_sum().label("debits"),
            _base_credits_sum().label("credits"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(*filters)
        .group_by(JournalLine.account_id)
        .subquery()
    )
    q = (
        select(
            ChartOfAccount.account_code,
            ChartOfAccount.account_name,
            ChartOfAccount.account_type,
            sqlfunc.coalesce(agg.c.debits, 0).label("debits"),
            sqlfunc.coalesce(agg.c.credits, 0).label("credits"),
        )
        .outerjoin(agg, agg.c.account_id == ChartOfAccount.id)
        .where(ChartOfAccount.tenant_id == tenant_id)
        .order_by(ChartOfAccount.account_code)
    )
    rows = []
    for r in (await db.execute(q)).all():
        atype = getattr(r.account_type, "value", r.account_type)
        debits = Decimal(str(r.debits or 0)).quantize(_CENT)
        credits = Decimal(str(r.credits or 0)).quantize(_CENT)
        natural = (debits - credits) if atype in _DEBIT_NORMAL_TYPES else (credits - debits)
        rows.append({"account_code": r.account_code, "account_name": r.account_name,
                     "account_type": atype, "balance": natural})
    return rows


def _line(r: dict) -> dict:
    return {"account_code": r["account_code"], "account_name": r["account_name"],
            "amount": str(r["balance"])}


async def income_statement(
    db: AsyncSession, tenant_id: str,
    period_start: Optional[date] = None, period_end: Optional[date] = None,
) -> dict:
    """Profit & loss derived from POSTED lines. With no dates it is
    inception-to-date; period_start/period_end bound it to a reporting window.
    Net income = revenue - expenses."""
    rows = await _posted_balances(db, tenant_id, date_from=period_start, date_to=period_end)
    revenue, expense = [], []
    total_rev = Decimal("0")
    total_exp = Decimal("0")
    for r in rows:
        t = r["account_type"]
        if t in ("REVENUE", "CONTRA_REVENUE"):
            total_rev += r["balance"]
            if r["balance"] != 0:
                revenue.append(_line(r))
        elif t == "EXPENSE":
            total_exp += r["balance"]
            if r["balance"] != 0:
                expense.append(_line(r))
    net = (total_rev - total_exp).quantize(_CENT)
    return {
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "revenue": revenue,
        "total_revenue": str(total_rev.quantize(_CENT)),
        "expenses": expense,
        "total_expenses": str(total_exp.quantize(_CENT)),
        "net_income": str(net),
        "note": ("Derived from POSTED journal lines. A period with no posted "
                 "activity reads as zero - opening balances that were never "
                 "posted as journal entries do not appear here."),
    }


async def balance_sheet(
    db: AsyncSession, tenant_id: str, as_of: Optional[date] = None,
) -> dict:
    """Balance sheet derived from POSTED lines as of a date (inception-to-date
    by default). Current-period earnings (revenue - expenses) close into equity
    so the sheet balances without formal closing entries: Assets = Liabilities
    + Equity."""
    rows = await _posted_balances(db, tenant_id, date_to=as_of)
    assets, liabilities, equity = [], [], []
    ta = tl = te = tr = tx = Decimal("0")
    for r in rows:
        t, bal = r["account_type"], r["balance"]
        if t in ("ASSET", "CONTRA_ASSET"):
            ta += bal
            if bal != 0:
                assets.append(_line(r))
        elif t in ("LIABILITY", "CONTRA_LIABILITY"):
            tl += bal
            if bal != 0:
                liabilities.append(_line(r))
        elif t == "EQUITY":
            te += bal
            if bal != 0:
                equity.append(_line(r))
        elif t in ("REVENUE", "CONTRA_REVENUE"):
            tr += bal
        elif t == "EXPENSE":
            tx += bal
    net_income = (tr - tx).quantize(_CENT)
    equity.append({"account_code": "", "account_name": "Current period earnings",
                   "amount": str(net_income)})
    te = (te + net_income).quantize(_CENT)
    ta = ta.quantize(_CENT)
    tl = tl.quantize(_CENT)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "assets": assets,
        "total_assets": str(ta),
        "liabilities": liabilities,
        "total_liabilities": str(tl),
        "equity": equity,
        "total_equity": str(te),
        "balanced": ta == (tl + te),
        "note": ("Derived from POSTED journal lines. Current-period earnings "
                 "close into equity so Assets = Liabilities + Equity without "
                 "formal period-close entries."),
    }


def _valid_period(year: int, period: int) -> None:
    if not (1 <= int(period) <= 12):
        raise GLPostingError(f"fiscal_period must be 1-12 (got {period})")
    if not (1900 <= int(year) <= 2200):
        raise GLPostingError(f"fiscal_year out of range (got {year})")


async def set_period_status(
    db: AsyncSession, tenant_id: str, year: int, period: int, *,
    close: bool, actor: Optional[str] = None, note: Optional[str] = None,
) -> dict:
    """Close or reopen a fiscal period (idempotent). Closing stops back-dated
    postings into a reported period; reopening restores them. The row is
    created on first close - absence means OPEN."""
    _valid_period(year, period)
    row = (await db.execute(select(FiscalPeriod).where(
        FiscalPeriod.tenant_id == tenant_id,
        FiscalPeriod.fiscal_year == year,
        FiscalPeriod.fiscal_period == period,
    ))).scalar_one_or_none()
    new_status = FiscalPeriodStatus.CLOSED if close else FiscalPeriodStatus.OPEN
    if row is None:
        row = FiscalPeriod(tenant_id=tenant_id, fiscal_year=year, fiscal_period=period)
        db.add(row)
    row.status = new_status
    row.note = note
    if close:
        row.closed_by = actor
        row.closed_at = datetime.now(timezone.utc)
    else:
        row.closed_by = None
        row.closed_at = None
    await db.commit()
    logger.info("[GL] period %s-%02d %s by %s", year, period,
                new_status.value, actor or "system")
    return {"fiscal_year": year, "fiscal_period": period,
            "status": new_status.value,
            "closed_by": row.closed_by,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None}


async def _cash_by_account(
    db: AsyncSession, tenant_id: str,
    date_from: Optional[date], date_to: Optional[date],
) -> dict[str, dict]:
    """Debits/credits per cash/bank account (is_bank_account) over POSTED lines
    in [date_from, date_to], tenant-scoped. Keyed by account_id."""
    filters = [
        JournalLine.tenant_id == tenant_id,
        JournalEntry.status == JournalEntryStatus.POSTED,
        ChartOfAccount.is_bank_account.is_(True),
    ]
    if date_from:
        filters.append(JournalEntry.entry_date >= date_from)
    if date_to:
        filters.append(JournalEntry.entry_date <= date_to)
    q = (
        select(
            ChartOfAccount.id,
            ChartOfAccount.account_code,
            ChartOfAccount.account_name,
            sqlfunc.coalesce(_base_debits_sum(), 0).label("debits"),
            sqlfunc.coalesce(_base_credits_sum(), 0).label("credits"),
        )
        .select_from(ChartOfAccount)
        .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(*filters)
        .group_by(ChartOfAccount.id, ChartOfAccount.account_code, ChartOfAccount.account_name)
    )
    out: dict[str, dict] = {}
    for r in (await db.execute(q)).all():
        debits = Decimal(str(r.debits or 0)).quantize(_CENT)
        credits = Decimal(str(r.credits or 0)).quantize(_CENT)
        out[r.id] = {
            "account_code": r.account_code, "account_name": r.account_name,
            "net": (debits - credits).quantize(_CENT),   # cash rises on a debit
        }
    return out


async def cash_flow_statement(
    db: AsyncSession, tenant_id: str,
    period_start: Optional[date] = None, period_end: Optional[date] = None,
) -> dict:
    """Net change in cash/bank accounts over a window, derived from POSTED lines
    (not the cached CashFlow table). Net change = debits - credits (cash rises on
    a debit). Closing balance is inception-to period_end; opening = closing - net."""
    window = await _cash_by_account(db, tenant_id, period_start, period_end)
    closing = await _cash_by_account(db, tenant_id, None, period_end)

    accounts = []
    total_net = Decimal("0")
    for acc_id in sorted(set(window) | set(closing),
                         key=lambda i: (closing.get(i) or window[i])["account_code"]):
        net = window.get(acc_id, {}).get("net", Decimal("0"))
        close_bal = closing.get(acc_id, {}).get("net", Decimal("0"))
        meta = closing.get(acc_id) or window[acc_id]
        total_net += net
        accounts.append({
            "account_code": meta["account_code"],
            "account_name": meta["account_name"],
            "opening_balance": str((close_bal - net).quantize(_CENT)),
            "net_change": str(net.quantize(_CENT)),
            "closing_balance": str(close_bal.quantize(_CENT)),
        })
    return {
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "base_currency": base_currency(),
        "accounts": accounts,
        "net_change_in_cash": str(total_net.quantize(_CENT)),
        "note": ("Net movement of cash/bank accounts (is_bank_account) over POSTED "
                 "journal lines. Opening/closing are inception-to-date endpoints; "
                 "opening = closing - net_change."),
    }


_AGING_BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "over_90"


async def aging_report(
    db: AsyncSession, tenant_id: str, side: str = "both", as_of: Optional[date] = None,
) -> dict:
    """AR and/or AP aging: open invoice balances bucketed by (as_of - due_date)
    into current / 1-30 / 31-60 / 61-90 / 90+ days. Derived from live invoice
    balances (balance_due), not the denormalized aging_* columns."""
    from app.finance.models.accounts_payable import Invoice, InvoiceStatus
    from app.finance.models.accounts_receivable import (
        CustomerInvoice, CustomerInvoiceStatus,
    )

    as_of = as_of or datetime.now(timezone.utc).date()
    side = (side or "both").lower()

    async def _age(model, party_col, closed_statuses):
        rows = (await db.execute(
            select(model).where(
                model.tenant_id == tenant_id,
                model.balance_due > 0,
                model.status.notin_(closed_statuses),
            )
        )).scalars().all()
        buckets = {b: Decimal("0") for b in _AGING_BUCKETS}
        items, total = [], Decimal("0")
        for inv in rows:
            bal = Decimal(str(inv.balance_due or 0)).quantize(_CENT)
            days = (as_of - inv.due_date).days if inv.due_date else 0
            b = _bucket(days)
            buckets[b] += bal
            total += bal
            items.append({
                "invoice_number": inv.invoice_number,
                "party_id": getattr(inv, party_col),
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "days_overdue": max(0, days),
                "balance_due": str(bal),
                "bucket": b,
            })
        return {
            "buckets": {b: str(v.quantize(_CENT)) for b, v in buckets.items()},
            "total_outstanding": str(total.quantize(_CENT)),
            "open_count": len(items),
            "items": items,
        }

    result = {
        "as_of": as_of.isoformat(),
        "note": ("Open invoice balances bucketed by days past due_date, derived "
                 "from live balance_due (not the cached aging_* columns). 'current' "
                 "= not yet overdue."),
    }
    if side in ("ap", "both"):
        result["accounts_payable"] = await _age(
            Invoice, "vendor_id",
            [InvoiceStatus.PAID, InvoiceStatus.VOIDED])
    if side in ("ar", "both"):
        result["accounts_receivable"] = await _age(
            CustomerInvoice, "customer_id",
            [CustomerInvoiceStatus.PAID, CustomerInvoiceStatus.VOIDED,
             CustomerInvoiceStatus.WRITE_OFF])
    return result


async def list_periods(db: AsyncSession, tenant_id: str) -> dict:
    """Explicitly-tracked periods (closed ones, plus any reopened). Periods
    with no row are OPEN by default and not listed."""
    rows = (await db.execute(select(FiscalPeriod).where(
        FiscalPeriod.tenant_id == tenant_id
    ).order_by(FiscalPeriod.fiscal_year.desc(),
               FiscalPeriod.fiscal_period.desc()))).scalars().all()
    return {
        "periods": [{
            "fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period,
            "status": r.status.value if r.status is not None else None,
            "closed_by": r.closed_by,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        } for r in rows],
        "note": "Periods without a row are OPEN. Only closed/reopened periods are tracked.",
    }
