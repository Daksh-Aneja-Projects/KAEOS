"""M16: commission payouts get a hash-chained audit trail.

calculate_payout set is_approved on a money calculation and committed with no
ledger entry (auto-approving anything under $10k). It now writes a
COMMISSION_PAYOUT ledger event recording the amount, the approver, and the
beneficiary rep (traced through the opportunity) so a self-approval is
detectable on review."""
import pytest
from sqlalchemy import select

from app.models.domain import ProvenanceLedger
from app.sales.agents.commission_agent import CommissionAgent
from app.sales.models.commission import CommissionCalculation, CommissionPlan
from app.sales.models.pipeline import Opportunity

TENANT = "tenant_m16"


@pytest.mark.asyncio
async def test_payout_writes_ledger_with_approver_and_beneficiary(db):
    db.add(CommissionPlan(id="pl1", tenant_id=TENANT, plan_name="Std",
                          rep_id="rep-9", base_commission_rate=5.0))
    db.add(Opportunity(id="opp1", tenant_id=TENANT, name="Deal", stage="CLOSED_WON",
                       amount=100000, assigned_rep_id="rep-9"))
    db.add(CommissionCalculation(id="cc1", tenant_id=TENANT, plan_id="pl1",
                                 opportunity_id="opp1", deal_value=5000,
                                 calculated_payout=0))
    await db.commit()

    res = await CommissionAgent().calculate_payout(
        db, "cc1", TENANT, approver="ops@kaeos.test")
    assert res["calculated_payout"] == 250.0  # 5000 * 5%

    rows = (await db.execute(select(ProvenanceLedger).where(
        ProvenanceLedger.tenant_id == TENANT,
        ProvenanceLedger.event_type == "COMMISSION_PAYOUT"))).scalars().all()
    assert len(rows) == 1, "every payout must land a ledger entry"
    assert "ops@kaeos.test" in rows[0].reasoning     # who approved
    assert "rep-9" in rows[0].reasoning              # who benefits (four-eyes review)
