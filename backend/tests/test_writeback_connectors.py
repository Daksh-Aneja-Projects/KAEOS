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
import re
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


class _HubSpot(BaseHTTPRequestHandler):
    """HubSpot CRM v3 stub: idempotent on a kaeos_idem property via /search."""
    posts: int = 0
    patches: int = 0
    idems: set = set()
    last_properties: dict = {}

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):  # noqa: N802
        body = self._read()
        if self.path.endswith("/search"):
            try:
                value = body["filterGroups"][0]["filters"][0]["value"]
            except (KeyError, IndexError):
                value = ""
            self._json({"results": [{"id": "701"}] if value in _HubSpot.idems else []})
            return
        _HubSpot.posts += 1
        props = body.get("properties", {})
        _HubSpot.last_properties = props
        if props.get("kaeos_idem"):
            _HubSpot.idems.add(props["kaeos_idem"])
        self._json({"id": "701", "properties": props}, code=201)

    def do_PATCH(self):  # noqa: N802
        _HubSpot.patches += 1
        _HubSpot.last_properties = self._read().get("properties", {})
        self._json({"id": "701"})

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


class _GitHub(BaseHTTPRequestHandler):
    """GitHub REST stub: idempotent on a [kaeos:<idem>] body marker via search."""
    posts: int = 0
    patches: int = 0
    comments: list = []
    markers: set = set()
    last_issue: dict = {}
    last_patch: dict = {}

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        items = [{"number": 7}] if any(m in q for m in _GitHub.markers) else []
        self._json({"total_count": len(items), "items": items})

    def do_POST(self):  # noqa: N802
        body = self._read()
        if self.path.endswith("/comments"):
            _GitHub.comments.append(body)
            self._json({"id": 1}, code=201)
            return
        _GitHub.posts += 1
        _GitHub.last_issue = body
        m = re.search(r"\[(kaeos:[^\]]+)\]", body.get("body", ""))
        if m:
            _GitHub.markers.add(m.group(1))
        self._json({"number": 7}, code=201)

    def do_PATCH(self):  # noqa: N802
        _GitHub.patches += 1
        _GitHub.last_patch = self._read()
        self._json({"number": 7})

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a):
        pass


class _PagerDuty(BaseHTTPRequestHandler):
    """PagerDuty REST v2 stub: idempotent on incident_key via GET /incidents."""
    posts: int = 0
    puts: int = 0
    keys: set = set()
    last_incident: dict = {}

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        key = parse_qs(urlparse(self.path).query).get("incident_key", [""])[0]
        self._json({"incidents": [{"id": "PD1"}] if key in _PagerDuty.keys else []})

    def do_POST(self):  # noqa: N802
        _PagerDuty.posts += 1
        inc = self._read().get("incident", {})
        _PagerDuty.last_incident = inc
        if inc.get("incident_key"):
            _PagerDuty.keys.add(inc["incident_key"])
        self._json({"incident": {"id": "PD1"}}, code=201)

    def do_PUT(self):  # noqa: N802
        _PagerDuty.puts += 1
        _PagerDuty.last_incident = self._read().get("incident", {})
        self._json({"incident": {"id": "PD1"}})

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


