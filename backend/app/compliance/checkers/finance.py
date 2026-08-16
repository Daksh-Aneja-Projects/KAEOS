"""Finance department statutory checkers: SOX controls (segregation of duties +
human approval for financial actions). Deterministic, no LLM."""
from __future__ import annotations

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "finance"

# Approver/maker identities that are NOT attributable to a real, distinct human.
# The email/Slack one-click approval link mints a constant "email-approver" and
# the runtime falls back to "human-approver" when no principal resolves; both
# LOOK like an approver but can never be proven != the maker, so four-eyes on a
# financial write approved only by one of these is UNVERIFIABLE, not satisfied.
_NON_ATTRIBUTABLE = {"", "none", "null", "system", "email-approver", "human-approver"}


def _attributable(identity) -> bool:
    """True only for a concrete, human-attributable identity."""
    return identity is not None and str(identity).strip().lower() not in _NON_ATTRIBUTABLE


@register("SOX", department=_DEPT,
          title="SOX segregation of duties + human approval",
          citation="Sarbanes-Oxley Act 302/404; COSO control activities")
def check_sox(context: dict) -> CheckResult:
    """A financial action needs a human approver, and that approver must be a
    DIFFERENT identity than the maker (four-eyes / segregation of duties).

    Fail-closed: once an action carries a human approval, four-eyes is satisfied
    only if BOTH a maker and an approver resolve to concrete identities that
    differ. If either cannot be resolved, four-eyes is UNVERIFIABLE and the action
    is BLOCKED rather than passed on the mere presence of an approval - a bare
    ``has_human_approver=True`` with no attributable maker/approver was the hole
    this closes. Reads ``has_human_approver`` (the approver's identity string, or
    a bool) plus the ``maker``/``created_by`` and ``approver``/``approved_by``
    identities the financial call sites populate."""
    findings = []
    financial = context.get("is_financial", True)
    approved = context.get("has_human_approver")
    if financial and not approved:
        findings.append(Finding("no_human_approver",
                                "SOX requires explicit human approval for this "
                                "financial action.", "HIGH"))
    elif financial and approved:
        maker = context.get("maker") or context.get("created_by")
        # The approver identity may ride on has_human_approver itself (the call
        # sites set it to the approver's identity string) or on an explicit key.
        approver = (context.get("approver") or context.get("approved_by")
                    or (approved if isinstance(approved, str) else None))
        if not _attributable(maker) or not _attributable(approver):
            findings.append(Finding("segregation_of_duties_unverifiable",
                                    "Four-eyes cannot be verified: this financial "
                                    "action was approved but a distinct, attributable "
                                    "maker and approver were not both recorded (a "
                                    "constant email/system approver does not satisfy "
                                    "segregation of duties).",
                                    "HIGH"))
        elif str(maker) == str(approver):
            findings.append(Finding("segregation_of_duties",
                                    "Segregation of duties: the maker cannot also "
                                    "be the approver (four-eyes).", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("SOX", status, findings, method="deterministic")


if __name__ == "__main__":  # pragma: no cover - runnable self-check for the SoD logic
    def _st(ctx):
        return check_sox(ctx).status

    # Financial action with no approver -> blocked.
    assert _st({"is_financial": True, "has_human_approver": False}) is CheckStatus.BLOCK
    # Approved but four-eyes unverifiable (missing maker and/or approver) -> blocked.
    assert _st({"has_human_approver": True}) is CheckStatus.BLOCK
    assert _st({"has_human_approver": "cfo@x"}) is CheckStatus.BLOCK            # approver only
    assert _st({"has_human_approver": True, "maker": "a@x"}) is CheckStatus.BLOCK  # maker only
    # Maker == approver -> four-eyes violation.
    assert _st({"has_human_approver": True, "maker": "a@x", "approver": "a@x"}) is CheckStatus.BLOCK
    assert _st({"has_human_approver": "a@x", "maker": "a@x"}) is CheckStatus.BLOCK
    # A constant/non-attributable approver (email-link default, runtime fallback)
    # cannot satisfy four-eyes even though it "differs" from the maker -> blocked.
    assert _st({"has_human_approver": "email-approver", "maker": "a@x"}) is CheckStatus.BLOCK
    assert _st({"has_human_approver": True, "maker": "a@x", "approver": "human-approver"}) is CheckStatus.BLOCK
    # Distinct maker and approver -> passes.
    assert _st({"has_human_approver": True, "maker": "a@x", "approver": "b@x"}) is CheckStatus.PASS
    assert _st({"has_human_approver": "b@x", "maker": "a@x"}) is CheckStatus.PASS
    # Non-financial action is out of four-eyes scope.
    assert _st({"is_financial": False, "has_human_approver": False}) is CheckStatus.PASS
    print("check_sox four-eyes self-check passed")
