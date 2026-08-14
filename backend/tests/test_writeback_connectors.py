"""Write-back adapters for Zendesk, Jira, and Slack - REAL, no mocks.

Each writer is exercised against a live local HTTP stub standing in for the
vendor API, so the SSRF-pinned guarded_async_client, the real REST paths/payload
shapes, and the idempotency probes all run for real. A dispatch_outbound test
per provider proves the provider is registered and routes through
_write_via_adapter (the "register them so they dispatch" contract).

Dual-engine trap (documented by the existing sync tests): the engine reads/writes
through AsyncSessionLocal (the APP engine), not the conftest test engine, so the
fixture creates the tables it touches on the app engine.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.sync import OutboundWrite

TENANT = "tenant_wbc_test"


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ── Vendor stubs ──────────────────────────────────────────────────────────────

class _Zendesk(BaseHTTPRequestHandler):
    """Zendesk Ticketing stub: idempotent on the ticket external_id field."""
    posts: int = 0
    puts: int = 0
    deletes: int = 0
    store: set = set()          # external_id values seen on create
    last_ticket: dict = {}

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        q = parse_qs(urlparse(self.path).query).get("query", [""])[0]
        results = []
        # query looks like: type:ticket external_id:<idem>
        for tok in q.split():
            if tok.startswith("external_id:") and tok.split(":", 1)[1] in _Zendesk.store:
                results = [{"id": 999}]
        self._json({"results": results})

    def do_POST(self):  # noqa: N802
        body = self._read()
        _Zendesk.posts += 1
        _Zendesk.last_ticket = body.get("ticket", {})
        ext = _Zendesk.last_ticket.get("external_id")
        if ext:
            _Zendesk.store.add(ext)
        self._json({"ticket": {"id": 4242, "external_id": ext}}, code=201)

    def do_PUT(self):  # noqa: N802
        _Zendesk.puts += 1
        _Zendesk.last_ticket = self._read().get("ticket", {})
        self._json({"ticket": {"id": 4242}})

    def do_DELETE(self):  # noqa: N802
        _Zendesk.deletes += 1
        self.send_response(204)
        self.end_headers()

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


class _Jira(BaseHTTPRequestHandler):
    """Jira Cloud stub: idempotent on a kaeos-<idem> label."""
    posts: int = 0
    puts: int = 0
    labels: set = set()
    last_fields: dict = {}

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        jql = parse_qs(urlparse(self.path).query).get("jql", [""])[0]
        issues = []
        # jql looks like: labels = "kaeos-<idem>"
        for lab in _Jira.labels:
            if lab in jql:
                issues = [{"key": "PROJ-1"}]
        self._json({"issues": issues})

    def do_POST(self):  # noqa: N802
        _Jira.posts += 1
        _Jira.last_fields = self._read().get("fields", {})
        for lab in _Jira.last_fields.get("labels", []):
            _Jira.labels.add(lab)
        self._json({"key": "PROJ-42", "id": "10042"}, code=201)

    def do_PUT(self):  # noqa: N802
        _Jira.puts += 1
        _Jira.last_fields = self._read().get("fields", {})
        self.send_response(204)
        self.end_headers()

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


class _Slack(BaseHTTPRequestHandler):
    """Slack Web API stub. Returns HTTP 200 with ok:false for a bad channel,
    exactly like the real API."""
    posts: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Slack.posts.append(body)
        if body.get("channel") == "BAD":
            self._json({"ok": False, "error": "channel_not_found"})
        else:
            self._json({"ok": True, "ts": "1700000000.000100"})

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


# ── Direct writer tests (idempotency + payload shape + honest errors) ─────────

@pytest.mark.asyncio
async def test_zendesk_create_is_idempotent_on_lost_response():
    server, url = _serve(_Zendesk)
    _Zendesk.posts = 0
    _Zendesk.store = set()
    try:
        from app.services.sync_engine import _write_zendesk
        w = OutboundWrite(tenant_id=TENANT, entity_type="ticket", internal_id="t1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"subject": "Reset password", "priority": "high"}})
        cfg = {"subdomain_url": url}
        secrets = {"email": "agent@acme.com", "api_token": "zt"}

        assert await _write_zendesk(cfg, secrets, w, "idem-1") is None
        # Retry with the SAME token (lost response on attempt 1) -> no duplicate.
        assert await _write_zendesk(cfg, secrets, w, "idem-1") is None
        assert _Zendesk.posts == 1, "duplicate ticket created on retry"
        assert _Zendesk.last_ticket.get("subject") == "Reset password"
        assert _Zendesk.last_ticket.get("external_id") == "idem-1"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_zendesk_update_targets_existing_ticket_by_id():
    server, url = _serve(_Zendesk)
    _Zendesk.posts = _Zendesk.puts = 0
    try:
        from app.services.sync_engine import _write_zendesk
        w = OutboundWrite(tenant_id=TENANT, entity_type="ticket", internal_id="t2",
                          op="UPSERT", external_id="4242",
                          payload={"state": {"status": "solved"}})
        err = await _write_zendesk({"subdomain_url": url},
                                   {"email": "a@b.c", "api_token": "zt"}, w, "idem-2")
        assert err is None
        assert _Zendesk.puts == 1 and _Zendesk.posts == 0
        assert _Zendesk.last_ticket.get("status") == "solved"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_zendesk_missing_creds_is_honest_not_silent():
    from app.services.sync_engine import _write_zendesk
    w = OutboundWrite(tenant_id=TENANT, entity_type="ticket", internal_id="t3",
                      op="UPSERT", external_id=None, payload={})
    err = await _write_zendesk({"subdomain_url": "https://acme.zendesk.com"}, {}, w, "x")
    assert err and "missing email/api_token" in err


@pytest.mark.asyncio
async def test_jira_create_is_idempotent_on_label():
    server, url = _serve(_Jira)
    _Jira.posts = 0
    _Jira.labels = set()
    try:
        from app.services.sync_engine import _write_jira
        w = OutboundWrite(tenant_id=TENANT, entity_type="issue", internal_id="i1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"summary": "Fix flaky test"}})
        cfg = {"base_url": url, "project_key": "PROJ", "issue_type": "Task"}
        secrets = {"email": "dev@acme.com", "api_token": "jt"}

        assert await _write_jira(cfg, secrets, w, "idem-j") is None
        assert await _write_jira(cfg, secrets, w, "idem-j") is None
        assert _Jira.posts == 1, "duplicate issue created on retry"
        # project/issuetype defaults folded in; idem label carried.
        assert _Jira.last_fields.get("project") == {"key": "PROJ"}
        assert _Jira.last_fields.get("issuetype") == {"name": "Task"}
        assert "kaeos-idem-j" in _Jira.last_fields.get("labels", [])
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_jira_update_by_key():
    server, url = _serve(_Jira)
    _Jira.posts = _Jira.puts = 0
    try:
        from app.services.sync_engine import _write_jira
        w = OutboundWrite(tenant_id=TENANT, entity_type="issue", internal_id="i2",
                          op="UPSERT", external_id="PROJ-7",
                          payload={"state": {"summary": "Renamed"}})
        err = await _write_jira({"base_url": url},
                                {"email": "a@b.c", "api_token": "jt"}, w, "idem-x")
        assert err is None
        assert _Jira.puts == 1 and _Jira.posts == 0
        assert _Jira.last_fields.get("summary") == "Renamed"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_slack_posts_message_and_carries_idem_metadata():
    server, url = _serve(_Slack)
    _Slack.posts = []
    try:
        from app.services.sync_engine import _write_slack
        w = OutboundWrite(tenant_id=TENANT, entity_type="message", internal_id="m1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"text": "Deploy approved"}})
        err = await _write_slack({"api_url": url, "channel_id": "C123"},
                                 {"bot_token": "xoxb-1"}, w, "idem-s")
        assert err is None
        assert len(_Slack.posts) == 1
        sent = _Slack.posts[0]
        assert sent["channel"] == "C123" and sent["text"] == "Deploy approved"
        assert sent["metadata"]["event_payload"]["idempotency_key"] == "idem-s"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_slack_ok_false_is_a_failure_not_silent_success():
    server, url = _serve(_Slack)
    _Slack.posts = []
    try:
        from app.services.sync_engine import _write_slack
        w = OutboundWrite(tenant_id=TENANT, entity_type="message", internal_id="m2",
                          op="UPSERT", external_id=None,
                          payload={"state": {"text": "hi", "channel": "BAD"}})
        err = await _write_slack({"api_url": url}, {"bot_token": "xoxb-1"}, w, "idem-b")
        assert err and "channel_not_found" in err
    finally:
        server.shutdown()


# ── Registration: each provider dispatches through dispatch_outbound ──────────

@pytest_asyncio.fixture(autouse=True)
async def _tables():
    from sqlalchemy import text
    from app.core.database import engine as app_engine
    from app.models.sync import SyncLedger, OutboundWrite as _OW
    from app.models.domain import Connector, ConnectorCredential
    async with app_engine.begin() as conn:
        for model in (Connector, ConnectorCredential, SyncLedger, _OW):
            await conn.run_sync(model.__table__.create, checkfirst=True)
        for tbl in ("sync_ledger", "outbound_writes", "connector_credentials", "connectors"):
            await conn.execute(text(f"DELETE FROM {tbl}"))
    yield


async def _connector(provider, category, config, secrets) -> str:
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
            config=config, secrets_encrypted=encrypt_secrets(secrets)))
        await db.commit()
        return c.id


@pytest.mark.asyncio
async def test_dispatch_routes_to_zendesk_writer():
    server, url = _serve(_Zendesk)
    _Zendesk.posts = 0
    _Zendesk.store = set()
    try:
        await _connector("zendesk", "support", {"subdomain_url": url},
                         {"email": "a@b.c", "api_token": "zt"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "ticket", "t1", "UPSERT",
                                   {"subject": "Routed"}, provider="zendesk")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert _Zendesk.posts == 1
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_dispatch_routes_to_jira_writer():
    server, url = _serve(_Jira)
    _Jira.posts = 0
    _Jira.labels = set()
    try:
        await _connector("jira", "engineering",
                         {"base_url": url, "project_key": "PROJ", "issue_type": "Task"},
                         {"email": "a@b.c", "api_token": "jt"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "issue", "i1", "UPSERT",
                                   {"summary": "Routed"}, provider="jira")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert _Jira.posts == 1
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_dispatch_routes_to_slack_writer():
    server, url = _serve(_Slack)
    _Slack.posts = []
    try:
        await _connector("slack", "collaboration",
                         {"api_url": url, "channel_id": "C999"},
                         {"bot_token": "xoxb-1"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "message", "m1", "UPSERT",
                                   {"text": "Routed"}, provider="slack")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert len(_Slack.posts) == 1 and _Slack.posts[0]["text"] == "Routed"
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()
