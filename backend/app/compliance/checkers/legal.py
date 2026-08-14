"""Legal department statutory checkers: conflicts of interest, legal hold,
records retention, and required contract clauses.

Deterministic, no LLM / no DB / no network. Each reads the structured facts it
needs from the gate ``context`` and returns a citation-backed verdict. Absent
inputs return ADVISORY (never a silent PASS); a real violation BLOCKs.
"""
from __future__ import annotations

from datetime import date

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "legal"

# Actions that mutate or destroy a record - the trigger for hold/retention.
_DESTRUCTIVE = {"delete", "destroy", "purge", "remove", "erase", "expunge",
                "modify", "alter", "overwrite", "edit", "update", "redact",
                "dispose", "shred"}
# Actions that permanently dispose of a record - the trigger for retention.
_DISPOSAL = {"delete", "destroy", "purge", "remove", "erase", "expunge",
             "dispose", "shred"}


def _norm(s) -> str:
    """Lowercase and collapse whitespace so 'Acme  Corp' == 'acme corp'."""
    return " ".join(str(s).lower().split())


def _norm_clause(s) -> str:
    """Canonicalize a clause name: 'Limitation of Liability' ==
    'limitation_of_liability' == 'limitation-of-liability'."""
    return "-".join(str(s).lower().replace("_", " ").replace("-", " ").split())


def _parse_date(v):
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return date.fromisoformat(str(v))
    except (ValueError, TypeError):
        return None


