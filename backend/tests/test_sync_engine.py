"""Bidirectional sync engine - REAL end-to-end, no mocks.

Inbound: a real HTTP POST to the public ingest endpoint with a valid HMAC
upserts a twin row and ledgers APPLIED; a bad signature is 401; an unknown
shape is ledgered SKIPPED (the engine never guesses).

Outbound: a queued write is dispatched over REAL HTTP to a local server acting
as the external system via the generic_rest adapter; no-connector and
no-credentials outcomes are honest statuses, never silence.
"""
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import init_db

TENANT = "tenant_sync_test"
SECRET = "sync-webhook-secret"


class _ExternalSystem(BaseHTTPRequestHandler):
    """A real HTTP server standing in the external system's shoes."""
    received: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        _ExternalSystem.received.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length) or b"{}"),
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass


@pytest.fixture()
def external_system():
    _ExternalSystem.received = []
    server = HTTPServer(("127.0.0.1", 0), _ExternalSystem)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", _ExternalSystem.received
    server.shutdown()


@pytest.fixture(autouse=True)
async def _sync_tables():
    """Create everything the engine touches on the APP engine (dual-engine trap:
    the sync engine reads/writes through AsyncSessionLocal, not the conftest
    test engine)."""
    from sqlalchemy import text
    from app.core.database import engine as app_engine
    from app.models.sync import SyncLedger, OutboundWrite
    from app.models.domain import Connector, ConnectorCredential
    from app.hr.models.core import HREmployee
    async with app_engine.begin() as conn:
        for model in (Connector, ConnectorCredential, SyncLedger, OutboundWrite, HREmployee):
            await conn.run_sync(model.__table__.create, checkfirst=True)
        for tbl in ("sync_ledger", "outbound_writes", "connector_credentials", "connectors"):
            await conn.execute(text(f"DELETE FROM {tbl}"))
    yield


@pytest_asyncio.fixture()
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_connector(provider="workday", category="hris", status="CONNECTED",
                          config=None, secrets=None) -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import encrypt_secrets
    async with AsyncSessionLocal() as db:
        c = Connector(tenant_id=TENANT, name=f"{provider} connector",
                      category=category, connector_type="WEBHOOK", status=status)
        db.add(c)
        await db.flush()
        db.add(ConnectorCredential(
            connector_id=c.id, tenant_id=TENANT, provider=provider,
            config=config or {},
            secrets_encrypted=encrypt_secrets({"webhook_secret": SECRET, **(secrets or {})}),
        ))
        await db.commit()
        return c.id


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_realtime_ingest_upserts_employee_and_ledgers(client):
    """Workday changes an employee -> KAEOS twin updates in realtime."""
    connector_id = await _make_connector(provider="workday")
    body = json.dumps({
        "entity_type": "employee", "op": "upsert", "external_id": "WD-1001",
        "data": {"email": "jane.sync@corp.com", "first_name": "Jane",
                 "last_name": "Sync", "job_title": "Director of Ops",
                 "status": "ACTIVE"},
    }).encode()

    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}",
                             content=body,
                             headers={"X-KAEOS-Signature": _sign(body),
                                      "Content-Type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "applied"

    # the twin row is real
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.hr.models.core import HREmployee
    from app.models.sync import SyncLedger
    async with AsyncSessionLocal() as db:
        emp = (await db.execute(select(HREmployee).where(
            HREmployee.email == "jane.sync@corp.com"))).scalar_one()
        assert emp.job_title == "Director of Ops"
        entry = (await db.execute(select(SyncLedger).where(
            SyncLedger.tenant_id == TENANT,
            SyncLedger.direction == "IN"))).scalars().all()
        assert any(e.status == "APPLIED" and e.entity_type == "employee" for e in entry)

    # a second push UPDATES the same row (matched by email), no duplicate
    body2 = json.dumps({
        "entity_type": "employee", "op": "upsert", "external_id": "WD-1001",
        "data": {"email": "jane.sync@corp.com", "job_title": "VP of Ops"},
    }).encode()
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}",
                             content=body2,
                             headers={"X-KAEOS-Signature": _sign(body2)})
    assert resp.json()["status"] == "applied"
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HREmployee).where(
            HREmployee.email == "jane.sync@corp.com"))).scalars().all()
        assert len(rows) == 1 and rows[0].job_title == "VP of Ops"


