"""Engineering / IT change-management checkers: SOC2 CC8.1 change management,
ISO 27001 change control (rollback + approval), and change-freeze enforcement.

Deterministic, no LLM / no DB / no network. Each reads the structured facts it
needs from the gate ``context`` and returns a citation-backed verdict.

Context shape follows what the Engineering agents actually produce. The
deploy-risk agent passes ``context['facts']`` (environment, pr_ci_passing,
pr_risk, ...) and the code-review agent passes ``context['surface']``
(ci_passing, approvals-adjacent change surface). Callers may also pass the
change-management fields at the top level or under ``context['change']``. To
stay robust to all three call shapes, the checkers read a flattened view.

Fail-closed posture, matching operations.py: an EXPLICIT bad value (CI failing,
zero approvals, rollback declared absent) is a BLOCK; a simply-absent input is
ADVISORY (never a silent PASS that fails open); a non-production / non-deploy
action is NOT_APPLICABLE. Absent risk-weakening evidence is treated as unknown -
we keep the stricter prior and refuse to PASS on it.
"""
from __future__ import annotations

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "engineering"

_PROD = {"production", "prod", "live"}
_NONPROD = {"dev", "development", "staging", "stage", "test", "testing", "qa", "sandbox"}


def _flat(context: dict) -> dict:
    """Flatten the known nested fact bags the agents produce into one view.

    Nested bags provide defaults; explicit top-level context keys win last, so a
    caller can always override a nested value.
    """
    merged: dict = {}
    for bag in ("facts", "surface", "change", "deployment", "deploy",
                "pr", "pull_request"):
        v = context.get(bag)
        if isinstance(v, dict):
            merged.update(v)
    merged.update({k: v for k, v in context.items() if not isinstance(v, dict)})
    return merged


def _tri(m: dict, *keys):
    """First present, non-None key coerced to a bool; None if none are present.

    Distinguishes 'declared false / empty' (-> False, a real violation) from
    'not supplied' (-> None, thin input) - the whole point of the fail-closed
    posture. An empty string is a declared-empty value, i.e. False.
    """
    for k in keys:
        if k in m and m[k] is not None:
            v = m[k]
            return bool(v.strip()) if isinstance(v, str) else bool(v)
    return None


def _is_production(m: dict):
    """True / False / None (unknown) for whether this change targets production."""
    ip = m.get("is_production")
    if ip is not None:
        return bool(ip)
    env = str(m.get("environment") or "").strip().lower()
    if env in _PROD:
        return True
    if env in _NONPROD:
        return False
    return None


def _reviewed(m: dict):
    """True / False / None for peer review, from ``peer_reviewed`` or ``approvals``."""
    pr = m.get("peer_reviewed")
    if pr is not None:
        return bool(pr)
    appr = m.get("approvals")
    if appr is not None:
        try:
            return int(appr) > 0
        except (TypeError, ValueError):
            return None
    return None


def _ci_passing(m: dict):
    """True / False / None, from ``ci_passing`` or the deploy agent's ``pr_ci_passing``."""
    for k in ("ci_passing", "pr_ci_passing", "tests_passing"):
        if k in m and m[k] is not None:
            return bool(m[k])
    return None


def _ticket(m: dict) -> str:
    for k in ("ticket", "change_ticket", "ticket_id", "change_record",
              "change_record_id", "jira", "issue"):
        v = m.get(k)
        if v:
            return str(v).strip()
    return ""


def _approved(m: dict):
    """True / False / None for a recorded approval (approver identity or approvals)."""
    a = _tri(m, "approved")
    if a is not None:
        return a
    ident = (m.get("approver") or m.get("approved_by")
             or m.get("emergency_approver") or m.get("approver_identity"))
    if ident:
        return True
    return _reviewed(m)


# ─────────────────────────────────────────────────────────────────────────────


@register("SOC2", department=_DEPT,
          title="SOC2 CC8.1 change management: peer review + change record + CI",
          citation="AICPA Trust Services Criteria CC8.1 (Change Management)")
