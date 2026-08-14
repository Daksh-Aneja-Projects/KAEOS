"""Engineering change-management checkers: deterministic, fail-closed.

PASS + BLOCK (and the NOT_APPLICABLE / ADVISORY branch) for each of SOC2,
ISO27001, and CHANGE_FREEZE. Also exercises the real deploy-agent context shape
(facts under ``context['facts']``) to prove the checkers read the fields the
agents actually produce.
"""
from app.compliance import CheckStatus, run_checks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


# --- SOC2 CC8.1 change management --------------------------------------------

def test_soc2_pass():
    ctx = {"environment": "production", "approvals": 2, "ci_passing": True,
           "ticket": "CHG-42"}
    assert _status(run_checks(["SOC2"], ctx), "SOC2") == CheckStatus.PASS.value


def test_soc2_blocks_failing_ci_on_prod():
    ctx = {"environment": "production", "approvals": 2, "ci_passing": False,
           "ticket": "CHG-42"}
    res = run_checks(["SOC2"], ctx)
    assert _status(res, "SOC2") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_soc2_blocks_zero_peer_review_on_prod():
    ctx = {"environment": "production", "approvals": 0, "ci_passing": True,
           "ticket": "CHG-42"}
    assert _status(run_checks(["SOC2"], ctx), "SOC2") == CheckStatus.BLOCK.value


def test_soc2_not_applicable_for_non_prod():
    ctx = {"environment": "staging", "ci_passing": False}
    assert _status(run_checks(["SOC2"], ctx), "SOC2") == CheckStatus.NOT_APPLICABLE.value


def test_soc2_advisory_when_evidence_thin():
    # Real deploy-agent shape: a pending deploy with no linked PR -> CI and
    # review unknown. Must not BLOCK (deploy is always-HITL), must not PASS.
    ctx = {"facts": {"environment": "production", "pr_ci_passing": None}}
    assert _status(run_checks(["SOC2"], ctx), "SOC2") == CheckStatus.ADVISORY.value


def test_soc2_reads_deploy_agent_facts():
    # facts.pr_ci_passing False -> BLOCK, proving nested-facts resolution works.
    ctx = {"facts": {"environment": "production", "pr_ci_passing": False,
                     "pr_risk": "HIGH"}, "approvals": 2}
    assert _status(run_checks(["SOC2"], ctx), "SOC2") == CheckStatus.BLOCK.value


# --- ISO 27001 change control ------------------------------------------------

def test_iso27001_pass():
    ctx = {"environment": "production", "rollback_plan": "revert to v2.13",
           "approver": "lead@x"}
    assert _status(run_checks(["ISO27001"], ctx), "ISO27001") == CheckStatus.PASS.value


def test_iso27001_blocks_missing_rollback_on_prod():
    ctx = {"environment": "production", "rollback_plan": False, "approver": "lead@x"}
    res = run_checks(["ISO27001"], ctx)
    assert _status(res, "ISO27001") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_iso27001_not_applicable_for_non_prod():
    ctx = {"environment": "dev", "rollback_plan": False}
    assert _status(run_checks(["ISO27001"], ctx),
                   "ISO27001") == CheckStatus.NOT_APPLICABLE.value


def test_iso27001_advisory_when_rollback_unknown():
    ctx = {"facts": {"environment": "production"}}
    assert _status(run_checks(["ISO27001"], ctx),
                   "ISO27001") == CheckStatus.ADVISORY.value


# --- CHANGE_FREEZE -----------------------------------------------------------

def test_change_freeze_pass_emergency_with_approver():
    ctx = {"change_freeze_active": True, "emergency": True,
           "emergency_approver": "vp-eng@x"}
    assert _status(run_checks(["CHANGE_FREEZE"], ctx),
                   "CHANGE_FREEZE") == CheckStatus.PASS.value


def test_change_freeze_blocks_normal_deploy():
    ctx = {"change_freeze_active": True}
    res = run_checks(["CHANGE_FREEZE"], ctx)
    assert _status(res, "CHANGE_FREEZE") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_change_freeze_blocks_emergency_without_approver():
    ctx = {"change_freeze_active": True, "emergency": True}
    assert _status(run_checks(["CHANGE_FREEZE"], ctx),
                   "CHANGE_FREEZE") == CheckStatus.BLOCK.value


def test_change_freeze_not_applicable_when_no_freeze():
    assert _status(run_checks(["CHANGE_FREEZE"], {}),
                   "CHANGE_FREEZE") == CheckStatus.NOT_APPLICABLE.value
    assert _status(run_checks(["CHANGE_FREEZE"], {"change_freeze_active": False}),
                   "CHANGE_FREEZE") == CheckStatus.NOT_APPLICABLE.value


# --- registry wiring ---------------------------------------------------------

def test_all_three_frameworks_are_backed():
    # None should return UNBACKED (which would be blocking): the checkers exist.
    res = run_checks(["SOC2", "ISO27001", "CHANGE_FREEZE"], {})
    assert all(r["status"] != CheckStatus.UNBACKED.value for r in res["results"])
