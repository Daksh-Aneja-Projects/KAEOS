"""Notification delivery layer - REAL deliveries, no mocks.

Webhook + Slack channels deliver over real HTTP to a local http.server running
in a thread; assertions inspect what the server actually received (payload,
headers, HMAC signature). SMTP delivery is exercised against a real local SMTP
server (aiosmtpd) when that package is installed, and skipped honestly when not.
Channel CRUD + secret masking are covered via the API.
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

TENANT = "tenant_test_notify"


# ── A real local HTTP receiver ────────────────────────────────────────────────

class _Receiver(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _Receiver.received.append({
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # silence request logging
        pass


@pytest.fixture()
def http_receiver():
    _Receiver.received = []
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", _Receiver.received
    server.shutdown()
    thread.join(timeout=5)


@pytest_asyncio.fixture(autouse=True)
async def _notification_tables():
    """Create the notification tables on the APP engine (the one the notifier's
    AsyncSessionLocal uses) - the dual-engine trap: conftest's test engine and
    the app engine are different databases in the fast lane."""
    from sqlalchemy import text
    from app.core.database import engine as app_engine
    from app.models.notifications import NotificationChannel, NotificationDelivery
    async with app_engine.begin() as conn:
        await conn.run_sync(NotificationChannel.__table__.create, checkfirst=True)
        await conn.run_sync(NotificationDelivery.__table__.create, checkfirst=True)
        await conn.execute(text("DELETE FROM notification_channels"))
        await conn.execute(text("DELETE FROM notification_deliveries"))
    yield


@pytest_asyncio.fixture()
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _admin_headers(client) -> dict:
    # Mint a valid admin JWT directly (same pattern as test_rbac_coverage) -
    # no login round-trip needed in the ASGI harness.
    from app.services.auth import _create_token
    token = _create_token("u-admin-notify", "admin@kaeos.ai", "ADMIN", "tenant_acme")
    return {"Authorization": f"Bearer {token}"}


# ── Service-level: real webhook delivery with HMAC ────────────────────────────

@pytest.mark.asyncio
async def test_webhook_delivery_reaches_real_server_with_signature(http_receiver):
    url, received = http_receiver
    from app.core.database import AsyncSessionLocal
    from app.models.notifications import NotificationChannel
    from app.services.live_connectors import encrypt_secrets
    from app.services.notifier import notify

    async with AsyncSessionLocal() as db:
        db.add(NotificationChannel(
            tenant_id=TENANT, name="ops hook", kind="webhook",
            config_encrypted=encrypt_secrets({"url": f"{url}/hook", "secret": "s3cret"}),
            events=["hitl.pending"], enabled=True,
        ))
        await db.commit()

    result = await notify(TENANT, "hitl.pending", "Approval needed",
                          "A governed execution paused.", {"execution_id": "x1"})
    assert result["sent"] == 1 and result["failed"] == 0
    assert len(received) == 1
    req = received[0]
    assert req["path"] == "/hook"
    payload = json.loads(req["body"])
    assert payload["event"] == "hitl.pending"
    assert payload["data"]["execution_id"] == "x1"
    # HMAC signature is real and verifiable
    expected = hmac.new(b"s3cret", req["body"], hashlib.sha256).hexdigest()
    assert req["headers"].get("X-KAEOS-Signature") == expected

    # Delivery ledger recorded the send
    from sqlalchemy import select
    from app.models.notifications import NotificationDelivery
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(NotificationDelivery).where(
            NotificationDelivery.tenant_id == TENANT))).scalars().all()
        assert any(d.status == "SENT" and d.event == "hitl.pending" for d in rows)


@pytest.mark.asyncio
async def test_slack_channel_posts_text_payload(http_receiver):
    url, received = http_receiver
    from app.core.database import AsyncSessionLocal
    from app.models.notifications import NotificationChannel
    from app.services.live_connectors import encrypt_secrets
    from app.services.notifier import notify

    async with AsyncSessionLocal() as db:
        db.add(NotificationChannel(
            tenant_id=TENANT + "_slack", name="slack", kind="slack",
            config_encrypted=encrypt_secrets({"webhook_url": f"{url}/slack"}),
            events=[], enabled=True,   # empty events = subscribe to everything
        ))
        await db.commit()

    result = await notify(TENANT + "_slack", "sla.breach", "SLA escalation",
                          "Ticket sat too long.")
    assert result["sent"] == 1
    body = json.loads(received[-1]["body"])
    assert body["text"].startswith("*SLA escalation*")


@pytest.mark.asyncio
async def test_event_filter_and_failure_ledger(http_receiver):
    """A channel subscribed to other events is skipped; a dead URL is FAILED."""
    url, received = http_receiver
    from app.core.database import AsyncSessionLocal
    from app.models.notifications import NotificationChannel, NotificationDelivery
    from app.services.live_connectors import encrypt_secrets
    from app.services.notifier import notify
    from sqlalchemy import select

    t = TENANT + "_filter"
    async with AsyncSessionLocal() as db:
        db.add(NotificationChannel(     # subscribed to a DIFFERENT event
            tenant_id=t, name="other", kind="webhook",
            config_encrypted=encrypt_secrets({"url": f"{url}/other"}),
            events=["digest.weekly"], enabled=True,
        ))
        db.add(NotificationChannel(     # dead endpoint -> FAILED row
            tenant_id=t, name="dead", kind="webhook",
            config_encrypted=encrypt_secrets({"url": "http://127.0.0.1:9/nope"}),
            events=["hitl.pending"], enabled=True,
        ))
        await db.commit()

    result = await notify(t, "hitl.pending", "s", "b")
    assert result["sent"] == 0 and result["failed"] == 1
    assert not received            # the filtered channel was never called
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(NotificationDelivery).where(
            NotificationDelivery.tenant_id == t))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "FAILED" and rows[0].error


# ── Real SMTP (aiosmtpd) - skipped honestly when the package is absent ────────

@pytest.mark.asyncio
async def test_smtp_delivery_against_real_smtp_server():
    aiosmtpd = pytest.importorskip("aiosmtpd.controller",
                                   reason="aiosmtpd not installed")
    from aiosmtpd.controller import Controller

    class _Collector:
        messages = []

        async def handle_DATA(self, server, session, envelope):  # noqa: N802
            _Collector.messages.append(envelope)
            return "250 Message accepted"

    # aiosmtpd's readiness probe connects to the configured port, so port=0
    # (kernel-assigned) breaks it - allocate a free port explicitly instead.
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    controller = Controller(_Collector(), hostname="127.0.0.1", port=free_port)
    controller.start()
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.notifications import NotificationChannel
        from app.services.live_connectors import encrypt_secrets
        from app.services.notifier import notify

        t = TENANT + "_smtp"
        async with AsyncSessionLocal() as db:
            db.add(NotificationChannel(
                tenant_id=t, name="mail", kind="smtp",
                config_encrypted=encrypt_secrets({
                    "host": "127.0.0.1", "port": controller.port,
                    "use_tls": False, "from_addr": "kaeos@test.local",
                    "to_addrs": ["ops@test.local"],
                }),
                events=["mission.checkpoint"], enabled=True,
            ))
            await db.commit()

        result = await notify(t, "mission.checkpoint", "Mission paused",
                              "Approve step 2 in Mission Control.")
        assert result["sent"] == 1
        assert len(_Collector.messages) == 1
        env = _Collector.messages[0]
        assert env.mail_from == "kaeos@test.local"
        assert "ops@test.local" in env.rcpt_tos
        assert b"Mission paused" in env.content
    finally:
        controller.stop()


# ── API: CRUD + masking + validation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_channel_crud_and_secret_masking(client, http_receiver):
    url, received = http_receiver
    headers = await _admin_headers(client)

    resp = await client.post("/api/v1/notifications/channels", headers=headers, json={
        "name": "team hook", "kind": "webhook",
        "config": {"url": f"{url}/crud", "secret": "supersecretvalue"},
        "events": ["hitl.pending", "sla.breach"],
    })
    assert resp.status_code == 201, resp.text
    ch = resp.json()
    # secrets masked on read
    assert "supersecretvalue" not in json.dumps(ch)

    resp = await client.get("/api/v1/notifications/channels", headers=headers)
    assert resp.status_code == 200
    assert any(c["name"] == "team hook" for c in resp.json()["channels"])

    # real test-send through the API
    resp = await client.post(f"/api/v1/notifications/channels/{ch['id']}/test", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert any(r["path"] == "/crud" for r in received)

    # invalid kind and unknown event rejected
    resp = await client.post("/api/v1/notifications/channels", headers=headers, json={
        "name": "bad", "kind": "carrier_pigeon", "config": {}, "events": []})
    assert resp.status_code == 400
    resp = await client.post("/api/v1/notifications/channels", headers=headers, json={
        "name": "bad", "kind": "webhook", "config": {"url": "http://x"},
        "events": ["not.an.event"]})
    assert resp.status_code == 400

    # delete
    resp = await client.delete(f"/api/v1/notifications/channels/{ch['id']}", headers=headers)
    assert resp.status_code == 204
