"""Approver-by-link + executive digest - real flows, no mocks.

Approval links: a signed single-purpose token resolves a REAL pending HITL
record without a session; it cannot be replayed, tampered into the other
decision, or used after the approval is gone.

Digest: built from real ledgers and delivered through a real webhook channel
served by a local HTTP server.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import init_db

TENANT = "tenant_approval_test"


class _Sink(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        _Sink.received.append(json.loads(self.rfile.read(n) or b"{}"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture()
def sink():
    _Sink.received = []
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", _Sink.received
    server.shutdown()


@pytest.fixture(autouse=True)
async def _tables():
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


class _MemHITL:
    """The real HITLManager with Redis forced off (memory store)."""
    def __new__(cls):
        from app.services.hitl_manager import HITLManager
        mgr = HITLManager()
        mgr._memory = {}

        async def _no_redis():
            return None
        mgr._get_redis = _no_redis
        return mgr


@pytest.mark.asyncio
async def test_approval_link_resolves_real_pending_approval(client, monkeypatch):
    from app.services.hitl_manager import hitl_manager
    from app.api.routes.approvals import approval_links

    async def _no_redis():
        return None
    monkeypatch.setattr(hitl_manager, "_get_redis", _no_redis)
    hitl_manager._memory = {}

    exec_id = "exec-approval-link-1"
    await hitl_manager.request_human_confirmation(
        {"skill_id": "vendor_payment_approval", "steps": [], "department": "finance"},
        {"execution_id": exec_id, "tenant_id": TENANT})

    links = approval_links(exec_id, TENANT, "http://test")
    # the approve link decides it, with NO session
    path = links["approve"].replace("http://test", "")
    resp = await client.get(path)
    assert resp.status_code == 200
    assert "Approved" in resp.text

    status = await hitl_manager.get_hitl_status(exec_id, tenant_id=TENANT)
    assert status["status"] == "RESOLVED" and status["decision"] is True

    # replay after resolution is refused (not silently re-applied)
    resp = await client.get(path)
    assert resp.status_code == 400
    assert "no longer pending" in resp.text


@pytest.mark.asyncio
async def test_reject_link_and_tampered_tokens(client, monkeypatch):
    from app.services.hitl_manager import hitl_manager
    from app.api.routes.approvals import approval_links

    async def _no_redis():
        return None
    monkeypatch.setattr(hitl_manager, "_get_redis", _no_redis)
    hitl_manager._memory = {}

    exec_id = "exec-approval-link-2"
    await hitl_manager.request_human_confirmation(
        {"skill_id": "enterprise_discount_approval", "steps": [], "department": "sales"},
        {"execution_id": exec_id, "tenant_id": TENANT})

    links = approval_links(exec_id, TENANT, "http://test")
    resp = await client.get(links["reject"].replace("http://test", ""))
    assert resp.status_code == 200 and "Rejected" in resp.text
    status = await hitl_manager.get_hitl_status(exec_id, tenant_id=TENANT)
    assert status["decision"] is False

    # a garbage / tampered token is refused
    resp = await client.get("/api/v1/approvals/decide?token=not-a-real-token")
    assert resp.status_code == 400 and "not valid" in resp.text


@pytest.mark.asyncio
async def test_expired_link_is_refused(client):
    """A token past its expiry cannot decide anything."""
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.services.auth import _get_secret_key
    now = datetime.now(timezone.utc)
    stale = jwt.encode({
        "execution_id": "whatever", "tenant_id": TENANT, "approved": True,
        "approver": "x", "aud": "kaeos-approval",
        "iat": now - timedelta(days=30), "exp": now - timedelta(days=1),
    }, _get_secret_key(), algorithm="HS256")
    resp = await client.get(f"/api/v1/approvals/decide?token={stale}")
    assert resp.status_code == 400 and "expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_digest_builds_from_real_data_and_delivers(sink):
    """The digest reports real ledger numbers and reaches a real endpoint."""
    url, received = sink
    from app.core.database import AsyncSessionLocal
    from app.models.notifications import NotificationChannel
    from app.services.live_connectors import encrypt_secrets
    from app.services.digest import build_digest, render_digest, send_weekly_digest

    async with AsyncSessionLocal() as db:
        db.add(NotificationChannel(
            tenant_id=TENANT, name="exec digest", kind="webhook",
            config_encrypted=encrypt_secrets({"url": f"{url}/digest"}),
            events=["digest.weekly"], enabled=True))
        await db.commit()

    payload = await build_digest(TENANT, days=7)
    # every key present, and honest when there is no data
    assert payload["window_days"] == 7
    assert "safe_autonomy_rate" in payload
    assert isinstance(payload["pending_approvals"], int)
    text = render_digest(payload)
    assert "KAEOS executive digest" in text
    assert "Safe-autonomy-rate:" in text

    result = await send_weekly_digest(tenant_id=TENANT, days=7)
    assert result["sent"] == 1 and result["failed"] == 0
    assert len(received) == 1
    assert received[0]["event"] == "digest.weekly"
    assert "Safe-autonomy-rate" in received[0]["body"]
