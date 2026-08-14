"""KAEOS - outbound notification delivery (SMTP / Slack / generic webhook).

The one place platform events become messages that reach humans where they
live. Fire-and-forget by design: a failed delivery is recorded in the
NotificationDelivery ledger and logged, but NEVER raises into the calling
business path - a broken mail server must not block a governed execution.

Channels are tenant-configured rows (see app/models/notifications.py); their
config is Fernet-encrypted with the same KDF as connector credentials.

Usage from business code:

    from app.services.notifier import notify_fire_and_forget
    notify_fire_and_forget(tenant_id, "hitl.pending",
                           subject="Approval needed: vendor_payment_approval",
                           body="...", data={"execution_id": ...})
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from app.models.notifications import NotificationChannel, NotificationDelivery
from app.services.live_connectors import decrypt_secrets

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0
SMTP_TIMEOUT = 15.0


# ── Channel senders (each returns None on success, raises on failure) ─────────

def _send_smtp_sync(cfg: Dict[str, Any], subject: str, body: str,
                    to_override: Optional[List[str]] = None) -> None:
    """Blocking SMTP send - run via asyncio.to_thread."""
    host = cfg["host"]
    port = int(cfg.get("port") or 587)
    username = cfg.get("username") or ""
    password = cfg.get("password") or ""
    use_tls = bool(cfg.get("use_tls", True))
    from_addr = cfg.get("from_addr") or username or "kaeos@localhost"
    to_addrs = to_override or cfg.get("to_addrs") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    if not to_addrs:
        raise ValueError("smtp channel has no recipients (to_addrs)")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as server:
        if use_tls:
            try:
                server.starttls()
            except smtplib.SMTPNotSupportedError:
                # Local/dev relays often speak plain SMTP; the config asked for
                # TLS but the server cannot - proceed unencrypted rather than
                # silently dropping the message, and log loudly.
                logger.warning("[Notifier] SMTP server %s does not support STARTTLS", host)
        if username and password:
            server.login(username, password)
        server.sendmail(from_addr, to_addrs, msg.as_string())


async def _send_slack(cfg: Dict[str, Any], subject: str, body: str) -> None:
    from app.core.outbound import guarded_async_client
    url = cfg["webhook_url"]
    payload = {"text": f"*{subject}*\n{body}"}
    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def _send_webhook(cfg: Dict[str, Any], event: str, subject: str,
                        body: str, data: Optional[Dict[str, Any]]) -> None:
    url = cfg["url"]
    payload = {"event": event, "subject": subject, "body": body, "data": data or {}}
    raw = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json", "X-KAEOS-Event": event}
    secret = cfg.get("secret")
    if secret:
        headers["X-KAEOS-Signature"] = hmac.new(
            str(secret).encode(), raw, hashlib.sha256).hexdigest()
    from app.core.outbound import guarded_async_client
    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(url, content=raw, headers=headers)
        resp.raise_for_status()


# ── Core dispatch ─────────────────────────────────────────────────────────────

async def _deliver_one(channel: NotificationChannel, event: str, subject: str,
                       body: str, data: Optional[Dict[str, Any]],
                       to_override: Optional[List[str]]) -> Optional[str]:
    """Deliver to one channel. Returns None on success, the error string on failure."""
    try:
        cfg = decrypt_secrets(channel.config_encrypted)
    except Exception as e:
        return f"config decrypt failed: {e}"
    try:
        if channel.kind == "smtp":
            await asyncio.to_thread(_send_smtp_sync, cfg, subject, body, to_override)
        elif channel.kind == "slack":
            await _send_slack(cfg, subject, body)
        elif channel.kind == "webhook":
            await _send_webhook(cfg, event, subject, body, data)
        else:
            return f"unknown channel kind '{channel.kind}'"
        return None
    except Exception as e:
        return str(e)[:900]


async def notify(tenant_id: str, event: str, subject: str, body: str,
                 data: Optional[Dict[str, Any]] = None,
                 to_override: Optional[List[str]] = None) -> Dict[str, int]:
    """Deliver `event` to every enabled subscribed channel of the tenant.

    Records a NotificationDelivery row per attempt. Never raises: failures are
    counted and logged. Returns {"sent": n, "failed": m}.
    """
    from app.core.database import AsyncSessionLocal

    sent = failed = 0
    try:
        async with AsyncSessionLocal() as db:
            channels = (await db.execute(
                select(NotificationChannel).where(
                    NotificationChannel.tenant_id == tenant_id,
                    NotificationChannel.enabled.is_(True),
                )
            )).scalars().all()

            targets = [c for c in channels if not (c.events or []) or event in (c.events or [])]
            for ch in targets:
                error = await _deliver_one(ch, event, subject, body, data, to_override)
                db.add(NotificationDelivery(
                    tenant_id=tenant_id, channel_id=ch.id, event=event,
                    subject=subject[:256],
                    status="SENT" if error is None else "FAILED",
                    error=error,
                ))
                if error is None:
                    sent += 1
                else:
                    failed += 1
                    logger.warning("[Notifier] delivery failed (%s/%s): %s",
                                   ch.kind, ch.name, error)
            await db.commit()
    except Exception as e:
        # The notifier must never take a business path down with it.
        logger.error("[Notifier] notify() error for %s/%s: %s", tenant_id, event, e)
    return {"sent": sent, "failed": failed}


def notify_fire_and_forget(tenant_id: str, event: str, subject: str, body: str,
                           data: Optional[Dict[str, Any]] = None,
                           to_override: Optional[List[str]] = None) -> None:
    """Schedule a notify() without awaiting it (safe inside request handlers).

    Falls back to a synchronous best-effort run when no loop is running (e.g.
    called from a script).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    coro = notify(tenant_id, event, subject, body, data, to_override)
    if loop is not None:
        task = loop.create_task(coro)
        # keep a reference so the task is not garbage-collected mid-flight
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    else:
        try:
            asyncio.run(coro)
        except Exception as e:
            logger.error("[Notifier] sync fallback failed: %s", e)


_BACKGROUND_TASKS: set = set()