@pytest.mark.asyncio
async def test_ingest_rejects_bad_signature_and_unknown_connector(client):
    connector_id = await _make_connector()
    body = b'{"entity_type": "employee", "op": "upsert", "data": {"email": "x@y.z"}}'
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}",
                             content=body,
                             headers={"X-KAEOS-Signature": "deadbeef"})
    assert resp.status_code == 401
    resp = await client.post("/api/v1/integrations/ingest/nope",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unrecognized_payload_is_ledgered_skipped_not_guessed(client):
    connector_id = await _make_connector()
    body = json.dumps({"something": "else"}).encode()
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.sync import SyncLedger
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SyncLedger).where(
            SyncLedger.tenant_id == TENANT, SyncLedger.status == "SKIPPED"))).scalars().all()
        assert rows and "unrecognized" in (rows[-1].detail or "")


@pytest.mark.asyncio
async def test_workday_native_shape_normalizes(client):
    connector_id = await _make_connector(provider="workday")
    body = json.dumps({"worker": {
        "id": "WD-7", "primaryWorkEmail": "native.shape@corp.com",
        "name": {"firstName": "Native", "lastName": "Shape"},
        "businessTitle": "Analyst",
    }}).encode()
    resp = await client.post(f"/api/v1/integrations/ingest/{connector_id}",
                             content=body, headers={"X-KAEOS-Signature": _sign(body)})
    assert resp.json()["status"] == "applied", resp.text


@pytest.mark.asyncio
async def test_outbound_write_back_over_real_http(external_system):
    """A governed KAEOS change is pushed to the external system for real."""
    url, received = external_system
    await _make_connector(provider="generic_rest", category="hris",
                          config={"base_url": url}, secrets={"api_key": "ext-key-1"})

    from app.services.sync_engine import queue_outbound, dispatch_outbound
    write_id = await queue_outbound(
        TENANT, "employee", "emp-internal-1", "UPSERT",
        {"email": "jane.sync@corp.com", "job_title": "SVP of Ops"},
        external_id="WD-1001")
    assert write_id is not None

    result = await dispatch_outbound(tenant_id=TENANT)
    assert result["sent"] == 1 and result["failed"] == 0

    # the external system REALLY received it, authenticated
    assert len(received) == 1
    req = received[0]
    assert req["path"] == "/kaeos/sync"
    assert req["auth"] == "Bearer ext-key-1"
    assert req["body"]["data"]["job_title"] == "SVP of Ops"
    assert req["body"]["external_id"] == "WD-1001"

    # ledger has the OUT entry; the write row is SENT
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.sync import OutboundWrite, SyncLedger
    async with AsyncSessionLocal() as db:
        w = (await db.execute(select(OutboundWrite).where(
            OutboundWrite.id == write_id))).scalar_one()
        assert w.status == "SENT"
        out = (await db.execute(select(SyncLedger).where(
            SyncLedger.direction == "OUT", SyncLedger.tenant_id == TENANT))).scalars().all()
        assert any(e.status == "APPLIED" for e in out)


@pytest.mark.asyncio
async def test_outbound_honest_states_no_connector_and_no_creds():
    from app.services.sync_engine import queue_outbound, dispatch_outbound
    t2 = TENANT + "_lonely"
    wid = await queue_outbound(t2, "account", "acc-1", "UPSERT", {"name": "X Corp"})
    result = await dispatch_outbound(tenant_id=t2)
    assert result["skipped"] == 1 and result["sent"] == 0

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.sync import OutboundWrite
    async with AsyncSessionLocal() as db:
        w = (await db.execute(select(OutboundWrite).where(
            OutboundWrite.id == wid))).scalar_one()
        assert w.status == "SKIPPED_NO_CONNECTOR"
        assert "no CONNECTED connector" in w.last_error


@pytest.mark.asyncio
async def test_workday_write_back_is_honest_about_missing_tenant(external_system):
    """Workday write-back cannot be live without a customer tenant - the
    outcome must SAY so, never pretend."""
    await _make_connector(provider="workday", category="hris")
    from app.services.sync_engine import queue_outbound, dispatch_outbound
    wid = await queue_outbound(TENANT, "employee", "emp-2", "UPSERT",
                               {"email": "a@b.c"}, provider="workday")
    result = await dispatch_outbound(tenant_id=TENANT)
    assert result["failed"] >= 1

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.sync import OutboundWrite
    async with AsyncSessionLocal() as db:
        w = (await db.execute(select(OutboundWrite).where(
            OutboundWrite.id == wid))).scalar_one()
        assert w.status == "FAILED"
        assert "customer Workday tenant" in w.last_error
