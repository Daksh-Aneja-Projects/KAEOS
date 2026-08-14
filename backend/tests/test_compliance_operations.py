"""Operations / Engineering ITGC checkers: deterministic, fail-closed.
Covers PASS, BLOCK, and the NOT_APPLICABLE/ADVISORY branch for each of
CHANGE_MANAGEMENT, INCIDENT_POSTMORTEM, and BACKUP_RETENTION."""
from app.compliance import CheckStatus, run_checks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


# --- CHANGE_MANAGEMENT -------------------------------------------------------

def test_change_management_pass():
    ctx = {"change": {"is_production": True, "implementer": "dev@x",
                      "approver": "lead@x", "ticket": "CHG-123"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.PASS.value


def test_change_management_blocks_self_approval():
    # Same identity implements and approves -> segregation violation.
    ctx = {"change": {"is_production": True, "implementer": "dev@x",
                      "approver": "dev@x", "ticket": "CHG-9"}}
    res = run_checks(["CHANGE_MANAGEMENT"], ctx)
    assert _status(res, "CHANGE_MANAGEMENT") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_change_management_blocks_missing_ticket_and_approver():
    ctx = {"change": {"is_production": True, "implementer": "dev@x"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.BLOCK.value


def test_change_management_not_applicable_for_non_prod():
    ctx = {"change": {"is_production": False, "implementer": "dev@x"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.NOT_APPLICABLE.value
    # No change record at all is also out of scope.
    assert _status(run_checks(["CHANGE_MANAGEMENT"], {}),
                   "CHANGE_MANAGEMENT") == CheckStatus.NOT_APPLICABLE.value


def test_change_management_advisory_when_implementer_absent():
    # Approver + ticket present but no implementer identity: SoD cannot be
    # verified, so it must not silently PASS.
    ctx = {"change": {"is_production": True, "approver": "lead@x",
                      "ticket": "CHG-77"}}
    assert _status(run_checks(["CHANGE_MANAGEMENT"], ctx),
                   "CHANGE_MANAGEMENT") == CheckStatus.ADVISORY.value


# --- INCIDENT_POSTMORTEM -----------------------------------------------------

def test_incident_postmortem_pass():
    ctx = {"incident": {"severity": "SEV1", "status": "resolved",
                        "postmortem": {"root_cause": "DB connection pool exhausted",
                                       "action_items": ["raise pool ceiling"]}}}
    assert _status(run_checks(["INCIDENT_POSTMORTEM"], ctx),
                   "INCIDENT_POSTMORTEM") == CheckStatus.PASS.value


def test_incident_postmortem_blocks_sev1_without_postmortem():
    ctx = {"incident": {"severity": "SEV2", "status": "closing", "postmortem": {}}}
    res = run_checks(["INCIDENT_POSTMORTEM"], ctx)
    assert _status(res, "INCIDENT_POSTMORTEM") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_incident_postmortem_advisory_for_low_sev():
    # SEV3 closed without a postmortem is advisory, not blocking.
    ctx = {"incident": {"severity": "SEV3", "status": "resolved"}}
    assert _status(run_checks(["INCIDENT_POSTMORTEM"], ctx),
                   "INCIDENT_POSTMORTEM") == CheckStatus.ADVISORY.value


def test_incident_postmortem_blocks_string_action_items():
    # A placeholder string ("TBD") is not a list of action items; must not PASS.
    ctx = {"incident": {"severity": "SEV1", "status": "resolved",
                        "postmortem": {"root_cause": "bad deploy",
                                       "action_items": "TBD"}}}
    assert _status(run_checks(["INCIDENT_POSTMORTEM"], ctx),
                   "INCIDENT_POSTMORTEM") == CheckStatus.BLOCK.value


def test_incident_postmortem_not_applicable_when_open():
    ctx = {"incident": {"severity": "SEV1", "status": "investigating"}}
    assert _status(run_checks(["INCIDENT_POSTMORTEM"], ctx),
                   "INCIDENT_POSTMORTEM") == CheckStatus.NOT_APPLICABLE.value


# --- BACKUP_RETENTION --------------------------------------------------------

def test_backup_retention_pass():
    ctx = {"retention": {"operation": "delete", "record_age_days": 400,
                         "retention_days": 365, "backup_verified": True}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.PASS.value


def test_backup_retention_blocks_premature_deletion():
    ctx = {"retention": {"operation": "purge", "record_age_days": 100,
                         "retention_days": 365, "backup_verified": True}}
    res = run_checks(["BACKUP_RETENTION"], ctx)
    assert _status(res, "BACKUP_RETENTION") == CheckStatus.BLOCK.value
    assert res["verified"] is False


def test_backup_retention_blocks_delete_without_backup():
    ctx = {"retention": {"operation": "delete", "record_age_days": 400,
                         "retention_days": 365, "backup_verified": False}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.BLOCK.value


def test_backup_retention_advisory_when_unverifiable():
    # Delete with a good backup but no retention facts -> cannot verify.
    ctx = {"retention": {"operation": "delete", "backup_verified": True}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.ADVISORY.value


def test_backup_retention_advisory_when_backup_absent():
    # Destructive delete with no backup_verified fact at all: cannot confirm a
    # verified backup, so ADVISORY (not a fail-open PASS).
    ctx = {"retention": {"operation": "delete", "record_age_days": 400,
                         "retention_days": 365}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.ADVISORY.value


def test_backup_retention_restore_advisory_when_backup_absent():
    ctx = {"retention": {"operation": "restore"}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.ADVISORY.value


def test_backup_retention_restore_blocks_when_backup_false():
    ctx = {"retention": {"operation": "restore", "backup_verified": False}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.BLOCK.value


def test_backup_retention_not_applicable_for_read():
    ctx = {"retention": {"operation": "read"}}
    assert _status(run_checks(["BACKUP_RETENTION"], ctx),
                   "BACKUP_RETENTION") == CheckStatus.NOT_APPLICABLE.value
