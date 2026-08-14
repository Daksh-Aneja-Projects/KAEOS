"""Banking / lending statutory checkers: ECOA (Reg B) adverse-action notice.
Deterministic, no LLM. This is the banking-lending vertical's load-bearing
control - the first vertical KAEOS certifies."""
from __future__ import annotations

from datetime import date

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

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
