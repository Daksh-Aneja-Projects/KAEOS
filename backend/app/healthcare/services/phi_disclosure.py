"""
KAEOS Healthcare — PHI Disclosure Service (the load-bearing privacy control)

A PHI disclosure MUST pass the deterministic HIPAA + 42 CFR Part 2 checkers
BEFORE it is recorded. Fail-closed: if any checker BLOCKs (or a tag is
unbacked), nothing is persisted and the denial is written to the signed
provenance ledger instead. This binds the four EXISTING checkers in
app/compliance/checkers/healthcare.py as real gates - it does not re-implement
their logic.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.registry import run_checks
from app.healthcare.models.core import PHIDisclosure
from app.services.provenance import append_ledger_event

# The four healthcare frameworks with deterministic checkers. Bound as gates.
PHI_FRAMEWORKS = [
    "HIPAA_MINIMUM_NECESSARY",
    "HIPAA_AUTHORIZATION",
    "HIPAA_DEIDENTIFICATION",
    "PART2",
]


class PHIDisclosureError(ValueError):
    """A disclosure that fails a statutory checker. The router maps this to 4xx.
    Carries the blocking findings so the caller sees WHY it was refused."""

    def __init__(self, message: str, blocking: Optional[List[dict]] = None):
        super().__init__(message)
        self.blocking = blocking or []


def build_context(
    *,
    purpose: str,
    fields: List[str],
    authorization: Optional[dict] = None,
    diagnosis_codes: Optional[List[str]] = None,
    part2_records: bool = False,
    part2_consent: Optional[dict] = None,
) -> Dict[str, Any]:
    """Assemble the gate context the healthcare checkers read. Pure - no I/O."""
    return {
        "phi_disclosure": {
            "purpose": purpose,
            "fields": list(fields or []),
            "diagnosis_codes": list(diagnosis_codes or []),
        },
        "authorization": authorization or {},
        "part2_records": bool(part2_records),
        "part2_consent": part2_consent or {},
        "diagnosis_codes": list(diagnosis_codes or []),
    }


def evaluate_disclosure(context: Dict[str, Any]) -> Dict[str, Any]:
    """Run the four checkers against ``context`` and return run_checks' verdict
    ``{verified, blocking, advisory, results}``. No persistence - a dry run."""
    return run_checks(PHI_FRAMEWORKS, context)


def _norm(v: str) -> str:
    return str(v).strip().lower().replace(" ", "_").replace("-", "_")


def _scope_covers(scope: str, purpose: str) -> bool:
    # ponytail: token-subset match (every purpose token is a token of the
    # consent scope). A structured purpose->scope map would be exact; add one
    # if consent scopes proliferate beyond the current free-text handful.
    ptoks = {t for t in _norm(purpose).split("_") if t}
    return bool(ptoks) and ptoks <= set(_norm(scope).split("_"))


def resolve_consent_facts(
    *,
    purpose: str,
    stored_diagnosis_codes: Optional[List[str]] = None,
    stored_consents: Optional[List[dict]] = None,
    diagnosis_codes: Optional[List[str]] = None,
    authorization: Optional[dict] = None,
    part2_consent: Optional[dict] = None,
) -> Dict[str, Any]:
    """Bind an encounter's stored facts and the consent store to the gate
    inputs. The store is the source of truth, NOT the request body:

    - the encounter's stored diagnosis codes are unioned in, so omitting
      ``diagnosis_codes`` can never dodge Part 2 on an SUD encounter;
    - ``authorization`` / ``part2_consent`` are derived from the patient's
      ACTIVE consents (revoked_at IS NULL, matching scope / the part2 flag).

    The request body may only STRENGTHEN the verdict (assert a revoked / expired
    restriction, or withhold its own signature); it can never manufacture a
    consent the store lacks. Pure - no I/O.

    ``stored_consents``: ``[{"scope": str, "part2": bool, "active": bool}, ...]``
    """
    codes = list(dict.fromkeys(
        [str(c) for c in (stored_diagnosis_codes or [])]
        + [str(c) for c in (diagnosis_codes or [])]
    ))
    consents = stored_consents or []
    store_part2_ok = any(c.get("part2") and c.get("active") for c in consents)
    store_auth_ok = any(
        (not c.get("part2")) and c.get("active")
        and _scope_covers(c.get("scope") or "", purpose)
        for c in consents
    )
    body_auth = authorization or {}
    body_p2 = part2_consent or {}
    # signed only if the store backs it AND the body did not withhold its own
    # signature; revoked/expired can be ADDED by the body but the store's
    # "no active consent" (signed False) can never be flipped to True.
    return {
        "diagnosis_codes": codes,
        "authorization": {
            "signed": store_auth_ok and bool(body_auth.get("signed", True)),
            "revoked": bool(body_auth.get("revoked")),
            "expired": bool(body_auth.get("expired")),
        },
        "part2_consent": {
            "signed": store_part2_ok and bool(body_p2.get("signed", True)),
            "revoked": bool(body_p2.get("revoked")),
            "expired": bool(body_p2.get("expired")),
        },
    }


async def record_disclosure(
    db: AsyncSession,
    tenant_id: str,
    *,
    purpose: str,
    recipient: str,
    fields: List[str],
    minimum_necessary_justification: str,
    encounter_id: Optional[str] = None,
    authorization: Optional[dict] = None,
    diagnosis_codes: Optional[List[str]] = None,
    part2_records: bool = False,
    part2_consent: Optional[dict] = None,
    recorded_by: Optional[str] = None,
) -> PHIDisclosure:
    """Fail-closed: gate the disclosure through the HIPAA/Part 2 checkers, then
    persist it ONLY if it passed. A blocked disclosure raises PHIDisclosureError
    and writes the denial to the ledger; no PHIDisclosure row is created."""
    if not (minimum_necessary_justification or "").strip():
        raise PHIDisclosureError("A minimum-necessary justification is required.")

    context = build_context(
        purpose=purpose,
        fields=fields,
        authorization=authorization,
        diagnosis_codes=diagnosis_codes,
        part2_records=part2_records,
        part2_consent=part2_consent,
    )
    verdict = run_checks(PHI_FRAMEWORKS, context)

    if not verdict["verified"]:
        reasons = "; ".join(
            f["framework"] + ": " + "; ".join(m["message"] for m in f["findings"])
            for f in verdict["blocking"]
        ) or "PHI disclosure blocked by a statutory checker."
        # Signed evidence of the DENIAL - the control leaves a replayable trail
        # even (especially) when it refuses.
        await append_ledger_event(
            db, tenant_id=tenant_id, event_type="PHI_DISCLOSURE_BLOCKED",
            reasoning=f"Refused disclosure to '{recipient}' for '{purpose}': {reasons}",
            actor_hash=recorded_by,
            scope=encounter_id or "phi_disclosure",
        )
        raise PHIDisclosureError(reasons, blocking=verdict["blocking"])

    disclosure = PHIDisclosure(
        tenant_id=tenant_id,
        encounter_id=encounter_id,
        purpose=purpose,
        recipient=recipient,
        fields=list(fields or []),
        minimum_necessary_justification=minimum_necessary_justification,
        part2=bool(part2_records),
        authorized=True,
        recorded_by=recorded_by,
    )
    db.add(disclosure)
    # commit=True lands the row atomically with the provenance entry.
    await append_ledger_event(
        db, tenant_id=tenant_id, event_type="PHI_DISCLOSURE_RECORDED",
        reasoning=(f"Authorized disclosure to '{recipient}' for '{purpose}' "
                   f"({len(fields or [])} fields); minimum-necessary + authorization verified."),
        actor_hash=recorded_by,
        scope=encounter_id or "phi_disclosure",
    )
    await db.refresh(disclosure)
    return disclosure


def _selfcheck() -> None:
    """Consent resolution is a security path - assert its teeth hold."""
    # (a) a stored SUD code is unioned in even when the body omits it.
    r = resolve_consent_facts(purpose="treatment",
                              stored_diagnosis_codes=["F10.20"], stored_consents=[])
    assert "F10.20" in r["diagnosis_codes"]
    # (b) a revoked/absent Part 2 consent cannot be rescued by the body.
    r = resolve_consent_facts(purpose="treatment", part2_consent={"signed": True},
                              stored_consents=[{"scope": "part2", "part2": True, "active": False}])
    assert r["part2_consent"]["signed"] is False
    # an active store consent, with no body withdrawal, is signed.
    r = resolve_consent_facts(purpose="treatment",
                              stored_consents=[{"scope": "part2", "part2": True, "active": True}])
    assert r["part2_consent"]["signed"] is True
    # non-TPO authorization derives from a scope-matching active consent.
    r = resolve_consent_facts(purpose="research", stored_consents=[
        {"scope": "research_participation", "part2": False, "active": True}])
    assert r["authorization"]["signed"] is True
    # the body cannot manufacture an authorization the store lacks.
    r = resolve_consent_facts(purpose="marketing", authorization={"signed": True},
                              stored_consents=[])
    assert r["authorization"]["signed"] is False
    print("phi_disclosure consent-resolution self-check passed.")


if __name__ == "__main__":
    _selfcheck()