@pytest.mark.asyncio
async def test_hubspot_create_is_idempotent_on_kaeos_idem_property():
    server, url = _serve(_HubSpot)
    _HubSpot.posts = 0
    _HubSpot.patches = 0
    _HubSpot.idems = set()
    try:
        from app.services.sync_engine import _write_hubspot
        w = OutboundWrite(tenant_id=TENANT, entity_type="opportunity", internal_id="o1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"dealname": "Acme expansion", "amount": "5000"}})
        cfg = {"api_url": url}
        secrets = {"access_token": "hs"}

        assert await _write_hubspot(cfg, secrets, w, "idem-h") is None
        # The create stamped kaeos_idem AND captured the returned object id, so a
        # reprocess of the same row PATCHes by that id (durable idempotency)
        # rather than re-creating - no duplicate deal.
        assert await _write_hubspot(cfg, secrets, w, "idem-h") is None
        assert _HubSpot.posts == 1, "duplicate deal created on retry"
        assert _HubSpot.patches == 1, "retry must PATCH by captured id, not re-create"
        # The create stamped kaeos_idem (the dedup key relied on when a lost
        # response leaves external_id uncaptured and the retry must re-probe).
        assert "idem-h" in _HubSpot.idems, "create must stamp kaeos_idem for dedup"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_hubspot_missing_creds_is_honest_not_silent():
    from app.services.sync_engine import _write_hubspot
    w = OutboundWrite(tenant_id=TENANT, entity_type="opportunity", internal_id="o2",
                      op="UPSERT", external_id=None, payload={})
    err = await _write_hubspot({"api_url": "https://api.hubapi.com"}, {}, w, "x")
    assert err and "missing access_token" in err


@pytest.mark.asyncio
async def test_github_create_is_idempotent_on_body_marker():
    server, url = _serve(_GitHub)
    _GitHub.posts = 0
    _GitHub.markers = set()
    try:
        from app.services.sync_engine import _write_github
        w = OutboundWrite(tenant_id=TENANT, entity_type="issue", internal_id="g1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"title": "Fix login flake", "body": "Steps to repro"}})
        cfg = {"api_url": url, "owner": "acme", "repo": "app"}
        secrets = {"token": "gh"}

        assert await _write_github(cfg, secrets, w, "idem-g") is None
        assert await _write_github(cfg, secrets, w, "idem-g") is None
        assert _GitHub.posts == 1, "duplicate issue created on retry"
        assert _GitHub.last_issue.get("title") == "Fix login flake"
        assert "[kaeos:idem-g]" in _GitHub.last_issue.get("body", "")
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_github_missing_creds_is_honest_not_silent():
    from app.services.sync_engine import _write_github
    w = OutboundWrite(tenant_id=TENANT, entity_type="issue", internal_id="g2",
                      op="UPSERT", external_id=None, payload={})
    err = await _write_github({"owner": "acme", "repo": "app"}, {}, w, "x")
    assert err and "missing token" in err


@pytest.mark.asyncio
async def test_github_delete_closes_with_honest_comment():
    server, url = _serve(_GitHub)
    _GitHub.patches = 0
    _GitHub.comments = []
    try:
        from app.services.sync_engine import _write_github
        w = OutboundWrite(tenant_id=TENANT, entity_type="issue", internal_id="g3",
                          op="DELETE", external_id="7", payload={})
        err = await _write_github({"api_url": url, "owner": "acme", "repo": "app"},
                                  {"token": "gh"}, w, "idem-d")
        assert err is None
        assert _GitHub.patches == 1
        assert _GitHub.last_patch == {"state": "closed", "state_reason": "not_planned"}
        assert len(_GitHub.comments) == 1
        assert "closed as not planned" in _GitHub.comments[0]["body"]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_pagerduty_create_is_idempotent_on_incident_key():
    server, url = _serve(_PagerDuty)
    _PagerDuty.posts = 0
    _PagerDuty.keys = set()
    try:
        from app.services.sync_engine import _write_pagerduty
        w = OutboundWrite(tenant_id=TENANT, entity_type="incident", internal_id="p1",
                          op="UPSERT", external_id=None,
                          payload={"state": {"title": "DB latency spike", "urgency": "high"}})
        cfg = {"api_url": url, "service_id": "SVC1", "from_email": "ops@acme.com"}
        secrets = {"api_key": "pd"}

        assert await _write_pagerduty(cfg, secrets, w, "idem-p") is None
        assert await _write_pagerduty(cfg, secrets, w, "idem-p") is None
        assert _PagerDuty.posts == 1, "duplicate incident created on retry"
        assert _PagerDuty.last_incident.get("incident_key") == "idem-p"
        assert _PagerDuty.last_incident.get("title") == "DB latency spike"
        assert _PagerDuty.last_incident.get("service") == {"id": "SVC1",
                                                           "type": "service_reference"}
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_pagerduty_missing_creds_is_honest_not_silent():
    from app.services.sync_engine import _write_pagerduty
    w = OutboundWrite(tenant_id=TENANT, entity_type="incident", internal_id="p2",
                      op="UPSERT", external_id=None, payload={})
    err = await _write_pagerduty({"service_id": "SVC1"}, {}, w, "x")
    assert err and "missing api_key" in err


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


@pytest.mark.asyncio
async def test_dispatch_routes_to_hubspot_writer():
    server, url = _serve(_HubSpot)
    _HubSpot.posts = 0
    _HubSpot.idems = set()
    try:
        await _connector("hubspot", "crm", {"api_url": url}, {"access_token": "hs"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "opportunity", "o1", "UPSERT",
                                   {"dealname": "Routed"}, provider="hubspot")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert _HubSpot.posts == 1
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_dispatch_routes_to_github_writer():
    server, url = _serve(_GitHub)
    _GitHub.posts = 0
    _GitHub.markers = set()
    try:
        await _connector("github", "engineering",
                         {"api_url": url, "owner": "acme", "repo": "app"},
                         {"token": "gh"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "issue", "i1", "UPSERT",
                                   {"title": "Routed"}, provider="github")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert _GitHub.posts == 1
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_dispatch_routes_to_pagerduty_writer():
    server, url = _serve(_PagerDuty)
    _PagerDuty.posts = 0
    _PagerDuty.keys = set()
    try:
        await _connector("pagerduty", "engineering",
                         {"api_url": url, "service_id": "SVC1", "from_email": "ops@acme.com"},
                         {"api_key": "pd"})
        from app.services.sync_engine import queue_outbound, dispatch_outbound
        wid = await queue_outbound(TENANT, "incident", "n1", "UPSERT",
                                   {"title": "Routed"}, provider="pagerduty")
        result = await dispatch_outbound(tenant_id=TENANT)
        assert result["sent"] == 1 and result["failed"] == 0, result
        assert _PagerDuty.posts == 1
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            w = (await db.execute(select(OutboundWrite).where(
                OutboundWrite.id == wid))).scalar_one()
            assert w.status == "SENT"
    finally:
        server.shutdown()
