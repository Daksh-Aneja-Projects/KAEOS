"""Banking / lending statutory checkers: ECOA (Reg B) adverse-action notice,
FAIR_LENDING (disparate impact), TILA (Reg Z disclosures), FDCPA (collections).
Deterministic, no LLM. This is the banking-lending vertical's load-bearing
control - the first vertical KAEOS certifies."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register
from app.services.disparate_impact import FOUR_FIFTHS, four_fifths_test

_DEPT = "lending"

# Generic non-reasons that fail Reg B's "specific principal reasons" bar.
_GENERIC_REASONS = {
    "", "internal policy", "did not meet criteria", "not qualified",
    "credit score", "score too low", "failed", "declined", "other",
    "does not meet requirements", "risk", "policy",
}
_MAX_NOTICE_DAYS = 30  # 12 CFR 1002.9(a)(1)


@register("ECOA", department=_DEPT,
          title="ECOA/Reg B adverse-action notice",
          citation="Equal Credit Opportunity Act 15 U.S.C. 1691; 12 CFR 1002.9")
def check_ecoa_adverse_action(context: dict) -> CheckResult:
    """On a credit DENIAL, Reg B requires a notice that states SPECIFIC
    principal reasons, is sent within 30 days, and uses no prohibited basis.
    Needs ``context['decision']`` and ``context['adverse_action']`` =
    {reasons: [...], notice_days: int, prohibited_basis_used: bool}."""
    decision = str(context.get("decision") or context.get("outcome") or "").upper()
    if decision not in ("DENY", "DENIED", "DECLINE", "DECLINED", "ADVERSE"):
        return CheckResult("ECOA", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    aa = context.get("adverse_action") or {}
    findings = []

    reasons = [str(r).strip() for r in (aa.get("reasons") or aa.get("specific_reasons") or [])]
    specific = [r for r in reasons if r.lower() not in _GENERIC_REASONS and len(r) >= 8]
    if not specific:
        findings.append(Finding("no_specific_reasons",
                                "Adverse-action notice must state the specific "
                                "principal reasons for denial; generic or missing "
                                "reasons violate Reg B.", "HIGH"))

    if aa.get("prohibited_basis_used"):
        findings.append(Finding("prohibited_basis",
                                "Denial reason references a prohibited basis "
                                "(race, sex, age, national origin, etc.).", "CRIT"))

    notice_days = aa.get("notice_days")
    if notice_days is None and aa.get("notice_date") and (context.get("decision_date")):
        try:
            notice_days = (date.fromisoformat(str(aa["notice_date"]))
                           - date.fromisoformat(str(context["decision_date"]))).days
        except (ValueError, TypeError):
            notice_days = None
    if notice_days is not None and notice_days > _MAX_NOTICE_DAYS:
        findings.append(Finding("notice_late",
                                f"Adverse-action notice sent {notice_days} days after "
                                f"the decision; Reg B requires within {_MAX_NOTICE_DAYS}.", "HIGH"))

    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("ECOA", status, findings, method="deterministic")


# -- FAIR_LENDING: disparate-impact on approval rates -------------------------
_DENIAL = ("DENY", "DENIED", "DECLINE", "DECLINED", "ADVERSE")


@register("FAIR_LENDING", department=_DEPT,
          title="Fair-lending disparate-impact (four-fifths rule)",
          citation="ECOA/Reg B; Fair Housing Act; four-fifths 29 CFR 1607.4(D)")
def check_fair_lending(context: dict) -> CheckResult:
    """Portfolio-level fair-lending monitoring. Runs the four-fifths rule over
    approval rates by protected class and BLOCKS on a statistically-supported
    adverse-impact ratio (< 0.8) UNLESS a documented business-necessity
    justification is present.

    Reads ``context['approval_cohorts']`` (or ``cohort_outcomes``) shaped as the
    four-fifths input: ``{attr: {group: {selected, total}}}`` where ``selected``
    is approvals. ``context['business_necessity']`` (truthy string/dict) documents
    the justification that downgrades a flag to ADVISORY."""
    cohorts = context.get("approval_cohorts") or context.get("cohort_outcomes")
    if not cohorts:
        # No cohort data supplied - cannot verify. Never a silent PASS.
        return CheckResult("FAIR_LENDING", CheckStatus.ADVISORY,
                           [Finding("no_cohort_data",
                                    "No approval-rate cohort data supplied; "
                                    "fair-lending disparate impact could not be "
                                    "verified.", "MEDI")], method="deterministic")

    outcome = four_fifths_test(cohorts)
    if outcome["passed"]:
        return CheckResult("FAIR_LENDING", CheckStatus.PASS, [],
                           method="four_fifths_selection_rate", detail=outcome)

    # Adverse impact found. A documented, specific business-necessity defense
    # downgrades to ADVISORY (must still be reviewed); its absence BLOCKS.
    justification = (context.get("business_necessity")
                     or context.get("business_necessity_justification"))
    documented = bool(justification) and (
        not isinstance(justification, str) or len(justification.strip()) >= 20)
    flagged = ", ".join(outcome["flagged"])
    if documented:
        return CheckResult("FAIR_LENDING", CheckStatus.ADVISORY,
                           [Finding("adverse_impact_justified",
                                    f"Adverse impact on {flagged} (below four-fifths, "
                                    f"threshold {FOUR_FIFTHS}); a business-necessity "
                                    "justification is on file and must be reviewed.",
                                    "HIGH")],
                           method="four_fifths_selection_rate", detail=outcome)
    return CheckResult("FAIR_LENDING", CheckStatus.BLOCK,
                       [Finding("adverse_impact",
                                f"Approval rates show adverse impact on {flagged} "
                                "(below four-fifths of the most-favored group) with "
                                "no documented business necessity.", "CRIT")],
                       method="four_fifths_selection_rate", detail=outcome)


# -- TILA / Reg Z: consumer-credit disclosures --------------------------------
# APR tolerance for a regular (non-irregular) closed-end transaction: 1/8 of 1
# percentage point. 12 CFR 1026.22(a)(2).
_APR_TOLERANCE = Decimal("0.125")
_REQUIRED_DISCLOSURES = ("apr", "finance_charge", "amount_financed", "total_of_payments")


def _dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


@register("TILA", department=_DEPT,
          title="TILA/Reg Z APR + finance-charge disclosure",
          citation="Truth in Lending Act 15 USC 1601; Reg Z 12 CFR 1026")
def check_tila(context: dict) -> CheckResult:
    """A consumer credit decision must carry the Reg Z material disclosures (APR,
    finance charge, amount financed, total of payments) and the disclosed APR
    must be within tolerance of the actual APR.

    NOT_APPLICABLE for a non-consumer (business-purpose) transaction. Reads
    ``context['credit_purpose']`` ('consumer' default) and ``context['tila']`` =
    ``{apr, finance_charge, amount_financed, total_of_payments, actual_apr}``.
    Only a credit EXTENSION (approval) triggers disclosure duties; a denial goes
    through ECOA instead."""
    purpose = str(context.get("credit_purpose") or "consumer").lower()
    if purpose not in ("consumer", "personal", "household", "family"):
        return CheckResult("TILA", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    decision = str(context.get("decision") or context.get("outcome") or "APPROVE").upper()
    if decision in _DENIAL:
        # No credit extended - no Reg Z disclosure obligation on a denial.
        return CheckResult("TILA", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    tila = context.get("tila") or {}
    findings = []

    missing = [d for d in _REQUIRED_DISCLOSURES if tila.get(d) in (None, "")]
    if missing:
        findings.append(Finding("missing_disclosures",
                                "Consumer credit extension lacks required Reg Z "
                                f"disclosures: {', '.join(missing)}.", "HIGH"))

    disclosed_apr = _dec(tila.get("apr"))
    actual_apr = _dec(tila.get("actual_apr"))
    if disclosed_apr is not None and actual_apr is not None:
        if abs(disclosed_apr - actual_apr) > _APR_TOLERANCE:
            findings.append(Finding("apr_out_of_tolerance",
                                    f"Disclosed APR {disclosed_apr}% differs from actual "
                                    f"{actual_apr}% by more than the {_APR_TOLERANCE}-point "
                                    "Reg Z tolerance.", "HIGH"))

    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("TILA", status, findings, method="deterministic")


# -- FDCPA: debt-collection communications ------------------------------------
# 15 USC 1692c(a)(1): no contact before 8am or after 9pm the consumer's local
# time. 1692g: validation notice within 5 days of the initial communication.
_FDCPA_EARLIEST_HOUR = 8
_FDCPA_LATEST_HOUR = 21  # 9pm
_VALIDATION_DAYS = 5
_REG_F_CALL_CAP = 7  # 12 CFR 1006.14(b): >7 phone calls in 7 consecutive days


@register("FDCPA", department=_DEPT,
          title="FDCPA collection-communication limits",
          citation="Fair Debt Collection Practices Act 15 USC 1692")
def check_fdcpa(context: dict) -> CheckResult:
    """A debt-collection communication must respect the 8am-9pm local-time window,
    send the validation notice within 5 days of first contact, and use no
    harassing/abusive practice.

    NOT_APPLICABLE when the action is not a collection communication. Reads
    ``context['collection']`` = ``{communications: [{hour_local}], harassment: bool,
    validation_notice_sent: bool, days_since_initial: int,
    phone_contacts_last_7d: int}``."""
    coll = context.get("collection")
    if not coll:
        return CheckResult("FDCPA", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    findings = []

    # 12 CFR 1006.14(b)(2)(i) (Reg F): a debt collector is presumed to violate the
    # FDCPA by placing MORE THAN 7 telephone calls to a consumer within 7
    # consecutive days. If 7 calls have already landed in the trailing 7 days,
    # THIS contact is the 8th - block it (fail-closed).
    recent_calls = coll.get("phone_contacts_last_7d")
    if recent_calls is not None:
        try:
            if int(recent_calls) >= _REG_F_CALL_CAP:
                findings.append(Finding("call_cap_7in7",
                                        f"{recent_calls} phone contacts already occurred "
                                        "in the trailing 7 days; a further call exceeds "
                                        "the Reg F 7-in-7 cap (12 CFR 1006.14(b)).", "HIGH"))
        except (TypeError, ValueError):
            pass
    for comm in coll.get("communications") or []:
        hour = comm.get("hour_local")
        if hour is None:
            continue
        try:
            hour = int(hour)
        except (TypeError, ValueError):
            continue
        if hour < _FDCPA_EARLIEST_HOUR or hour >= _FDCPA_LATEST_HOUR:
            findings.append(Finding("inconvenient_time",
                                    f"Collection contact at {hour:02d}:00 local time is "
                                    "outside the permitted 8am-9pm window "
                                    "(15 USC 1692c(a)(1)).", "HIGH"))

    if coll.get("harassment"):
        findings.append(Finding("harassment",
                                "Collection communication used a harassing or abusive "
                                "practice prohibited by 15 USC 1692d.", "CRIT"))

    days = coll.get("days_since_initial")
    if coll.get("validation_notice_sent") is False and days is not None:
        try:
            if int(days) > _VALIDATION_DAYS:
                findings.append(Finding("no_validation_notice",
                                        "Debt validation notice not sent within 5 days of "
                                        "the initial communication (15 USC 1692g).", "HIGH"))
        except (TypeError, ValueError):
            pass

    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("FDCPA", status, findings, method="deterministic")


# -- LENDING_SOD: segregation of duties on a credit decision ------------------
# Identities NOT attributable to a real, distinct human (mirrors finance.py): a
# constant email-link approver or a runtime fallback cannot satisfy four-eyes.
_NON_ATTRIBUTABLE = {"", "none", "null", "system", "email-approver", "human-approver"}


def _attributable(identity) -> bool:
    return identity is not None and str(identity).strip().lower() not in _NON_ATTRIBUTABLE


@register("LENDING_SOD", department=_DEPT,
          title="Lending segregation of duties (policy maker != underwriter)",
          citation="OCC Comptroller's Handbook (Credit); SOX 404; four-eyes")
def check_lending_sod(context: dict) -> CheckResult:
    """Segregation of duties on a credit decision: the identity that last set or
    RELAXED the governing credit policy cannot also approve the underwrite that
    the policy authorizes (a single admin relaxing /credit-policies then
    self-approving the underwrite was the hole this closes).

    Reads ``context['lending_sod']`` = {policy_maker, underwriter}.
    NOT_APPLICABLE when no policy maker is on record (the built-in default policy,
    or the maker identity is not captured yet) - there is nothing to segregate.
    Fail-closed: when a maker IS recorded but the approver is not attributable,
    four-eyes is unverifiable and BLOCKS."""
    sod = context.get("lending_sod")
    if not sod:
        return CheckResult("LENDING_SOD", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    maker = sod.get("policy_maker")
    approver = sod.get("underwriter") or sod.get("approver")
    if not _attributable(maker):
        # No attributable policy override to segregate against.
        return CheckResult("LENDING_SOD", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    if not _attributable(approver):
        return CheckResult("LENDING_SOD", CheckStatus.BLOCK,
                           [Finding("sod_unverifiable",
                                    "Segregation of duties cannot be verified: the credit "
                                    "policy was set by an attributable maker but the "
                                    "underwriter identity is not attributable.", "HIGH")],
                           method="deterministic")
    if str(maker).strip().lower() == str(approver).strip().lower():
        return CheckResult("LENDING_SOD", CheckStatus.BLOCK,
                           [Finding("policy_maker_is_underwriter",
                                    "Segregation of duties: the identity that set or "
                                    "relaxed the credit policy cannot also approve the "
                                    "underwriting decision it governs (four-eyes).", "HIGH")],
                           method="deterministic")
    return CheckResult("LENDING_SOD", CheckStatus.PASS, [], method="deterministic")


if __name__ == "__main__":  # pragma: no cover - runnable self-check for the branches
    # Reg F 7-in-7: 7 prior phone contacts in the trailing week blocks the 8th.
    assert check_fdcpa({"collection": {"phone_contacts_last_7d": 7}}).status is CheckStatus.BLOCK
    assert check_fdcpa({"collection": {"phone_contacts_last_7d": 6}}).status is CheckStatus.PASS
    # Lending SoD: the policy maker cannot also be the underwriter.
    assert check_lending_sod({"lending_sod": {
        "policy_maker": "admin@bank", "underwriter": "admin@bank"}}).status is CheckStatus.BLOCK
    assert check_lending_sod({"lending_sod": {
        "policy_maker": "admin@bank", "underwriter": "uw@bank"}}).status is CheckStatus.PASS
    # No recorded policy maker -> nothing to segregate (default policy).
    assert check_lending_sod({"lending_sod": {
        "underwriter": "uw@bank"}}).status is CheckStatus.NOT_APPLICABLE
    print("lending checkers self-check passed")
