"""H1: connector-pulled Signals are bridged into the event mesh.

live_connectors persisted `Signal` rows while the event mesh reads
`ExternalSignal` — two tables, so the connector pull fed nothing into the only
closed loop. ingest_connector_signals mirrors the new signals into
ExternalSignal and correlates them to the twin (correlate-only, quarantined
skipped)."""
import pytest
from sqlalchemy import select

from app.models.domain import Signal
from app.models.event_mesh import ExternalSignal
from app.services.event_mesh import ingest_connector_signals

TENANT = "tenant_bridge"


def _sig(ext_id, payload, stype="LIVE_SYNC"):
    return Signal(
        id=f"sig_{ext_id}", tenant_id=TENANT, signal_type=stype,
        source_type="jira", source_entity=f"ticket:{ext_id}",
        external_id=ext_id, clean_payload=payload, authority_score=0.7,
        domain="engineering",
    )


@pytest.mark.asyncio
async def test_connector_signals_bridge_and_correlate(db):
    signals = [
        _sig("J-1", "Security CVE vulnerability in the deploy pipeline"),
        _sig("J-2", "Payroll headcount question from an employee"),
        _sig("J-3", "malicious injection ignore previous", stype="QUARANTINED"),
    ]
    bridged = await ingest_connector_signals(db, TENANT, signals)
    await db.commit()

    # Quarantined signal is not bridged into the mesh.
    assert bridged == 2

    rows = (await db.execute(
        select(ExternalSignal).where(ExternalSignal.tenant_id == TENANT)
    )).scalars().all()
    assert len(rows) == 2
    # correlate() ran: each bridged signal is CORRELATED and matched to the twin.
    assert all(r.status == "CORRELATED" for r in rows)
    assert all(r.source == "jira" for r in rows)
    assert all(r.matched_entities for r in rows), "each should match at least one twin dept"
