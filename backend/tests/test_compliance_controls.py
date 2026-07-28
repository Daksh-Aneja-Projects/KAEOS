"""Controls-evidence inventory: proves the audit-readiness report is real,
honest, and internally consistent - and never claims an external attestation as
satisfied."""
from app.services import compliance_controls as cc
from app.services.compliance_controls import ControlStatus


def test_report_shape_and_counts():
    report = cc.build_controls_report()
    s = report["summary"]
    assert s["total"] == s["implemented"] + s["operational"] + s["external"]
    assert s["implemented"] >= 10, "the technical controls should be substantial"
    assert s["external"] >= 1, "external attestation must be listed as a gap, not hidden"


def test_external_attestation_never_marked_implemented():
    """Certification is a third-party audit; it must never read as done."""
    report = cc.build_controls_report()
    for c in report["controls"]:
        if "attestation" in c["name"].lower() or "penetration" in c["name"].lower():
            assert c["status"] != ControlStatus.IMPLEMENTED


def test_implemented_controls_cite_evidence():
    report = cc.build_controls_report()
    for c in report["controls"]:
        if c["status"] == ControlStatus.IMPLEMENTED:
            assert c["evidence"], f"{c['id']} claims implemented but cites no evidence"
            assert c["frameworks"], f"{c['id']} maps to no framework"


def test_framework_coverage_cross_references_controls():
    report = cc.build_controls_report()
    cov = report["framework_coverage"]
    # The headline regimes must each be covered by at least one implemented control.
    for fw in ("SOC2", "ISO27001", "GDPR"):
        assert cov.get(fw), f"no implemented control maps to {fw}"


def test_report_carries_the_honest_boundary():
    report = cc.build_controls_report()
    assert "NOT a certificate" in report["honest_note"]