def check_soc2_change_management(context: dict) -> CheckResult:
    """A production code/deploy change needs peer review, a linked change record,
    and passing CI/tests. Reads ``peer_reviewed``/``approvals``, ``ci_passing``
    (or the deploy agent's ``pr_ci_passing``), and a change ticket. BLOCK when a
    production change has failing CI or an explicit zero-review; ADVISORY when the
    evidence is simply not supplied."""
    m = _flat(context)
    prod = _is_production(m)
    if prod is False:
        return CheckResult("SOC2", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    ci = _ci_passing(m)
    reviewed = _reviewed(m)
    ticket = _ticket(m)

    problems = []
    if ci is False:
        problems.append(Finding("ci_failing",
                              "SOC2 CC8.1: change has failing CI/tests; a change may not "
                              "ship to production without passing verification.", "HIGH"))
    if reviewed is False:
        problems.append(Finding("no_peer_review",
                              "SOC2 CC8.1: change has no peer review (zero approvals); "
                              "changes require independent review.", "HIGH"))
    if problems:
        # Only a KNOWN production change hard-BLOCKs. With the target environment
        # unknown (e.g. a code-review action that carries no environment), the
        # same findings are ADVISORY: reviewing a red-CI PR is a normal action
        # and must not be blocked at the compliance gate - the deploy is where
        # the BLOCK belongs.
        status = CheckStatus.BLOCK if prod is True else CheckStatus.ADVISORY
        return CheckResult("SOC2", status, problems, method="deterministic")

    thin = []
    if prod is None:
        thin.append("target environment")
    if ci is None:
        thin.append("CI/test status")
    if reviewed is None:
        thin.append("peer-review evidence")
    if not ticket:
        thin.append("linked change record")
    if thin:
        return CheckResult("SOC2", CheckStatus.ADVISORY,
                           [Finding("change_evidence_thin",
                                    "SOC2 CC8.1 change-management evidence is incomplete "
                                    f"(missing {', '.join(thin)}); cannot fully verify.",
                                    "MEDI")],
                           method="deterministic")
    return CheckResult("SOC2", CheckStatus.PASS, [], method="deterministic")


@register("ISO27001", department=_DEPT,
          title="ISO 27001 change control: documented rollback + approval",
          citation="ISO/IEC 27001:2022 A.8.32 / A.12.1.2 (Change Management)")
def check_iso27001_change_control(context: dict) -> CheckResult:
    """A production change needs a documented rollback plan and a recorded
    approval. BLOCK on a production change whose rollback plan is declared absent,
    or whose approval is declared absent; ADVISORY when either is simply not
    supplied. Reads ``rollback_plan``/``has_rollback``/``rollback`` and
    ``approver``/``approved``/``approvals``."""
    m = _flat(context)
    prod = _is_production(m)
    if prod is False:
        return CheckResult("ISO27001", CheckStatus.NOT_APPLICABLE, [], method="deterministic")

    rollback = _tri(m, "rollback_plan", "has_rollback", "rollback", "rollback_documented")
    approved = _approved(m)

    blocks = []
    if rollback is False:
        blocks.append(Finding("no_rollback_plan",
                              "ISO 27001 A.8.32: production change has no documented "
                              "rollback plan; a change must be reversible.", "HIGH"))
    if approved is False:
        blocks.append(Finding("no_approval",
                              "ISO 27001 A.8.32: production change has no recorded "
                              "approval.", "HIGH"))
    if blocks:
        return CheckResult("ISO27001", CheckStatus.BLOCK, blocks, method="deterministic")

    thin = []
    if prod is None:
        thin.append("target environment")
    if rollback is None:
        thin.append("rollback plan")
    if approved is None:
        thin.append("change approval")
    if thin:
        return CheckResult("ISO27001", CheckStatus.ADVISORY,
                           [Finding("change_control_thin",
                                    "ISO 27001 change-control evidence is incomplete "
                                    f"(missing {', '.join(thin)}); cannot fully verify.",
                                    "MEDI")],
                           method="deterministic")
    return CheckResult("ISO27001", CheckStatus.PASS, [], method="deterministic")


@register("CHANGE_FREEZE", department=_DEPT,
          title="Change-freeze window enforcement",
          citation="SOC2 CC8.1; ITIL Change Enablement (freeze / blackout windows)")
def check_change_freeze(context: dict) -> CheckResult:
    """During an active change-freeze window (``change_freeze_active`` true), a
    deploy is denied unless it is flagged as an emergency AND names an approver.
    No active freeze -> NOT_APPLICABLE. Reads ``change_freeze_active``,
    ``emergency``/``is_emergency``, and ``emergency_approver``/``approver``."""
    m = _flat(context)
    frozen = m.get("change_freeze_active")
    if frozen is None:
        frozen = m.get("freeze_active")
    if not frozen:
        # No freeze declared, or explicitly not frozen: the control does not apply.
        return CheckResult("CHANGE_FREEZE", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    emergency = _tri(m, "emergency", "is_emergency", "emergency_change")
    approver = (m.get("emergency_approver") or m.get("approver")
                or m.get("approved_by") or m.get("approver_identity"))

    if not emergency:
        return CheckResult("CHANGE_FREEZE", CheckStatus.BLOCK,
                           [Finding("deploy_during_freeze",
                                    "A change-freeze window is active; deploys are denied "
                                    "unless flagged as an approved emergency change.", "HIGH")],
                           method="deterministic")
    if not approver:
        return CheckResult("CHANGE_FREEZE", CheckStatus.BLOCK,
                           [Finding("emergency_without_approver",
                                    "Emergency deploy during a change freeze requires a named "
                                    "approver; none was recorded.", "HIGH")],
                           method="deterministic")
    return CheckResult("CHANGE_FREEZE", CheckStatus.PASS, [], method="deterministic")
