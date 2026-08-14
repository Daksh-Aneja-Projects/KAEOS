"""Lending statutory checkers: ECOA, FAIR_LENDING, TILA, FDCPA - deterministic,
fail-closed. Pure functions, no LLM, no DB."""
from app.compliance import CheckStatus, run_checks
from app.compliance.registry import list_frameworks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def test_lending_frameworks_registered():
    tags = {f["framework"] for f in list_frameworks() if f["department"] == "lending"}
    assert {"ECOA", "FAIR_LENDING", "TILA", "FDCPA"} <= tags


def test_fair_lending_blocks_on_adverse_impact():
    adverse = {"approval_cohorts": {"race": {
        "white": {"selected": 80, "total": 100},
        "black": {"selected": 30, "total": 100}}}}
    assert _status(run_checks(["FAIR_LENDING"], adverse), "FAIR_LENDING") == CheckStatus.BLOCK.value

    # Same disparity but with a documented business-necessity defense -> advisory.
    justified = dict(adverse, business_necessity=(
        "Validated credit-risk model; ratios reflect verified repayment-capacity "
        "differences, documented in the fair-lending program."))
    assert _status(run_checks(["FAIR_LENDING"], justified), "FAIR_LENDING") == CheckStatus.ADVISORY.value


def test_fair_lending_passes_when_balanced():
    fair = {"approval_cohorts": {"race": {
        "white": {"selected": 48, "total": 100},
        "black": {"selected": 50, "total": 100}}}}
    assert _status(run_checks(["FAIR_LENDING"], fair), "FAIR_LENDING") == CheckStatus.PASS.value


def test_fair_lending_advisory_without_data():
    # No cohort data supplied -> ADVISORY, never a silent PASS.
    assert _status(run_checks(["FAIR_LENDING"], {}), "FAIR_LENDING") == CheckStatus.ADVISORY.value


def test_tila_blocks_missing_disclosures():
    bad = {"credit_purpose": "consumer", "decision": "APPROVE",
           "tila": {"apr": "12.5"}}  # missing finance_charge, etc.
    assert _status(run_checks(["TILA"], bad), "TILA") == CheckStatus.BLOCK.value


def test_tila_blocks_apr_out_of_tolerance():
    bad = {"credit_purpose": "consumer", "decision": "APPROVE", "tila": {
        "apr": "12.5", "actual_apr": "13.9", "finance_charge": "2000",
        "amount_financed": "18000", "total_of_payments": "20000"}}
    assert _status(run_checks(["TILA"], bad), "TILA") == CheckStatus.BLOCK.value


def test_tila_passes_with_full_disclosures():
    good = {"credit_purpose": "consumer", "decision": "APPROVE", "tila": {
        "apr": "12.5", "actual_apr": "12.55", "finance_charge": "2000",
        "amount_financed": "18000", "total_of_payments": "20000"}}
    assert _status(run_checks(["TILA"], good), "TILA") == CheckStatus.PASS.value


def test_tila_not_applicable_for_business_credit():
    biz = {"credit_purpose": "business", "decision": "APPROVE", "tila": {}}
    assert _status(run_checks(["TILA"], biz), "TILA") == CheckStatus.NOT_APPLICABLE.value


def test_fdcpa_blocks_out_of_hours_contact():
    bad = {"collection": {"communications": [{"hour_local": 6}]}}
    assert _status(run_checks(["FDCPA"], bad), "FDCPA") == CheckStatus.BLOCK.value
    late = {"collection": {"communications": [{"hour_local": 22}]}}
    assert _status(run_checks(["FDCPA"], late), "FDCPA") == CheckStatus.BLOCK.value


def test_fdcpa_blocks_missing_validation_notice():
    bad = {"collection": {"validation_notice_sent": False, "days_since_initial": 10}}
    assert _status(run_checks(["FDCPA"], bad), "FDCPA") == CheckStatus.BLOCK.value


def test_fdcpa_passes_within_hours_and_notice():
    ok = {"collection": {"communications": [{"hour_local": 10}, {"hour_local": 18}],
                         "validation_notice_sent": True, "days_since_initial": 2,
                         "harassment": False}}
    assert _status(run_checks(["FDCPA"], ok), "FDCPA") == CheckStatus.PASS.value


def test_fdcpa_not_applicable_without_collection():
    assert _status(run_checks(["FDCPA"], {}), "FDCPA") == CheckStatus.NOT_APPLICABLE.value
