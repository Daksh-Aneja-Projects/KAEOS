"""HR department statutory checkers: EEOC adverse impact, FLSA overtime, I-9.

Deterministic, no LLM. Each reads the structured facts it needs from the gate
``context`` and returns a citation-backed verdict.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register
from app.services.disparate_impact import four_fifths_test

_DEPT = "hr"
_CENT = Decimal("0.01")


@register("EEOC", department=_DEPT, title="EEOC four-fifths adverse impact",
          citation="EEOC Uniform Guidelines 29 CFR 1607.4(D)")
def check_eeoc(context: dict) -> CheckResult:
    """Adverse-impact test on real cohort selection rates (four-fifths rule +
    two-proportion significance). Needs ``context['cohort_outcomes']`` shaped
    {attr: {group: {selected, total}}}."""
    cohorts = context.get("cohort_outcomes") or context.get("cohorts")
    if not cohorts:
        return CheckResult("EEOC", CheckStatus.ADVISORY,
                           [Finding("no_cohort_data",
                                    "No cohort outcome counts supplied; adverse "
                                    "impact cannot be measured.", "MEDI")],
                           method="deterministic")
    res = four_fifths_test(cohorts)
    if res["passed"]:
        status = CheckStatus.PASS
        findings = []
    else:
        status = CheckStatus.BLOCK
        findings = [Finding("adverse_impact",
                            f"Adverse impact on {', '.join(res['flagged'])} "
                            "(selection rate below 80% of the most-favored group, "
                            "statistically significant).", "HIGH")]
    return CheckResult("EEOC", status, findings, method="four_fifths_selection_rate",
                       detail=res)


@register("FLSA", department=_DEPT, title="FLSA overtime (time-and-a-half over 40h)",
          citation="Fair Labor Standards Act, 29 U.S.C. 207(a)")
def check_flsa_overtime(context: dict) -> CheckResult:
    """Non-exempt employees must be paid >= 1.5x their regular rate for hours
    over 40 in a workweek. Needs ``context['timecards']`` = list of
    {employee_id, exempt?, hours, hourly_rate, overtime_paid?}."""
    cards = context.get("timecards")
    if not cards:
        return CheckResult("FLSA", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    findings = []
    for c in cards:
        if c.get("exempt"):
            continue
        try:
            hours = Decimal(str(c.get("hours") or 0))
            rate = Decimal(str(c.get("hourly_rate") or 0))
            paid_ot = Decimal(str(c.get("overtime_paid") or 0)).quantize(_CENT)
        except Exception:
            findings.append(Finding("bad_timecard",
                                    f"Unparseable timecard for {c.get('employee_id')}", "MEDI"))
            continue
        ot_hours = max(Decimal("0"), hours - 40)
        owed = (ot_hours * rate * Decimal("1.5")).quantize(_CENT)
        if owed > 0 and paid_ot + _CENT < owed:
            findings.append(Finding(
                "overtime_underpaid",
                f"Employee {c.get('employee_id')}: {ot_hours}h overtime owed "
                f"${owed} at 1.5x but only ${paid_ot} recorded.", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("FLSA", status, findings, method="deterministic")


@register("I9", department=_DEPT, title="I-9 employment eligibility timeliness",
          citation="8 U.S.C. 1324a; 8 CFR 274a.2")
def check_i9(context: dict) -> CheckResult:
    """Section 1 by first day of work; Section 2 within 3 business days of hire.
    Needs ``context['i9']`` = {hire_date, section1_date, section2_date}."""
    i9 = context.get("i9")
    if not i9:
        return CheckResult("I9", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    def _d(v):
        if isinstance(v, date):
            return v
        return date.fromisoformat(v) if v else None

    try:
        hire = _d(i9.get("hire_date"))
        s1 = _d(i9.get("section1_date"))
        s2 = _d(i9.get("section2_date"))
    except (ValueError, TypeError):
        return CheckResult("I9", CheckStatus.ADVISORY,
                           [Finding("bad_dates", "I-9 dates unparseable.", "MEDI")],
                           method="deterministic")
    findings = []
    if hire is None:
        return CheckResult("I9", CheckStatus.ADVISORY,
                           [Finding("no_hire_date", "No hire date on the I-9 record.", "MEDI")],
                           method="deterministic")
    if s1 is None or s1 > hire:
        findings.append(Finding("section1_late",
                                "I-9 Section 1 must be complete by the first day of work.", "HIGH"))
    # 3 business days (skip Sat/Sun) after hire.
    bd, cur = 0, hire
    from datetime import timedelta
    while bd < 3:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            bd += 1
    if s2 is None or s2 > cur:
        findings.append(Finding("section2_late",
                                f"I-9 Section 2 must be complete within 3 business days "
                                f"of hire (by {cur.isoformat()}).", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("I9", status, findings, method="deterministic")
