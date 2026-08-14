"""KAEOS compliance spine: the framework->checker registry is fail-closed and
the department checkers are deterministic. No LLM, no DB - pure functions."""
from app.compliance import CheckStatus, run_checks
from app.compliance.registry import list_frameworks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def test_unbacked_tag_fails_closed():
    """A made-up compliance tag must NOT silently pass (the old LLM-guess hole)."""
    res = run_checks(["TOTALLY_MADE_UP"], {})
    assert res["verified"] is False
    assert _status(res, "TOTALLY_MADE_UP") == CheckStatus.UNBACKED.value
    assert res["blocking"]


def test_registered_frameworks_are_listed():
    tags = {f["framework"] for f in list_frameworks()}
    assert {"EEOC", "FLSA", "I9", "SOX", "ECOA"} <= tags


def test_eeoc_blocks_on_adverse_impact():
    adverse = {"gender": {"female": {"selected": 5, "total": 100},
                          "male": {"selected": 60, "total": 100}}}
    res = run_checks(["EEOC"], {"cohort_outcomes": adverse})
    assert _status(res, "EEOC") == CheckStatus.BLOCK.value
    assert res["verified"] is False

    fair = {"gender": {"female": {"selected": 48, "total": 100},
                       "male": {"selected": 50, "total": 100}}}
    res = run_checks(["EEOC"], {"cohort_outcomes": fair})
    assert _status(res, "EEOC") == CheckStatus.PASS.value


def test_flsa_overtime_math():
    # 50h at $20/h: 10 OT hours owed 10*20*1.5 = $300. Paid only $200 -> block.
    under = {"timecards": [{"employee_id": "e1", "hours": 50, "hourly_rate": 20,
                            "overtime_paid": 200}]}
    assert _status(run_checks(["FLSA"], under), "FLSA") == CheckStatus.BLOCK.value
    ok = {"timecards": [{"employee_id": "e1", "hours": 50, "hourly_rate": 20,
                         "overtime_paid": 300}]}
    assert _status(run_checks(["FLSA"], ok), "FLSA") == CheckStatus.PASS.value
    # Exempt employees are not owed overtime.
    exempt = {"timecards": [{"employee_id": "e2", "exempt": True, "hours": 60,
                             "hourly_rate": 50, "overtime_paid": 0}]}
    assert _status(run_checks(["FLSA"], exempt), "FLSA") == CheckStatus.PASS.value


def test_i9_section2_deadline():
    late = {"i9": {"hire_date": "2026-03-02", "section1_date": "2026-03-02",
                   "section2_date": "2026-03-10"}}  # >3 business days
    assert _status(run_checks(["I9"], late), "I9") == CheckStatus.BLOCK.value
    ok = {"i9": {"hire_date": "2026-03-02", "section1_date": "2026-03-02",
                 "section2_date": "2026-03-04"}}
    assert _status(run_checks(["I9"], ok), "I9") == CheckStatus.PASS.value


def test_sox_segregation_and_approval():
    assert _status(run_checks(["SOX"], {"is_financial": True,
                   "has_human_approver": False}), "SOX") == CheckStatus.BLOCK.value
    assert _status(run_checks(["SOX"], {"has_human_approver": True,
                   "maker": "a@x", "approver": "a@x"}), "SOX") == CheckStatus.BLOCK.value
    assert _status(run_checks(["SOX"], {"has_human_approver": True,
                   "maker": "a@x", "approver": "b@x"}), "SOX") == CheckStatus.PASS.value


def test_ecoa_adverse_action_notice():
    # Denial with only a generic reason -> block.
    bad = {"decision": "DENY", "adverse_action": {"reasons": ["credit score"]}}
    assert _status(run_checks(["ECOA"], bad), "ECOA") == CheckStatus.BLOCK.value
    # Denial with specific reasons, timely, no prohibited basis -> pass.
    good = {"decision": "DENY", "adverse_action": {
        "reasons": ["Debt-to-income ratio of 62% exceeds the 45% program limit",
                    "Two 90-day delinquencies in the last 12 months"],
        "notice_days": 7, "prohibited_basis_used": False}}
    assert _status(run_checks(["ECOA"], good), "ECOA") == CheckStatus.PASS.value
    # Approvals are out of scope for adverse-action.
    assert _status(run_checks(["ECOA"], {"decision": "APPROVE"}),
                   "ECOA") == CheckStatus.NOT_APPLICABLE.value
