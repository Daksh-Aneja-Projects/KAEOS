"""H17: the support + operations litigable estate can be placed on legal hold.

LegalHoldMixin was on the HR/finance/legal/healthcare/lending/engineering/sales
record tables, but sup_tickets (Ticket) and the ops_purchase_* estate
(PurchaseRequest, PurchaseOrder) were exempt by omission - litigation-hold
evasion by omission. The erasure/retention guards are generic ("on_legal_hold"
in table.c -> preserve), so adding the column via the mixin auto-covers them."""
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.operations.models.procurement import PurchaseOrder, PurchaseRequest
from app.support.models.tickets import Ticket


@pytest.mark.parametrize("model", [Ticket, PurchaseRequest, PurchaseOrder])
def test_litigable_estate_carries_the_hold_flag(model):
    assert "on_legal_hold" in model.__table__.c, \
        f"{model.__name__} must carry the legal-hold flag (H17)"


def test_erasure_guard_covers_the_new_tables():
    """The shared preservation guard excludes held rows on any table with the
    column — so the three newly-flagged tables are covered without a registry."""
    from app.services.privacy_erasure import _skip_held
    for model in (Ticket, PurchaseRequest, PurchaseOrder):
        stmt = _skip_held(select(model.__table__), model.__table__)
        assert "on_legal_hold" in str(stmt), \
            f"{model.__name__} rows on hold must be excluded from erasure"


@pytest.mark.asyncio
async def test_held_ticket_flag_persists():
    async with AsyncSessionLocal() as db:
        t = Ticket(tenant_id="tenant_h17", ticket_number="T-HOLD-1",
                   subject="dispute evidence", description="held for litigation",
                   on_legal_hold=True)
        db.add(t)
        await db.commit()
        row = (await db.execute(select(Ticket).where(
            Ticket.ticket_number == "T-HOLD-1"))).scalar_one()
        assert row.on_legal_hold is True
