"""Write-back reliability: per-write isolation, dead-letter, external
idempotency, natural-key dedup, and the ServiceNow adapter - all REAL, no mocks.

The sync engine reads/writes through AsyncSessionLocal (the APP engine), not the
conftest test engine, so the fixture creates the tables it touches on the app
engine (the dual-engine trap the existing sync tests document).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import pytest_asyncio
from sqlalchemy import select

TENANT = "tenant_wb_test"


class _Sink(BaseHTTPRequestHandler):
    """A live external system: records POSTs (with headers) and 200s them."""
    received: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        _Sink.received.append({
            "path": self.path,
            "idempotency_key": self.headers.get("Idempotency-Key"),
            "body": json.loads(self.rfile.read(length) or b"{}"),
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a):
        pass


class _ServiceNow(BaseHTTPRequestHandler):
    """A live ServiceNow Table API stand-in: idempotent on correlation_id."""
    posts: int = 0
    store: dict = {}   # correlation_id -> sys_id

    def _read(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):  # noqa: N802
        # correlation_id probe: /api/now/table/incident?sysparm_query=correlation_id=<k>
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query).get("sysparm_query", [""])[0]
        result = []
        if q.startswith("correlation_id="):
            key = q.split("=", 1)[1]
            if key in _ServiceNow.store:
                result = [{"sys_id": _ServiceNow.store[key]}]
        self._respond({"result": result})

    def do_POST(self):  # noqa: N802
        body = self._read()
        _ServiceNow.posts += 1
        corr = body.get("correlation_id")
        sys_id = f"sysid_{_ServiceNow.posts}"
        if corr:
            _ServiceNow.store[corr] = sys_id
        self._respond({"result": {"sys_id": sys_id}}, code=201)

    def _respond(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture(autouse=True)
async def _tables():
    from sqlalchemy import text
    from app.core.database import engine as app_engine
    from app.models.sync import SyncLedger, OutboundWrite
    from app.models.domain import Connector, ConnectorCredential, Signal
    async with app_engine.begin() as conn:
        for model in (Connector, ConnectorCredential, SyncLedger, OutboundWrite, Signal):
            await conn.run_sync(model.__table__.create, checkfirst=True)
        for tbl in ("sync_ledger", "outbound_writes", "connector_credentials",
                    "connectors", "signals"):
            await conn.execute(text(f"DELETE FROM {tbl}"))
    yield


async def _connector(provider, category="itsm", config=None, secrets=None) -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import encrypt_secrets
    async with AsyncSessionLocal() as db:
        c = Connector(tenant_id=TENANT, name=f"{provider} conn",
                      category=category, connector_type="API", status="CONNECTED")
        db.add(c)
        await db.flush()
        db.add(ConnectorCredential(
            connector_id=c.id, tenant_id=TENANT, provider=provider,
            config=config or {}, secrets_encrypted=encrypt_secrets(secrets or {})))
        await db.commit()
        return c.id


# ── CRIT: per-write isolation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_dead_endpoint_does_not_stall_the_batch():
    """The head-of-line-blocking CRIT: a write to a dead endpoint must fail ONLY
    itself; a healthy sibling write in the same batch still gets delivered."""
    server, url = _serve(_Sink)
    _Sink.received = []
    try:
        # Poison connector: provider match forces this dead target for the poison write.
        await _connector("generic_rest", category="dead",
                         config={"base_url": "http://127.0.0.1:1"})
        # Healthy connector for the sibling write.
        await _connector("generic_rest", category="hris", config={"base_url": url},
                         secrets={"api_key": "k"})

        from app.services.sync_engine import queue_outbound, dispatch_outbound
        poison = await queue_outbound(TENANT, "employee", "p1", "UPSERT", {"x": 1},
                                      external_id="POISON")
        good = await queue_outbound(TENANT, "employee", "g1", "UPSERT", {"x": 2},
                                    external_id="GOOD")
        # Route the poison write to the dead connector explicitly by category so
        # both writes are in one batch but hit different targets.
        from app.core.database import AsyncSessionLocal
        from app.models.sync import OutboundWrite
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == poison))).scalar_one()
            p.category = "dead"
            g = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == good))).scalar_one()
            g.category = "hris"
            await db.commit()

        result = await dispatch_outbound(tenant_id=TENANT)
        # The healthy write went through despite the poison one raising.
        assert result["sent"] == 1, result
        assert len(_Sink.received) == 1
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == poison))).scalar_one()
            g = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == good))).scalar_one()
            assert g.status == "SENT"
            assert p.status == "FAILED" and p.attempts == 1
    finally:
        server.shutdown()


# ── Dead-letter terminal state ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_dead_letters_after_max_attempts():
    from app.services.sync_engine import queue_outbound, dispatch_outbound, MAX_ATTEMPTS
    from app.core.database import AsyncSessionLocal
    from app.models.sync import OutboundWrite

    await _connector("generic_rest", category="hris",
                     config={"base_url": "http://127.0.0.1:1"})
    wid = await queue_outbound(TENANT, "employee", "d1", "UPSERT", {"x": 1},
                               external_id="DEADME")
    for _ in range(MAX_ATTEMPTS):
        await dispatch_outbound(tenant_id=TENANT)

    async with AsyncSessionLocal() as db:
        w = (await db.execute(select(OutboundWrite).where(
            OutboundWrite.id == wid))).scalar_one()
        assert w.attempts == MAX_ATTEMPTS
        assert w.status == "DEAD", w.status
        assert "DEAD after" in (w.last_error or "")

    # A DEAD row is terminal: another dispatch never touches it again.
    res = await dispatch_outbound(tenant_id=TENANT)
    assert res["sent"] == 0 and res["failed"] == 0 and res["dead"] == 0
    async with AsyncSessionLocal() as db:
        w = (await db.execute(select(OutboundWrite).where(
            OutboundWrite.id == wid))).scalar_one()
        assert w.attempts == MAX_ATTEMPTS   # untouched


# ── External idempotency token ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generic_rest_carries_stable_idempotency_key():
    server, url = _serve(_Sink)
    _Sink.received = []
    try:
        await _connector("generic_rest", category="hris", config={"base_url": url})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "employee", "i1", "UPSERT", {"x": 1},
                                   external_id="IDEM", idempotency_key="fixed-token-123")
        await dispatch_outbound(tenant_id=TENANT)
        assert len(_Sink.received) == 1
        assert _Sink.received[0]["idempotency_key"] == "fixed-token-123"
    finally:
        server.shutdown()


# ── ServiceNow adapter: idempotent create ────────────────────────────────────

@pytest.mark.asyncio
async def test_servicenow_create_is_idempotent_on_lost_response():
    """A create whose HTTP response was lost is retried with the SAME token; the
    correlation_id probe finds the existing record and does NOT create a second."""
    server, url = _serve(_ServiceNow)
    _ServiceNow.posts = 0
    _ServiceNow.store = {}
    try:
        from app.services.sync_engine import _write_servicenow
        from app.models.sync import OutboundWrite

        w = OutboundWrite(tenant_id=TENANT, entity_type="incident", internal_id="a1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"short_description": "disk full"}})
        cfg = {"instance_url": url}
        secrets = {"username": "admin", "password": "pw"}

        err1 = await _write_servicenow(cfg, secrets, w, "tok-1")
        assert err1 is None
        # Retry with the same token (simulating a lost response on attempt 1).
        err2 = await _write_servicenow(cfg, secrets, w, "tok-1")
        assert err2 is None
        assert _ServiceNow.posts == 1, "duplicate incident created on retry"
    finally:
        server.shutdown()


# ── Natural-key dedup on pulls ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resync_upserts_signals_no_duplicates():
    from app.core.database import AsyncSessionLocal
    from app.services.live_connectors import LiveConnectorService
    from app.models.domain import Signal

    records = [
        {"entity": "incident", "external_id": "INC-1", "summary": "one",
         "domain": "operations", "authority": 0.9},
        {"entity": "incident", "external_id": "INC-2", "summary": "two",
         "domain": "operations", "authority": 0.9},
    ]
    # First sync inserts 2.
    async with AsyncSessionLocal() as db:
        sigs = LiveConnectorService.records_to_signals(records, TENANT, "ServiceNow")
        s1 = await LiveConnectorService.persist_signals(db, sigs)
        await db.commit()
    assert s1 == {"inserted": 2, "updated": 0}

    # Re-sync the SAME two records (one with new text) -> updates, no new rows.
    records[0]["summary"] = "one-updated"
    async with AsyncSessionLocal() as db:
        sigs = LiveConnectorService.records_to_signals(records, TENANT, "ServiceNow")
        s2 = await LiveConnectorService.persist_signals(db, sigs)
        await db.commit()
    assert s2 == {"inserted": 0, "updated": 2}, s2

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Signal).where(
            Signal.tenant_id == TENANT, Signal.source_type == "servicenow"))).scalars().all()
        assert len(rows) == 2
        assert any(r.clean_payload == "one-updated" for r in rows)
