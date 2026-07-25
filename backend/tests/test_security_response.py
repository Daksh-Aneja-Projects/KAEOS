"""SOAR - security event ingestion + governed containment (REAL, no mocks).

A signed security event creates a real engineering Incident, runs real
containment (connector paused, ingest secret rotated), deactivates the
affected user only at CRITICAL, and ledgers the whole response.
"""
import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import init_db

TENANT = "tenant_soar_test"
SECRET = "soar-webhook-secret"


@pytest.fixture(autouse=True)
async def _tables():
    from sqlalchemy import text
    from app.core.database import engine as app_engine
    from app.models.domain import Connector, ConnectorCredential
    from app.models.sync import SyncLedger, OutboundWrite
    from app.models.auth import User
    from app.engineering.models.incidents import Incident
    async with app_engine.begin() as conn:
        for model in (Connector, ConnectorCredential, SyncLedger, OutboundWrite,
                      User, Incident):
            await conn.run_sync(model.__table__.create, checkfirst=True)
        for tbl in ("sync_ledger", "connector_credentials", "connectors"):
            await conn.execute(text(f"DELETE FROM {tbl}"))
        await conn.execute(text(f"DELETE FROM eng_incidents WHERE tenant_id = '{TENANT}'"))
        await conn.execute(text(f"DELETE FROM users WHERE tenant_id = '{TENANT}'"))
    yield


@pytest_asyncio.fixture()
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _connector() -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import encrypt_secrets
    async with AsyncSessionLocal() as db:
        c = Connector(tenant_id=TENANT, name="okta", category="security",
                      connector_type="WEBHOOK", status="CONNECTED")
        db.add(c)
        await db.flush()
        db.add(ConnectorCredential(
            connector_id=c.id, tenant_id=TENANT, provider="generic_rest",
            config={}, secrets_encrypted=encrypt_secrets({"webhook_secret": SECRET})))
        await db.commit()
        return c.id


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_critical_breach_full_containment(client):
    """CRITICAL: incident created, connector quarantined, secret rotated,
    affected user deactivated, response ledgered."""
    from app.core.database import AsyncSessionLocal
    from app.models.auth import User, UserRole
    async with AsyncSessionLocal() as db:
        db.add(User(id="u-victim", email="victim@corp.com", display_name="V",
                    hashed_password="x", role=UserRole.ANALYST,
                    tenant_id=TENANT, is_active=True))
        await db.commit()

    connector_id = await _connector()
    body = json.dumps({
        "event_type": "credential_leak", "severity": "CRITICAL",
        "summary": "OAuth token exfiltrated from integration",
        "affected_user_email": "victim@corp.com", "external_id": "SIEM-9001",
    }).encode()
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}/security",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["severity"] == "CRITICAL"
    assert any("quarantine_connector" in a for a in out["actions_taken"])
    assert any("rotate_webhook_secret" in a for a in out["actions_taken"])
    assert any("disable_user" in a for a in out["actions_taken"])

    from sqlalchemy import select
    from app.models.domain import Connector
    from app.engineering.models.incidents import Incident, IncidentSeverity
    from app.models.auth import User as U
    from app.models.sync import SyncLedger
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Connector).where(Connector.id == connector_id))).scalar_one()
        assert c.status == "PAUSED"                        # sync REALLY halted
        inc = (await db.execute(select(Incident).where(
            Incident.id == out["incident_id"]))).scalar_one()
        assert inc.severity == IncidentSeverity.SEV1
        victim = (await db.execute(select(U).where(U.email == "victim@corp.com"))).scalar_one()
        assert victim.is_active is False                   # account REALLY disabled
        ledger = (await db.execute(select(SyncLedger).where(
            SyncLedger.tenant_id == TENANT,
            SyncLedger.entity_type == "security_event"))).scalars().all()
        assert ledger and "quarantine_connector" in (ledger[-1].detail or "")

    # the ROTATED secret means the old signature no longer authenticates
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}/security",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_medium_event_contains_nothing_but_recommends(client):
    """Below HIGH: incident recorded, no quarantine, human-recommended actions."""
    connector_id = await _connector()
    body = json.dumps({
        "event_type": "anomalous_access", "severity": "MEDIUM",
        "summary": "Login from a new location",
        "affected_user_email": "victim2@corp.com",
    }).encode()
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}/security",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.status_code == 200
    out = resp.json()
    assert out["actions_taken"] == []
    assert any("quarantine_connector" in r for r in out["recommended_actions"])

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Connector).where(Connector.id == connector_id))).scalar_one()
        assert c.status == "CONNECTED"                     # NOT paused


@pytest.mark.asyncio
async def test_bad_signature_rejected(client):
    connector_id = await _connector()
    body = b'{"event_type": "breach", "severity": "CRITICAL"}'
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}/security",
                             content=body, headers={"X-KAEOS-Signature": "nope"})
    assert resp.status_code == 401
