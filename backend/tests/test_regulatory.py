"""v3 Phase 6 — Regulatory & Risk Autopilot.

Risk tiers, control mapping, and the monitor are computed from real skills and
executions. Verifies EU-AI-Act-style classification and the overview aggregation.
"""
import uuid


from app.models.domain import Skill
from app.services import regulatory



def _skill(skill_id, dept, tags, conf=0.9):
    return Skill(id=str(uuid.uuid4()), skill_id=skill_id, tenant_id="t",
                 department=dept, domain=dept, status="ACTIVE", confidence=conf,
                 compliance_tags=tags)


def test_regulated_and_high_consequence_is_high_risk():
    r = regulatory.classify_risk(_skill("vendor_payment_approval", "finance", ["SOX"]))
    assert r["risk_tier"] == "HIGH"
    assert "human_oversight" in r["obligations"]


def test_regulated_low_confidence_is_high_risk():
    r = regulatory.classify_risk(_skill("hr_screen", "hr", ["EEOC"], conf=0.6))
    assert r["risk_tier"] == "HIGH"


def test_regulated_only_is_limited():
    r = regulatory.classify_risk(_skill("privacy_review", "legal", ["GDPR"], conf=0.95))
    assert r["risk_tier"] == "LIMITED"


def test_high_consequence_only_is_limited():
    r = regulatory.classify_risk(_skill("code_deploy", "engineering", [], conf=0.95))
    assert r["risk_tier"] == "LIMITED"  # 'deploy' is high-consequence


def test_plain_skill_is_minimal():
    r = regulatory.classify_risk(_skill("summarize_ticket", "support", [], conf=0.95))
    assert r["risk_tier"] == "MINIMAL"


async def test_overview_aggregates_register_and_control_map(db):
    t = "tenant_reg1"
    for s in [
        _skill("vendor_payment_approval", "finance", ["SOX"]),
        _skill("privacy_review", "legal", ["GDPR"], conf=0.95),
        _skill("summarize_ticket", "support", [], conf=0.95),
    ]:
        s.tenant_id = t
        db.add(s)
    await db.commit()

    ov = await regulatory.build_overview(db, t)
    assert ov["risk_summary"]["HIGH"] == 1
    assert ov["risk_summary"]["LIMITED"] == 1
    assert ov["risk_summary"]["MINIMAL"] == 1
    assert "SOX" in ov["control_map"] and "GDPR" in ov["control_map"]
    assert ov["risk_register"][0]["risk_tier"] == "HIGH"  # highest-risk first


async def test_evidence_pack_reports_covered_controls(db):
    import uuid as _uuid

    from app.models.domain import ProvenanceLedger, SkillExecution

    t = "tenant_reg2"
    s = _skill("vendor_payment_approval", "finance", ["SOX"])
    s.tenant_id = t
    db.add(s)
    # A hash-chained provenance row and a covered-control execution: without at
    # least one such row the pack is an assertion, not evidence (complete=False).
    chain_hash = _uuid.uuid4().hex
    db.add(ProvenanceLedger(tenant_id=t, rule_id="vendor_payment_approval",
                            event_type="AGENT_EXECUTION", chain_hash=chain_hash,
                            actor_role="agent", reasoning="approved vendor payment"))
    db.add(SkillExecution(id=str(_uuid.uuid4()), tenant_id=t,
                          skill_id_name="vendor_payment_approval",
                          status="SUCCESS_CLEAN", route_type="GATED_AGENT"))
    await db.commit()

    pack = await regulatory.evidence_pack(db, t, "SOX")
    assert pack["framework"] == "SOX"
    assert "vendor_payment_approval" in pack["controls"]
    assert pack["complete"] is True

    # Sampled rows, not just counts: an auditor can spot-verify the hash chain.
    assert pack["provenance_sample"], "evidence pack must carry sampled provenance rows"
    assert len(pack["provenance_sample"]) <= regulatory._EVIDENCE_SAMPLE_CAP
    assert pack["provenance_sample"][0]["chain_hash"] == chain_hash
    assert pack["control_executions_sample"], "covered-control executions must be sampled"
    assert all(r["skill_id_name"] == "vendor_payment_approval"
               for r in pack["control_executions_sample"])


async def test_evidence_pack_incomplete_without_rows(db):
    """Covered controls but zero ledger rows is not evidence -> complete=False."""
    t = "tenant_reg3"
    s = _skill("vendor_payment_approval", "finance", ["SOX"])
    s.tenant_id = t
    db.add(s)
    await db.commit()

    pack = await regulatory.evidence_pack(db, t, "SOX")
    assert "vendor_payment_approval" in pack["controls"]
    assert pack["complete"] is False
    assert pack["provenance_sample"] == []
