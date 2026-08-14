"""Legal department deterministic checkers: conflicts, legal hold, retention,
required contract clauses. Pure functions - no LLM, no DB."""
from app.compliance import CheckStatus, run_checks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def test_legal_frameworks_are_registered():
    from app.compliance.registry import list_frameworks
    tags = {f["framework"] for f in list_frameworks()}
    assert {"CONFLICT_OF_INTEREST", "LEGAL_HOLD", "RETENTION_SCHEDULE",
            "CONTRACT_CLAUSE"} <= tags


def test_conflict_of_interest():
    # A matter party is on the adverse-party list -> block.
    conflict = {"matter": {"parties": ["Acme Corp", "Jane Roe"],
                           "adverse_parties": ["acme  corp"]}}
    res = run_checks(["CONFLICT_OF_INTEREST"], conflict)
    assert _status(res, "CONFLICT_OF_INTEREST") == CheckStatus.BLOCK.value
    assert res["verified"] is False

    # No overlap -> pass.
    clean = {"matter": {"parties": ["Acme Corp"],
                        "adverse_parties": ["Globex Inc"]}}
    assert _status(run_checks(["CONFLICT_OF_INTEREST"], clean),
                   "CONFLICT_OF_INTEREST") == CheckStatus.PASS.value

    # No matter at all -> not applicable.
    assert _status(run_checks(["CONFLICT_OF_INTEREST"], {}),
                   "CONFLICT_OF_INTEREST") == CheckStatus.NOT_APPLICABLE.value

    # Matter present but no adverse list -> advisory (cannot verify).
    assert _status(run_checks(["CONFLICT_OF_INTEREST"], {"matter": {"parties": ["X"]}}),
                   "CONFLICT_OF_INTEREST") == CheckStatus.ADVISORY.value


def test_legal_hold_blocks_destructive_action():
    held = {"action": "delete", "record": {"on_legal_hold": True}}
    assert _status(run_checks(["LEGAL_HOLD"], held), "LEGAL_HOLD") == CheckStatus.BLOCK.value

    free = {"action": "delete", "record": {"on_legal_hold": False}}
    assert _status(run_checks(["LEGAL_HOLD"], free), "LEGAL_HOLD") == CheckStatus.PASS.value

    # A read is not destructive -> not applicable.
    assert _status(run_checks(["LEGAL_HOLD"], {"action": "read",
                   "record": {"on_legal_hold": True}}),
                   "LEGAL_HOLD") == CheckStatus.NOT_APPLICABLE.value

    # Destructive action but hold status unknown -> advisory.
    assert _status(run_checks(["LEGAL_HOLD"], {"action": "delete"}),
                   "LEGAL_HOLD") == CheckStatus.ADVISORY.value

    # No action at all against a HELD record -> advisory, not a silent pass.
    assert _status(run_checks(["LEGAL_HOLD"], {"record": {"on_legal_hold": True}}),
                   "LEGAL_HOLD") == CheckStatus.ADVISORY.value

    # No action against a record NOT on hold -> still not applicable.
    assert _status(run_checks(["LEGAL_HOLD"], {"record": {"on_legal_hold": False}}),
                   "LEGAL_HOLD") == CheckStatus.NOT_APPLICABLE.value


def test_retention_schedule():
    # Retained until 2030, purge attempted in 2026 -> block.
    early = {"action": "purge", "as_of": "2026-08-14",
             "record": {"retention_until": "2030-01-01"}}
    assert _status(run_checks(["RETENTION_SCHEDULE"], early),
                   "RETENTION_SCHEDULE") == CheckStatus.BLOCK.value

    # created 2019 + 7 year retention = 2026-06-01, purge in 2026-08 -> pass.
    ripe = {"action": "purge", "as_of": "2026-08-14",
            "record": {"created_date": "2019-06-01", "retention_years": 7}}
    assert _status(run_checks(["RETENTION_SCHEDULE"], ripe),
                   "RETENTION_SCHEDULE") == CheckStatus.PASS.value

    # A modify is not a disposal -> not applicable.
    assert _status(run_checks(["RETENTION_SCHEDULE"], {"action": "modify",
                   "record": {"retention_until": "2030-01-01"}}),
                   "RETENTION_SCHEDULE") == CheckStatus.NOT_APPLICABLE.value

    # No retention window on the record -> advisory.
    assert _status(run_checks(["RETENTION_SCHEDULE"], {"action": "purge",
                   "record": {}}), "RETENTION_SCHEDULE") == CheckStatus.ADVISORY.value

    # as_of PRESENT but unparseable -> advisory, not a silent fall-through to today.
    bad_asof = {"action": "purge", "as_of": "not-a-date",
                "record": {"retention_until": "2030-01-01"}}
    assert _status(run_checks(["RETENTION_SCHEDULE"], bad_asof),
                   "RETENTION_SCHEDULE") == CheckStatus.ADVISORY.value

    # as_of ABSENT still defaults to today() and blocks a future retention window.
    future = {"action": "purge", "record": {"retention_until": "2999-01-01"}}
    assert _status(run_checks(["RETENTION_SCHEDULE"], future),
                   "RETENTION_SCHEDULE") == CheckStatus.BLOCK.value


def test_contract_clause():
    # NDA missing confidentiality -> block.
    bad = {"contract": {"type": "NDA",
                        "clauses": ["Governing Law", "Term"]}}
    assert _status(run_checks(["CONTRACT_CLAUSE"], bad),
                   "CONTRACT_CLAUSE") == CheckStatus.BLOCK.value

    # MSA with every required clause (mixed casing/separators) -> pass.
    good = {"contract": {"type": "MSA", "clauses": [
        "Limitation of Liability", "governing_law", "Confidentiality",
        "Indemnification"]}}
    assert _status(run_checks(["CONTRACT_CLAUSE"], good),
                   "CONTRACT_CLAUSE") == CheckStatus.PASS.value

    # No contract in scope -> not applicable.
    assert _status(run_checks(["CONTRACT_CLAUSE"], {}),
                   "CONTRACT_CLAUSE") == CheckStatus.NOT_APPLICABLE.value

    # Contract present but no clause inventory -> advisory.
    assert _status(run_checks(["CONTRACT_CLAUSE"], {"contract": {"type": "MSA"}}),
                   "CONTRACT_CLAUSE") == CheckStatus.ADVISORY.value

    # Unmodeled contract type -> advisory (unknown required set), NOT a false block,
    # even though its clause list would miss the old hardcoded default set.
    unmodeled = {"contract": {"type": "SOW", "clauses": ["Term"]}}
    assert _status(run_checks(["CONTRACT_CLAUSE"], unmodeled),
                   "CONTRACT_CLAUSE") == CheckStatus.ADVISORY.value

    # A caller-supplied required set on an unmodeled type is still enforced -> block.
    override = {"contract": {"type": "SOW", "required_clauses": ["Confidentiality"],
                             "clauses": ["Term"]}}
    assert _status(run_checks(["CONTRACT_CLAUSE"], override),
                   "CONTRACT_CLAUSE") == CheckStatus.BLOCK.value
