"""Finance department statutory checkers: SOX controls (segregation of duties +
human approval for financial actions). Deterministic, no LLM."""
from __future__ import annotations

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "finance"


@register("SOX", department=_DEPT,
          title="SOX segregation of duties + human approval",
          citation="Sarbanes-Oxley Act 302/404; COSO control activities")
def check_sox(context: dict) -> CheckResult:
    """A financial action needs a human approver, and the maker may not be the
    approver (four-eyes). Reads ``has_human_approver`` (bool), and optionally
    ``maker``/``approver`` identities."""
    findings = []
    financial = context.get("is_financial", True)
    if financial and not context.get("has_human_approver"):
        findings.append(Finding("no_human_approver",
                                "SOX requires explicit human approval for this "
                                "financial action.", "HIGH"))
    maker = context.get("maker") or context.get("created_by")
    approver = context.get("approver") or context.get("approved_by")
    if maker and approver and str(maker) == str(approver):
        findings.append(Finding("segregation_of_duties",
                                "Segregation of duties: the maker cannot also be "
                                "the approver (four-eyes).", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("SOX", status, findings, method="deterministic")
