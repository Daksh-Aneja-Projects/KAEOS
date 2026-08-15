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


# --- CHANGE_MANAGEMENT (operations.py) -- Engineering now populates context ---
#
# Regression coverage: CodeReviewAgent.review_pull_request and
# IncidentAgent.triage_incident used to build a gate context with no "change"
# key at all, so this checker returned NOT_APPLICABLE on literally every run
# (a permanent no-op) and the gated_runner's "change_record_logged" bridge was
# dead code (this checker never read that key). Both agents now populate
# context['change'] with real facts before calling run_gated_engineering_skill.

def test_change_management_not_applicable_without_change_key():
    # Baseline: this is the bug being fixed - no 'change' key at all.
    assert _status(run_checks(["CHANGE_MANAGEMENT"], {}),
                   "CHANGE_MANAGEMENT") == CheckStatus.NOT_APPLICABLE.value


def test_change_management_real_verdict_for_engineering_review_context():
    """The exact shape CodeReviewAgent/IncidentAgent now build (is_production
    explicitly None - a review/triage is advisory, not the production change
    event itself) must yield a real ADVISORY verdict, never NOT_APPLICABLE."""
    ctx = {"change": {"is_production": None, "implementer": "ravi.iyer@acme.com",
                       "ticket": "PR-482"}}
    res = run_checks(["CHANGE_MANAGEMENT"], ctx)
    status = _status(res, "CHANGE_MANAGEMENT")
    assert status != CheckStatus.NOT_APPLICABLE.value
    assert status == CheckStatus.ADVISORY.value


def test_change_management_blocks_known_production_change_without_approver():
    # A genuinely known production change (is_production=True) with an
    # implementer and ticket but no named approver correctly BLOCKs - proving
    # the checker evaluates real data, not just NOT_APPLICABLE, once it is told
    # this specific action targets production.
    ctx = {"change": {"is_production": True, "implementer": "dana.w@acme.com",
                       "ticket": "DEPLOY-v2.14.0"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.BLOCK.value


def test_change_management_passes_with_segregated_approver_and_ticket():
    ctx = {"change": {"is_production": True, "implementer": "dana.w@acme.com",
                       "approver": "ravi.iyer@acme.com", "ticket": "DEPLOY-v2.14.0"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.PASS.value


# --- Engineering agents' _change_context() builders: real facts, no fabrication

def test_code_review_change_context_is_honest_and_never_fabricates_approver():
    from app.engineering.agents.code_review_agent import _change_context
    from app.engineering.models.delivery import PRStatus, PullRequest

    pr = PullRequest(id="pr1", tenant_id="t1", number=482, title="x", status=PRStatus.IN_REVIEW)
    ctx = _change_context(pr, "ravi.iyer@acme.com")

    assert ctx["is_production"] is None      # honest: review isn't the production event
    assert ctx["implementer"] == "ravi.iyer@acme.com"
    assert ctx["ticket"] == "PR-482"
    assert "approver" not in ctx              # KAEOS tracks no named-approver identity


def test_code_review_change_context_without_known_author():
    from app.engineering.agents.code_review_agent import _change_context
    from app.engineering.models.delivery import PRStatus, PullRequest

    pr = PullRequest(id="pr1", tenant_id="t1", number=97, title="x", status=PRStatus.APPROVED)
    ctx = _change_context(pr, None)
    assert ctx["implementer"] is None
    assert ctx["ticket"] == "PR-97"


def test_incident_change_context_uses_real_deploy_fields():
    from app.engineering.agents.incident_agent import _change_context
    from app.engineering.models.delivery import Deployment
    from app.engineering.models.incidents import Incident

    incident = Incident(id="i1", tenant_id="t1", incident_number="INC-2026-0042", title="x")
    deploy = Deployment(id="d1", tenant_id="t1", version="v2.14.0", deployed_by="dana.w@acme.com")
    ctx = _change_context(incident, deploy)

    assert ctx["is_production"] is None
    assert ctx["implementer"] == "dana.w@acme.com"
    assert ctx["ticket"] == "INC-2026-0042"


def test_incident_change_context_without_correlated_deploy():
    from app.engineering.agents.incident_agent import _change_context
    from app.engineering.models.incidents import Incident

    incident = Incident(id="i1", tenant_id="t1", incident_number="INC-2026-0041", title="x")
    ctx = _change_context(incident, None)
    assert ctx["implementer"] is None
    assert ctx["ticket"] == "INC-2026-0041"


def test_engineering_change_context_wiring_gives_real_verdict_end_to_end():
    """Wiring proof: run the ACTUAL agent-built context through the ACTUAL
    checker and confirm it is no longer the NOT_APPLICABLE no-op."""
    from app.engineering.agents.code_review_agent import _change_context
    from app.engineering.models.delivery import PRStatus, PullRequest

    pr = PullRequest(id="pr1", tenant_id="t1", number=482, title="x", status=PRStatus.IN_REVIEW)
    res = run_checks(["CHANGE_MANAGEMENT"], {"change": _change_context(pr, "ravi.iyer@acme.com")})
    status = _status(res, "CHANGE_MANAGEMENT")
    assert status == CheckStatus.ADVISORY.value
    assert status != CheckStatus.NOT_APPLICABLE.value


def test_gated_runner_has_no_dead_change_record_logged_bridge():
    """The old `ctx["change_record_logged"] = True` bridge line is gone -
    no checker ever read that key, so it was dead code. Assert it no longer
    leaks into the context gated_engineering skills build."""
    import inspect

    from app.engineering.agents import gated_runner
    src = inspect.getsource(gated_runner)
    assert "change_record_logged" not in src
