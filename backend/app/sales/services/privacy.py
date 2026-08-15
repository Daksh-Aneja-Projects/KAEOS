"""
KAEOS Sales — Data-Privacy Gate (CCPA / TCPA / DSAR)

Binds the deterministic CCPA/TCPA/DSAR checkers (app/compliance/checkers/crm.py)
as real fail-closed gates in front of genuine sales actions: contacting a lead,
sharing account data with a partner, and evaluating a data-subject request
deadline. No LLM, no new persisted PII columns - the checker's own verdict
(PASS/BLOCK/ADVISORY) is the answer, and every call leaves a signed provenance
entry whether it passes or is blocked. Mirrors
app/healthcare/services/phi_disclosure.py's fail-closed pattern.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.registry import run_checks
from app.services.provenance import append_ledger_event


class PrivacyCheckBlocked(ValueError):
    """A CCPA/TCPA/DSAR checker returned a blocking verdict. Carries the full
    verdict so the caller (the router) can surface WHY it was refused."""

    def __init__(self, message: str, verdict: Dict[str, Any]):
        super().__init__(message)
        self.verdict = verdict


def _reasons(verdict: Dict[str, Any]) -> str:
    return "; ".join(
        f["framework"] + ": " + "; ".join(m["message"] for m in f["findings"])
        for f in verdict["blocking"]
    )


async def _gate(
    db: AsyncSession, tenant_id: str, *, scope: str, event_type: str,
    frameworks: list, context: dict, allow_message: str,
) -> Dict[str, Any]:
    verdict = run_checks(frameworks, context)
    reasons = _reasons(verdict)
    # Signed evidence either way: a PASS and a BLOCK both leave a replayable
    # trail, matching the PHI disclosure gate.
    await append_ledger_event(
        db, tenant_id=tenant_id,
        event_type=event_type if verdict["verified"] else f"{event_type}_BLOCKED",
        reasoning=reasons or allow_message,
        scope=scope,
    )
    if not verdict["verified"]:
        raise PrivacyCheckBlocked(reasons or "Blocked by a statutory privacy checker.", verdict)
    return verdict


async def check_contact(
    db: AsyncSession, tenant_id: str, *, lead, channel: str,
    do_not_contact: Optional[list] = None, consent: Optional[bool] = None,
) -> Dict[str, Any]:
    """TCPA gate before a rep or dialer calls/texts a lead. The phone number is
    the lead's own real record; do_not_contact/consent are supplied by the
    caller because the platform has no persisted DNC list yet - an omission
    surfaces honestly as ADVISORY rather than a fabricated PASS."""
    context = {
        "action": channel, "channel": channel,
        "phone": lead.phone,
        "do_not_contact": do_not_contact,
        "consent": consent,
        "data_subject": {"consent": consent} if consent is not None else {},
    }
    return await _gate(
        db, tenant_id, scope=f"lead:{lead.id}", event_type="TCPA_CONTACT_CHECK",
        frameworks=["TCPA"], context=context,
        allow_message=f"{channel} outreach to lead {lead.id} cleared the TCPA do-not-contact check.",
    )


async def check_data_sale(
    db: AsyncSession, tenant_id: str, *, account, opted_out_of_sale: bool,
) -> Dict[str, Any]:
    """CCPA gate before an account's data is shared/sold to a partner (e.g. a
    data-enrichment vendor sync)."""
    context = {"action": "sell", "data_subject": {"opted_out_of_sale": opted_out_of_sale}}
    return await _gate(
        db, tenant_id, scope=f"account:{account.id}", event_type="CCPA_SALE_CHECK",
        frameworks=["CCPA"], context=context,
        allow_message=f"Sharing account {account.id} data cleared the CCPA sale opt-out check.",
    )


async def check_dsar(
    db: AsyncSession, tenant_id: str, *, subject_type: str, subject_id: str,
    regime: str, request_date: str, fulfilled_date: Optional[str] = None,
    status: Optional[str] = None, as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """DSAR gate: is a data-subject access/deletion request for a lead or
    account within its statutory response window (GDPR one calendar month,
    CCPA 45 days)."""
    context = {"dsar": {"regime": regime, "request_date": request_date,
                        "fulfilled_date": fulfilled_date, "status": status, "as_of": as_of}}
    return await _gate(
        db, tenant_id, scope=f"{subject_type}:{subject_id}", event_type="DSAR_DEADLINE_CHECK",
        frameworks=["DSAR"], context=context,
        allow_message=(f"{regime} data-subject request for {subject_type} {subject_id} "
                       "is within the statutory deadline."),
    )
