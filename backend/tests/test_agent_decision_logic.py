"""
Unit tests for domain-agent deterministic decision logic.

Regression guards for wrong-output bugs found by a logic audit (and confirmed by
running agents over real onboarded data). Each of these previously produced a
silently wrong result on a money, safety, or risk path.
"""
import asyncio
from types import SimpleNamespace



# ── Commission: 0% rate must not become 10%; large payouts must not self-approve ─

class _FakeResult:
    def __init__(self, obj):
        self._obj = obj
    def scalar_one_or_none(self):
        return self._obj
    def scalar_one(self):
        return self._obj


class _FakeDB:
    def __init__(self, calc, plan):
        self._calc, self._plan = calc, plan
        self._calls = 0
    async def execute(self, *_a, **_k):
        self._calls += 1
        return _FakeResult(self._calc if self._calls == 1 else self._plan)
    def add(self, *_a):
        pass
    async def commit(self):
        pass


def _run_commission(deal_value, base_rate):
    from app.sales.agents.commission_agent import CommissionAgent
    calc = SimpleNamespace(id="c1", plan_id="p1", deal_value=deal_value,
                           calculated_payout=None, is_approved=None)
    plan = SimpleNamespace(id="p1", base_commission_rate=base_rate)
    db = _FakeDB(calc, plan)
    # tenant_id is required (no default) so a caller can never silently bill the
    # wrong tenant; _FakeDB ignores the filter, so the payout maths is unchanged.
    return asyncio.run(CommissionAgent().calculate_payout(db, "c1", "tenant_acme"))


def test_zero_commission_rate_is_respected_not_defaulted():
    # base_commission_rate = 0 must yield 0 payout, not 10% of the deal.
    out = _run_commission(1_000_000, 0.0)
    assert out["calculated_payout"] == 0.0, "0% rate silently became the 10% default"


def test_large_payout_does_not_self_approve():
    out = _run_commission(5_000_000, 10.0)   # $500k payout
    assert out["is_approved"] is False
    assert out["status"] == "PENDING_HUMAN_APPROVAL"


def test_small_payout_auto_approves():
    out = _run_commission(50_000, 10.0)      # $5k payout
    assert out["is_approved"] is True
    assert out["status"] == "APPROVED"


# ── Facility: missing/unknown severity must not downgrade a safety issue ────────

def _facility(data):
    from app.operations.agents.facility_agent import FacilityAgent
    return asyncio.run(FacilityAgent().prioritize_work_order(data))


def test_gas_leak_without_severity_is_urgent():
    out = _facility({"issue_title": "Gas leak in server room"})
    assert out["priority"] == "URGENT"
    assert out["safety_flagged"] is True


def test_unknown_severity_routes_to_triage_not_medium():
    out = _facility({"issue_title": "Weird noise", "severity": "SEV1"})
    # "SEV1" is an urgent severity token — must escalate, not fall to MEDIUM.
    assert out["priority"] == "URGENT"


def test_unrecognized_severity_needs_triage():
    out = _facility({"issue_title": "Lightbulb out", "severity": "banana"})
    assert out["priority"] == "NEEDS_TRIAGE"


def test_explicit_low_is_low():
    out = _facility({"issue_title": "Repaint hallway", "severity": "LOW"})
    assert out["priority"] == "LOW"
