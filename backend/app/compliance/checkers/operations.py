"""Operations / Engineering IT general controls (ITGC): deterministic checkers
for production change management, incident postmortems, and backup/retention.

No LLM, no DB, no network. Each reads the structured facts it needs from the
gate ``context`` and returns a citation-backed verdict. These are the classic
SOX 404 ITGC / COBIT controls auditors test for any system that touches the
financial-reporting boundary.
"""
from __future__ import annotations

import re

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "operations"


def _sev_number(v) -> int | None:
    """Pull the severity rank out of SEV1 / SEV-2 / P1 / 3 / 'sev 1'. Returns
    None when no rank can be read."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None


@register("CHANGE_MANAGEMENT", department=_DEPT,
          title="Change management: approver segregation + linked ticket",
          citation="SOX 404 ITGC; COBIT BAI06 (Managed Changes)")
def check_change_management(context: dict) -> CheckResult:
    """A production change requires a recorded approver who is NOT the
    implementer, and a linked change ticket. Reads ``context['change']`` =
    {is_production, implementer, approver, ticket}."""
    change = context.get("change") or context.get("production_change")
    if not change:
        return CheckResult("CHANGE_MANAGEMENT", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    is_prod = change.get("is_production", True)
    if is_prod is None:
        return CheckResult("CHANGE_MANAGEMENT", CheckStatus.ADVISORY,
                           [Finding("prod_unknown",
                                    "Cannot verify whether this change targets "
                                    "production; change-management scope is "
                                    "unresolved.", "MEDI")],
                           method="deterministic")
    if not is_prod:
        return CheckResult("CHANGE_MANAGEMENT", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    implementer = str(change.get("implementer") or change.get("implemented_by") or "").strip()
    approver = str(change.get("approver") or change.get("approved_by") or "").strip()
    ticket = str(change.get("ticket") or change.get("change_ticket")
                 or change.get("ticket_id") or "").strip()

    findings = []
    if not approver:
        findings.append(Finding("no_approver",
                                "Production change has no recorded approver; SOX "
                                "ITGC requires a distinct approving identity.", "HIGH"))
    elif not implementer:
        # An approver but no implementer identity: segregation of duties cannot
        # be verified (approver != implementer is untestable), so do not PASS.
        if not ticket:
            findings.append(Finding("no_change_ticket",
                                    "Production change has no linked change ticket; the "
                                    "change is not traceable to an authorized record.", "HIGH"))
            return CheckResult("CHANGE_MANAGEMENT", CheckStatus.BLOCK, findings,
                               method="deterministic")
        return CheckResult("CHANGE_MANAGEMENT", CheckStatus.ADVISORY,
                           [Finding("implementer_unknown",
                                    "Production change records an approver but no "
                                    "implementer identity; segregation of duties "
                                    "cannot be confirmed.", "MEDI")],
                           method="deterministic")
    elif approver.lower() == implementer.lower():
        findings.append(Finding("approver_is_implementer",
                                "Segregation of duties: the approver cannot be the "
                                "same identity as the implementer of a production "
                                "change.", "HIGH"))
    if not ticket:
        findings.append(Finding("no_change_ticket",
                                "Production change has no linked change ticket; the "
                                "change is not traceable to an authorized record.", "HIGH"))

    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("CHANGE_MANAGEMENT", status, findings, method="deterministic")


@register("INCIDENT_POSTMORTEM", department=_DEPT,
          title="Incident postmortem before closing SEV1/SEV2",
          citation="SOX 404 ITGC; COBIT DSS02/DSS03 (Managed Problems)")
def check_incident_postmortem(context: dict) -> CheckResult:
    """Closing a resolved SEV1/SEV2 incident requires a completed postmortem
    with a root cause AND at least one action item. Lower severities are
    advisory, not blocking. Reads ``context['incident']`` =
    {severity, status, postmortem: {root_cause, action_items}}."""
    incident = context.get("incident")
    if not incident:
        return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    status = str(incident.get("status") or "").strip().lower()
    if status not in ("resolved", "closed", "closing", "mitigated", "done"):
        # The control only governs closure of a resolved incident.
        return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    sev = _sev_number(incident.get("severity") or incident.get("sev"))
    if sev is None:
        return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.ADVISORY,
                           [Finding("sev_unknown",
                                    "Incident severity is not recorded; cannot "
                                    "determine whether a postmortem is required.", "MEDI")],
                           method="deterministic")

    pm = incident.get("postmortem") or {}
    root_cause = str(pm.get("root_cause") or "").strip()
    action_items = pm.get("action_items")
    # A bare string like "TBD" is not a list of action items; require a real
    # sequence so a placeholder does not count as a completed postmortem.
    has_actions = isinstance(action_items, (list, tuple)) and len(action_items) > 0
    complete = bool(root_cause) and has_actions

    if complete:
        return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.PASS, [],
                           method="deterministic")

    missing = []
    if not root_cause:
        missing.append("root cause")
    if not has_actions:
        missing.append("action items")
    detail = " and ".join(missing) or "postmortem"

    if sev <= 2:
        return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.BLOCK,
                           [Finding("postmortem_incomplete",
                                    f"SEV{sev} incident cannot be closed without a "
                                    f"completed postmortem (missing {detail}).", "HIGH")],
                           method="deterministic")
    return CheckResult("INCIDENT_POSTMORTEM", CheckStatus.ADVISORY,
                       [Finding("postmortem_recommended",
                                f"SEV{sev} incident is being closed without a "
                                f"completed postmortem (missing {detail}).", "LOW")],
                       method="deterministic")


@register("BACKUP_RETENTION", department=_DEPT,
          title="Backup / retention policy on restore & delete",
          citation="SOX 404 ITGC; COBIT DSS04/DSS01 (Backup & Continuity)")
def check_backup_retention(context: dict) -> CheckResult:
    """A destructive or restore data action must respect the retention/backup
    policy: no deletion before the retention window elapses, and no delete/
    restore without a verified backup. Reads ``context['retention']`` =
    {operation, record_age_days, retention_days, backup_verified}."""
    ret = context.get("retention") or context.get("backup")
    if not ret:
        return CheckResult("BACKUP_RETENTION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    op = str(ret.get("operation") or "").strip().lower()
    is_delete = op in ("delete", "purge", "destroy", "erase", "hard_delete")
    is_restore = op in ("restore", "recover", "rollback")
    if not (is_delete or is_restore):
        return CheckResult("BACKUP_RETENTION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    backup_verified = ret.get("backup_verified")
    findings = []

    # backup_verified must be an affirmative True. False is a real violation
    # (BLOCK); None/absent means we simply cannot confirm it (ADVISORY, never a
    # silent PASS that fails open).
    if backup_verified is not True:
        if backup_verified is False:
            code, msg = ("no_verified_backup",
                         "Restore requested but no verified backup is "
                         "available to restore from.") if is_restore else (
                         "delete_without_backup",
                         "Destructive delete with no verified backup; the "
                         "data would be unrecoverable.")
            return CheckResult("BACKUP_RETENTION", CheckStatus.BLOCK,
                               [Finding(code, msg, "HIGH")], method="deterministic")
        return CheckResult("BACKUP_RETENTION", CheckStatus.ADVISORY,
                           [Finding("backup_unconfirmed",
                                    "Cannot confirm a verified backup exists for this "
                                    f"{'restore' if is_restore else 'destructive delete'}; "
                                    "backup verification was not supplied.", "MEDI")],
                           method="deterministic")

    if is_restore:
        return CheckResult("BACKUP_RETENTION", CheckStatus.PASS, [],
                           method="deterministic")

    # Deletion path (backup is verified; check the retention window).
    age = ret.get("record_age_days")
    keep = ret.get("retention_days")
    if age is None or keep is None:
        return CheckResult("BACKUP_RETENTION", CheckStatus.ADVISORY,
                           [Finding("retention_unverifiable",
                                    "Record age or retention period is not supplied; "
                                    "cannot verify the deletion respects retention.", "MEDI")],
                           method="deterministic")

    try:
        if float(age) < float(keep):
            findings.append(Finding("premature_deletion",
                                    f"Record is {age} days old but the retention "
                                    f"policy requires {keep} days; deleting now "
                                    "violates the retention schedule.", "HIGH"))
    except (TypeError, ValueError):
        return CheckResult("BACKUP_RETENTION", CheckStatus.ADVISORY,
                           [Finding("retention_unparseable",
                                    "Retention/age values are not numeric; cannot "
                                    "verify retention compliance.", "MEDI")],
                           method="deterministic")

    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("BACKUP_RETENTION", status, findings, method="deterministic")
