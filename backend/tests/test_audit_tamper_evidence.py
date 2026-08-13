"""Tamper-evident SecurityAuditLog (review theme E/J).

Every audit row is HMAC-signed at write time (edits detectable); windowed
checkpoints anchored into the signed provenance ledger surface deletions.
The old log was best-effort-and-silent: unsigned rows, swallowed failures,
no way to prove the trail had not been rewritten.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select, update

from app.core.audit import (
    checkpoint_audit_log,
    record_security_event,
    verify_audit_checkpoint,
    verify_audit_rows,
)
from app.core.database import AsyncSessionLocal
from app.models.domain import SecurityAuditLog


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    from app.core.database import init_db
    asyncio.run(init_db())


def _t():
    return f"tenant_aud_{uuid.uuid4().hex[:6]}"


async def _emit(tenant, n=3):
    for i in range(n):
        await record_security_event(
            tenant_id=tenant, event_type="CONFIG_CHANGE", action="WRITE",
            actor=f"user{i}@acme", actor_role="admin",
            resource_type="settings", resource_id=f"res-{i}",
        )


def test_rows_are_signed_and_verify():
    tenant = _t()

    async def run():
        await _emit(tenant)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(SecurityAuditLog).where(
                SecurityAuditLog.tenant_id == tenant))).scalars().all()
            assert len(rows) == 3
            assert all(r.signature for r in rows)
            verdict = await verify_audit_rows(db, tenant)
        assert verdict["status"] == "VERIFIED"
        assert verdict["verified"] == 3 and verdict["invalid"] == []

    asyncio.run(run())


def test_a_db_level_edit_is_detected():
    tenant = _t()

    async def run():
        await _emit(tenant)
        async with AsyncSessionLocal() as db:
            victim = (await db.execute(select(SecurityAuditLog).where(
                SecurityAuditLog.tenant_id == tenant))).scalars().first()
            victim_id = victim.id
            await db.execute(update(SecurityAuditLog)
                             .where(SecurityAuditLog.id == victim_id)
                             .values(result="BLOCKED"))  # rewrite history
            await db.commit()
            verdict = await verify_audit_rows(db, tenant)
        assert verdict["status"] == "TAMPERED"
        assert victim_id in verdict["invalid"]

    asyncio.run(run())


def test_checkpoint_detects_deletion():
    """Per-row signatures cannot see a DELETE; the ledger-anchored window
    digest can."""
    tenant = _t()

    async def run():
        await _emit(tenant)
        async with AsyncSessionLocal() as db:
            assert await checkpoint_audit_log(db, tenant) is not None
            verdict = await verify_audit_checkpoint(db, tenant)
            assert verdict["status"] == "VERIFIED"

            victim = (await db.execute(select(SecurityAuditLog).where(
                SecurityAuditLog.tenant_id == tenant))).scalars().first()
            await db.delete(victim)
            await db.commit()

            verdict = await verify_audit_checkpoint(db, tenant)
        assert verdict["status"] == "TAMPERED"
        assert verdict["current_count"] == verdict["anchored_count"] - 1

    asyncio.run(run())


def test_legacy_unsigned_rows_report_honestly():
    tenant = _t()

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(SecurityAuditLog(
                id=str(uuid.uuid4()), tenant_id=tenant, event_type="ACCESS",
                action="READ", result="ALLOWED"))  # pre-signing row
            await db.commit()
            verdict = await verify_audit_rows(db, tenant)
        assert verdict["status"] == "LEGACY_UNVERIFIABLE"
        assert verdict["legacy"] == 1 and verdict["invalid"] == []

    asyncio.run(run())


def test_db_failure_falls_back_to_durable_sink(tmp_path, monkeypatch):
    """A database outage must not silently drop audit events."""
    import app.core.audit as audit_mod

    sink = tmp_path / "audit-fallback.jsonl"
    monkeypatch.setattr(audit_mod, "_FALLBACK_PATH", str(sink))

    class _Boom:
        def __call__(self):
            raise RuntimeError("db down")

    async def run():
        from app.core import database
        monkeypatch.setattr(database, "AsyncSessionLocal", _Boom())
        await record_security_event(
            tenant_id="tenant_sink", event_type="AUTH_FAILURE", action="LOGIN",
            actor="x@acme", result="BLOCKED")

    asyncio.run(run())
    content = sink.read_text(encoding="utf-8").strip()
    assert content, "the event must land in the fallback sink"
    import json
    event = json.loads(content)
    assert event["tenant_id"] == "tenant_sink"
    assert event["signature"], "even fallback events carry their signature"