def _add_years(d: date, years: int) -> date:
    """d + N years, folding Feb 29 back to Feb 28 in a non-leap target year."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> non-leap year
        return d.replace(year=d.year + years, day=28)


@register("CONFLICT_OF_INTEREST", department=_DEPT,
          title="Conflict-of-interest screen (adverse parties)",
          citation="ABA Model Rules of Professional Conduct, Rule 1.7")
def check_conflict_of_interest(context: dict) -> CheckResult:
    """A new matter's parties must not overlap the firm's adverse-party list.
    Needs ``context['matter']`` = {parties: [...], adverse_parties: [...]} (or
    top-level ``parties`` / ``adverse_parties``)."""
    matter = context.get("matter") or {}
    parties = matter.get("parties") or context.get("parties")
    if not parties:
        return CheckResult("CONFLICT_OF_INTEREST", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    adverse = matter.get("adverse_parties")
    if adverse is None:
        adverse = context.get("adverse_parties")
    if adverse is None:
        return CheckResult("CONFLICT_OF_INTEREST", CheckStatus.ADVISORY,
                           [Finding("no_adverse_list",
                                    "No adverse-party list supplied; conflicts "
                                    "cannot be screened.", "MEDI")],
                           method="deterministic")

    adverse_norm = {_norm(a) for a in adverse}
    hits = [p for p in parties if _norm(p) in adverse_norm]
    if hits:
        return CheckResult("CONFLICT_OF_INTEREST", CheckStatus.BLOCK,
                           [Finding("adverse_party_overlap",
                                    f"Matter party overlaps an adverse party: "
                                    f"{', '.join(sorted(set(hits)))}. A concurrent "
                                    "conflict requires screening and informed "
                                    "written consent before proceeding.", "HIGH")],
                           method="deterministic",
                           detail={"conflicts": sorted(set(hits))})
    return CheckResult("CONFLICT_OF_INTEREST", CheckStatus.PASS, [],
                       method="deterministic")


@register("LEGAL_HOLD", department=_DEPT,
          title="Legal hold / preservation (no spoliation)",
          citation="Federal Rules of Civil Procedure 37(e)")
def check_legal_hold(context: dict) -> CheckResult:
    """A record under an active legal hold cannot be deleted or modified.
    Applies only to destructive actions. Needs ``context['action']`` and a hold
    flag on ``context['record']['on_legal_hold']`` (or top-level
    ``legal_hold``)."""
    action = _norm(context.get("action") or context.get("operation") or "")
    record = context.get("record") or {}
    on_hold = record.get("on_legal_hold")
    if on_hold is None:
        on_hold = record.get("legal_hold")
    if on_hold is None:
        on_hold = context.get("legal_hold")

    if action not in _DESTRUCTIVE:
        # A missing action against a record known to be held can't be cleared as a
        # silent pass - FRCP 37(e) spoliation needs the action verified first.
        if not action and on_hold:
            return CheckResult("LEGAL_HOLD", CheckStatus.ADVISORY,
                               [Finding("action_unknown_on_held_record",
                                        "Record is under an active legal hold but no "
                                        "action was supplied; the action must be "
                                        "verified as non-destructive before it "
                                        "proceeds.", "MEDI")],
                               method="deterministic")
        return CheckResult("LEGAL_HOLD", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    if on_hold is None:
        return CheckResult("LEGAL_HOLD", CheckStatus.ADVISORY,
                           [Finding("hold_status_unknown",
                                    "Cannot confirm whether this record is under "
                                    "a legal hold; destructive actions must be "
                                    "verified against active holds.", "MEDI")],
                           method="deterministic")
    if on_hold:
        return CheckResult("LEGAL_HOLD", CheckStatus.BLOCK,
                           [Finding("spoliation_risk",
                                    f"Record is under an active legal hold; the "
                                    f"'{action}' action would destroy or alter "
                                    "evidence and risks spoliation sanctions.",
                                    "CRIT")],
                           method="deterministic")
    return CheckResult("LEGAL_HOLD", CheckStatus.PASS, [], method="deterministic")


@register("RETENTION_SCHEDULE", department=_DEPT,
          title="Records-retention schedule (no premature disposal)",
          citation="18 U.S.C. 1519; applicable records-retention schedule")
def check_retention_schedule(context: dict) -> CheckResult:
    """A record younger than its retention period cannot be purged. Applies only
    to disposal actions. Needs ``context['record']`` with either
    ``retention_until`` or (``created_date`` + ``retention_years``); optional
    ``context['as_of']`` for a fixed evaluation date."""
    action = _norm(context.get("action") or context.get("operation") or "")
    if action not in _DISPOSAL:
        return CheckResult("RETENTION_SCHEDULE", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    record = context.get("record") or {}
    if "as_of" in context:
        as_of = _parse_date(context.get("as_of"))
        if as_of is None:
            return CheckResult("RETENTION_SCHEDULE", CheckStatus.ADVISORY,
                               [Finding("bad_as_of",
                                        "Supplied as_of date is unparseable; cannot "
                                        "evaluate the retention window.", "MEDI")],
                               method="deterministic")
    else:
        as_of = date.today()

    retention_until = _parse_date(record.get("retention_until"))
    if retention_until is None:
        created = _parse_date(record.get("created_date") or record.get("created_at"))
        years = record.get("retention_years")
        if created is not None and years is not None:
            try:
                retention_until = _add_years(created, int(years))
            except (ValueError, TypeError):
                retention_until = None
    if retention_until is None:
        return CheckResult("RETENTION_SCHEDULE", CheckStatus.ADVISORY,
                           [Finding("no_retention_window",
                                    "No retention period on this record; cannot "
                                    "verify it is eligible for disposal.", "MEDI")],
                           method="deterministic")

    if as_of < retention_until:
        return CheckResult("RETENTION_SCHEDULE", CheckStatus.BLOCK,
                           [Finding("within_retention",
                                    f"Record is retained until "
                                    f"{retention_until.isoformat()} and cannot be "
                                    f"purged as of {as_of.isoformat()}.", "HIGH")],
                           method="deterministic",
                           detail={"retention_until": retention_until.isoformat(),
                                   "as_of": as_of.isoformat()})
    return CheckResult("RETENTION_SCHEDULE", CheckStatus.PASS, [],
                       method="deterministic")


# Required clauses by contract type (normalized). An unmodeled type has no known
# required set, so it is ADVISORY (not BLOCK) unless the caller overrides.
_REQUIRED_CLAUSES = {
    "NDA": {"confidentiality", "governing-law", "term"},
    "MSA": {"limitation-of-liability", "governing-law", "confidentiality",
            "indemnification"},
    "DPA": {"confidentiality", "governing-law", "data-processing"},
}


@register("CONTRACT_CLAUSE", department=_DEPT,
          title="Required contract clauses present",
          citation="ABA Model Rule 1.1 (competent representation); contract standards")
def check_contract_clause(context: dict) -> CheckResult:
    """A contract must contain the clauses required for its type (limitation of
    liability, governing law, confidentiality, ...). Needs
    ``context['contract']`` = {type, clauses: [...]} (optional
    ``required_clauses`` override)."""
    contract = context.get("contract")
    if not contract:
        return CheckResult("CONTRACT_CLAUSE", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    ctype = _norm(contract.get("type") or contract.get("contract_type") or "").upper()
    required = contract.get("required_clauses")
    if required is None:
        required = _REQUIRED_CLAUSES.get(ctype)
    if required is None:
        return CheckResult("CONTRACT_CLAUSE", CheckStatus.ADVISORY,
                           [Finding("unknown_contract_type",
                                    f"No required-clause set is modeled for "
                                    f"contract type '{ctype or 'unspecified'}'; "
                                    "cannot verify required clauses.", "MEDI")],
                           method="deterministic")
    required_norm = {_norm_clause(c) for c in required}

    present_raw = contract.get("clauses")
    if present_raw is None:
        return CheckResult("CONTRACT_CLAUSE", CheckStatus.ADVISORY,
                           [Finding("no_clause_inventory",
                                    "No clause list supplied; required clauses "
                                    "cannot be verified.", "MEDI")],
                           method="deterministic")
    present_norm = {_norm_clause(c) for c in present_raw}

    missing = sorted(required_norm - present_norm)
    if missing:
        pretty = ", ".join(m.replace("-", " ") for m in missing)
        return CheckResult("CONTRACT_CLAUSE", CheckStatus.BLOCK,
                           [Finding("missing_required_clause",
                                    f"Contract is missing required clause(s): "
                                    f"{pretty}.", "HIGH")],
                           method="deterministic",
                           detail={"missing": missing})
    return CheckResult("CONTRACT_CLAUSE", CheckStatus.PASS, [],
                       method="deterministic")
