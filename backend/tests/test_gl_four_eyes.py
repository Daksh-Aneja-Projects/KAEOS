"""SOX maker-checker four-eyes on the manual GL entry route.

POST /finance/gl/journal-entries is the human entry point into the ledger. A
manual JE must carry a distinct, attributable preparer (maker); the authenticated
posting operator is the approver. A self-prepared or unattributable manual JE is
blocked fail-closed (mirrors the operations purchase four-eyes SoD gate).

In DEV_MODE the authenticated principal is the dev tenant (tenant_acme / dev_user),
so `dev_user` is the poster/approver in every request below.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.finance.models.core import AccountType, ChartOfAccount, JournalEntry

_URL = "/api/v1/finance/gl/journal-entries"
_TENANT = "tenant_acme"


@pytest.fixture(autouse=True)
def _dev_mode():
    s = get_settings()
    prev = s.DEV_MODE
    s.DEV_MODE = True
    yield
    s.DEV_MODE = prev


async def _accounts(db):
    db.add_all([
        ChartOfAccount(tenant_id=_TENANT, account_code="1010", account_name="Cash",
                       account_type=AccountType.ASSET, normal_balance="DEBIT", is_active=True),
        ChartOfAccount(tenant_id=_TENANT, account_code="2000", account_name="Accounts Payable",
                       account_type=AccountType.LIABILITY, normal_balance="CREDIT", is_active=True),
    ])
    await db.commit()


def _body(prepared_by, **extra):
    body = {"description": "Manual adjusting entry", "prepared_by": prepared_by,
            "lines": [{"account_code": "1010", "debit": 100},
                      {"account_code": "2000", "credit": 100}]}
    body.update(extra)
    return body


async def test_self_prepared_manual_je_blocked(async_client: AsyncClient, db):
    await _accounts(db)
    # No preparer -> unattributable maker -> four-eyes unverifiable -> blocked.
    r = await async_client.post(_URL, json=_body(None))
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "segregation_of_duties"
    # Preparer == poster (dev_user) -> self-approval -> blocked.
    r2 = await async_client.post(_URL, json=_body("dev_user"))
    assert r2.status_code == 403
    # Nothing reached the ledger.
    jes = (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == _TENANT))).scalars().all()
    assert jes == []


async def test_two_identity_manual_je_posts(async_client: AsyncClient, db):
    await _accounts(db)
    r = await async_client.post(_URL, json=_body("alice@acme.com"))
    assert r.status_code == 200, r.text
    entry_id = r.json()["id"]
    db.expire_all()
    je = (await db.execute(select(JournalEntry).where(
        JournalEntry.id == entry_id))).scalar_one()
    assert je.created_by == "alice@acme.com"   # maker / preparer
    assert je.approved_by == "dev_user"        # distinct approver / poster
    assert je.approved_at is not None


async def test_reserved_system_source_hand_post_rejected(async_client: AsyncClient, db):
    await _accounts(db)
    # A human cannot masquerade a manual JE as an automated accrual to dodge SoD.
    r = await async_client.post(_URL, json=_body("alice@acme.com", source_module="AP_ACCRUAL"))
    assert r.status_code == 403
