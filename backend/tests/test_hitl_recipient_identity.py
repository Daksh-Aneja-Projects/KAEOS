"""§17 HIGH-1 — per-recipient approval-link identity.

The emailed one-click approval link must carry the REAL recipient's identity as
its token subject (not the non-attributable 'email-approver' constant), so the
SOX four-eyes check can compare a real approver against the maker. This proves
the HITL notifier resolves the configured SMTP recipient and threads it through
to approval_links, and that a tenant with no resolvable recipient falls back to
the fail-closed constant.
"""
import jwt
import pytest

from app.api.routes.approvals import _AUD, _ALG, _get_secret_key
from app.services.hitl_manager import HITLManager


def _sub_of(approve_url: str) -> str:
    token = approve_url.split("token=", 1)[1]
    return jwt.decode(token, _get_secret_key(), algorithms=[_ALG], audience=_AUD)["sub"]


@pytest.mark.asyncio
async def test_link_subject_is_the_configured_recipient(monkeypatch):
    from app.core.database import AsyncSessionLocal, init_db
    from app.models.notifications import NotificationChannel
    from app.services.live_connectors import encrypt_secrets

    await init_db()  # create all tables (activity feed, skill executions, channels)

    tenant = "tenant_recip_identity"
    recipient = "cfo.approver@corp.com"
    async with AsyncSessionLocal() as db:
        db.add(NotificationChannel(
            tenant_id=tenant, name="approvers", kind="smtp",
            config_encrypted=encrypt_secrets(
                {"host": "127.0.0.1", "port": 25, "use_tls": False,
                 "from_addr": "kaeos@corp.com", "to_addrs": [recipient]}),
            events=["hitl.pending"], enabled=True,
        ))
        await db.commit()

    mgr = HITLManager()
    # Force the in-memory HITL store so the test needs no Redis.
    async def _no_redis():
        return None
    monkeypatch.setattr(mgr, "_get_redis", _no_redis)

    # Capture the emitted notifications instead of delivering them.
    captured = []
    import app.services.notifier as notifier

    def _capture(tenant_id, event, subject, body, data=None, to_override=None):
        captured.append({"to_override": to_override, "data": data})
    monkeypatch.setattr(notifier, "notify_fire_and_forget", _capture)

    await mgr.request_human_confirmation(
        {"skill_id": "vendor_payment_approval", "department": "finance"},
        {"execution_id": "exec-recip-1", "tenant_id": tenant},
    )

    assert captured, "no notification was emitted"
    note = next(n for n in captured if n["to_override"] == [recipient])
    approve_url = note["data"]["approval_links"]["approve"]
    sub = _sub_of(approve_url)
    assert sub == recipient, f"token subject {sub!r} is not the real recipient"
    assert sub != "email-approver"


@pytest.mark.asyncio
async def test_falls_back_to_fail_closed_constant_when_no_recipient(monkeypatch):
    from app.core.database import init_db
    await init_db()

    mgr = HITLManager()

    async def _no_redis():
        return None
    monkeypatch.setattr(mgr, "_get_redis", _no_redis)

    # A tenant with no configured SMTP recipient resolves to [].
    async def _none(_tenant):
        return []
    monkeypatch.setattr(mgr, "_resolve_notification_recipients", _none)

    captured = []
    import app.services.notifier as notifier
    monkeypatch.setattr(
        notifier, "notify_fire_and_forget",
        lambda *a, **k: captured.append(k),
    )

    await mgr.request_human_confirmation(
        {"skill_id": "vendor_payment_approval", "department": "finance"},
        {"execution_id": "exec-recip-2", "tenant_id": "tenant_no_recip"},
    )

    assert captured and captured[0].get("to_override") is None
    approve_url = captured[0]["data"]["approval_links"]["approve"]
    assert _sub_of(approve_url) == "email-approver"  # fail-closed → SoD blocks


if __name__ == "__main__":
    import asyncio

    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    asyncio.run(test_falls_back_to_fail_closed_constant_when_no_recipient(_MP()))
    print("fail-closed fallback OK")
