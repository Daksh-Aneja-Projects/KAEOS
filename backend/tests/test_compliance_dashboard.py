"""L13 Compliance dashboard — honesty contract.

Regression guard for the fabricated-compliance fix: the dashboard must count
REAL ``ComplianceViolation`` rows + framework-attributed governance blocks, use
a REAL ``last_audit`` timestamp, and NEVER auto-render COMPLIANT for a framework
that has coverage but no monitoring signal.
"""
import uuid
from datetime import datetime, timezone


from app.api.routes.dashboard import compliance_dashboard
from app.models.domain import Rule, Skill, SkillExecution
from app.hr.models.compliance import ComplianceViolation, ComplianceReport, ComplianceFramework


T = "tenant_test"
OTHER = "tenant_other"


def _rule(tenant, tags):
    return Rule(id=str(uuid.uuid4()), tenant_id=tenant, statement="s",
                trigger_json={}, action_json={}, compliance_tags=tags, is_archived=False)


def _skill(tenant, skill_id, tags, status="ACTIVE"):
    return Skill(id=str(uuid.uuid4()), skill_id=skill_id, tenant_id=tenant,
                 department="dept", domain="dept", status=status, confidence=0.9,
                 compliance_tags=tags)


def _exec(tenant, skill_id_name, status, when=None):
    return SkillExecution(id=str(uuid.uuid4()), tenant_id=tenant,
                          skill_id_name=skill_id_name, status=status,
                          started_at=when or datetime.now(timezone.utc))


def _violation(tenant, framework, severity, resolved=False):
    return ComplianceViolation(id=str(uuid.uuid4()), tenant_id=tenant, framework=framework,
                               severity=severity, description="d", resolved=resolved)


async def _run(db, tenant=T):
    resp = await compliance_dashboard(tenant_id=tenant, db=db)
    return {f.framework: f for f in resp.frameworks}


async def test_real_violations_flip_status_to_review(db):
    # GDPR has coverage + a monitored skill + a real unresolved BLOCKER violation.
    db.add(_rule(T, ["GDPR"]))
    db.add(_skill(T, "gdpr_dsar", ["GDPR"]))
    db.add(_exec(T, "gdpr_dsar", "COMPLETED"))
    db.add(_violation(T, "GDPR", "BLOCKER"))
    await db.commit()

    fw = (await _run(db))["GDPR"]
    assert fw.status == "REVIEW"
    assert fw.violations == 1
    assert fw.blocker_count == 1
    assert fw.last_audit is not None  # real timestamp from the violation/exec


async def test_governance_blocks_count_as_violations(db):
    # No ComplianceViolation rows, but a covered skill was BLOCKED_COMPLIANCE.
    db.add(_rule(T, ["SOX"]))
    db.add(_skill(T, "wire_approve", ["SOX"]))
    db.add(_exec(T, "wire_approve", "BLOCKED_COMPLIANCE"))
    await db.commit()

    fw = (await _run(db))["SOX"]
    assert fw.violations == 1          # attributed from the blocked execution
    assert fw.status == "REVIEW"


async def test_coverage_without_signal_is_unknown_not_compliant(db):
    # HIPAA is tagged on a rule and a skill, but nothing ever executed and there
    # are no violations/reports -> we do NOT know it is compliant.
    db.add(_rule(T, ["HIPAA"]))
    db.add(_skill(T, "phi_access", ["HIPAA"]))
    await db.commit()

    fw = (await _run(db))["HIPAA"]
    assert fw.status == "UNKNOWN"      # never auto-COMPLIANT
    assert fw.violations == 0
    assert fw.last_audit is None       # no fabricated audit date


async def test_monitored_clean_framework_is_compliant_with_real_audit(db):
    # CCPA has a covered skill that ran cleanly + a generated report -> COMPLIANT
    # with a real last_audit date, zero violations.
    db.add(_rule(T, ["GDPR"]))  # report framework enum uses GDPR; use GDPR here
    db.add(_skill(T, "privacy_review", ["GDPR"]))
    db.add(_exec(T, "privacy_review", "COMPLETED"))
    db.add(ComplianceReport(id=str(uuid.uuid4()), tenant_id=T,
                            framework=ComplianceFramework.GDPR, report_name="DPIA",
                            period_year=2026, data={}))
    await db.commit()

    fw = (await _run(db))["GDPR"]
    assert fw.status == "COMPLIANT"
    assert fw.violations == 0
    assert fw.last_audit is not None


async def test_resolved_violations_do_not_count(db):
    db.add(_rule(T, ["SOX"]))
    db.add(_skill(T, "je_post", ["SOX"]))
    db.add(_exec(T, "je_post", "COMPLETED"))
    db.add(_violation(T, "SOX", "BLOCKER", resolved=True))
    await db.commit()

    fw = (await _run(db))["SOX"]
    assert fw.violations == 0
    assert fw.status == "COMPLIANT"    # monitored + no *unresolved* violations


async def test_cross_tenant_isolation(db):
    # Another tenant's violations must never leak into this tenant's dashboard.
    db.add(_rule(T, ["GDPR"]))
    db.add(_skill(T, "gdpr_dsar", ["GDPR"]))
    db.add(_exec(T, "gdpr_dsar", "COMPLETED"))
    db.add(_violation(OTHER, "GDPR", "BLOCKER"))
    db.add(_exec(OTHER, "gdpr_dsar", "BLOCKED_COMPLIANCE"))
    await db.commit()

    fw = (await _run(db))["GDPR"]
    assert fw.violations == 0          # the other tenant's blocker is invisible
    assert fw.status == "COMPLIANT"
