"""KAEOS — Security audit logging (tamper-evident).

Writes a real, runtime audit trail to `security_audit_logs`: authentication
events, RBAC denials, configuration changes, data exports, and agent executions.
Previously this table was only ever populated by the seed script, so the
"who did what" trail shown in the UI was demo fiction. This is the runtime path.

Design:
  * Best-effort for the audited REQUEST: an audit write must never break the
    request it is auditing - but a failed DB write is no longer silent. The
    event is appended to a local durable fallback sink
    (``logs/audit-fallback.jsonl``) so a database outage cannot blind the
    trail, and the failure itself is logged.
  * `actor_hash` stores a salted hash of the principal (email/user id), not the
    raw identity, so the log itself is not a fresh PII store (it is pseudonymous)
    while still being attributable when correlated with the users table.
  * Tamper-evident: every row carries an HMAC-SHA256 ``signature`` over its
    canonical content, keyed from ``SECRET_KEY`` under an audit-specific
    domain. A database-level edit of a signed row is detectable by
    ``verify_audit_rows``. Deletions are surfaced by the periodic per-tenant
    CHECKPOINTS the scheduler anchors into the signed provenance ledger
    (count + digest over a time window - see ``checkpoint_audit_log``).
  * Append-only: nothing in the app updates or deletes rows, and on Postgres
    migration 0034 revokes UPDATE/DELETE from the app role, making it a
    database guarantee rather than a convention.
"""
import hashlib
import hmac as hmac_mod
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("kaeos.audit")

_AUDIT_DOMAIN = "kaeos.audit.row.v1"
_FALLBACK_PATH = os.path.join("logs", "audit-fallback.jsonl")


def _hash_actor(actor: str | None) -> str:
    if not actor:
        return "anonymous"
    from app.core.config import get_settings
    salt = (get_settings().SECRET_KEY or "kaeos")[:16]
    return hashlib.sha256(f"{salt}:{actor}".encode()).hexdigest()[:64]


def _audit_key() -> bytes:
    from app.core.config import get_settings
    secret = get_settings().SECRET_KEY or "dev-only-unsigned-audit"
    return hashlib.sha256(f"kaeos-audit-hmac|{secret}".encode()).digest()


def _canonical_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.isoformat(timespec="microseconds")


def sign_audit_row(
    *, row_id: str, tenant_id: str, event_type: str | None,
    actor_hash: str | None, actor_role: str | None, resource_type: str | None,
    resource_id: str | None, action: str | None, result: str | None,
    ip_address: str | None, details: dict | None, timestamp: datetime | None,
) -> str:
    """HMAC-SHA256 over the row's canonical content - recomputable from the
    persisted row alone, so a verifier needs nothing but the table and key."""
    payload = json.dumps({
        "id": row_id, "tenant_id": tenant_id, "event_type": event_type,
        "actor_hash": actor_hash, "actor_role": actor_role,
        "resource_type": resource_type, "resource_id": resource_id,
        "action": action, "result": result, "ip_address": ip_address,
        "details": details or {}, "timestamp": _canonical_ts(timestamp),
    }, sort_keys=True, separators=(",", ":"), default=str)
    message = f"{_AUDIT_DOMAIN}|{payload}"
    return hmac_mod.new(_audit_key(), message.encode(), hashlib.sha256).hexdigest()


def _sign_row_obj(row) -> str:
    return sign_audit_row(
        row_id=row.id, tenant_id=row.tenant_id, event_type=row.event_type,
        actor_hash=row.actor_hash, actor_role=row.actor_role,
        resource_type=row.resource_type, resource_id=row.resource_id,
        action=row.action, result=row.result, ip_address=row.ip_address,
        details=row.details, timestamp=row.timestamp,
    )


def _fallback_sink(event: dict) -> None:
    """Durable local sink for events the database could not accept. A lost
    audit event is a hole in the trail; a JSONL line on disk is recoverable."""
    try:
        os.makedirs(os.path.dirname(_FALLBACK_PATH), exist_ok=True)
        with open(_FALLBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:  # even the fallback must not break the request
        logger.error("[audit] fallback sink failed too: %s", e)


async def record_security_event(
    *,
    tenant_id: str,
    event_type: str,           # ACCESS | MODIFICATION | QUERY | AUTH_FAILURE | AUTH_SUCCESS | EXPORT | AGENT_EXEC | RBAC_DENIED | CONFIG_CHANGE
    action: str = "READ",       # READ | WRITE | DELETE | EXECUTE | EXPORT | LOGIN
    result: str = "ALLOWED",    # ALLOWED | BLOCKED | ESCALATED
    actor: str | None = None,   # email or user id — hashed before storage
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    """Persist one signed audit event. Never raises; falls back to a local
    durable sink when the database write fails."""
    from app.core.config import get_settings
    if not get_settings().AUDIT_LOG_ENABLED:
        return

    import uuid
    from app.core.context import current_tenant_id

    tid = tenant_id or current_tenant_id.get() or ""
    if not tid:
        logger.warning("[audit] dropping event with no tenant: %s/%s", event_type, action)
        return

    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    a_hash = _hash_actor(actor)
    ip = (ip_address or "")[:45] or None
    signature = sign_audit_row(
        row_id=row_id, tenant_id=tid, event_type=event_type, actor_hash=a_hash,
        actor_role=actor_role, resource_type=resource_type,
        resource_id=resource_id, action=action, result=result,
        ip_address=ip, details=details or {}, timestamp=now,
    )
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.domain import SecurityAuditLog

        # Bind the tenant so the RLS-scoped session can insert (and so an audit
        # row can never land untenanted).
        current_tenant_id.set(tid)
        async with AsyncSessionLocal() as db:
            db.add(SecurityAuditLog(
                id=row_id,
                tenant_id=tid,
                event_type=event_type,
                actor_hash=a_hash,
                actor_role=actor_role,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                result=result,
                ip_address=ip,
                details=details or {},
                timestamp=now,
                signature=signature,
            ))
            await db.commit()
    except Exception as e:  # audit must never break the audited action
        logger.warning("[audit] DB write failed for %s/%s, using fallback sink: %s",
                       event_type, action, e)
        _fallback_sink({
            "id": row_id, "tenant_id": tid, "event_type": event_type,
            "actor_hash": a_hash, "actor_role": actor_role,
            "resource_type": resource_type, "resource_id": resource_id,
            "action": action, "result": result, "ip_address": ip,
            "details": details or {}, "timestamp": _canonical_ts(now),
            "signature": signature, "sink_reason": str(e)[:300],
        })


async def verify_audit_rows(db, tenant_id: str, limit: int = 5000) -> dict:
    """Recompute signatures for the tenant's newest rows.

    Returns {total, verified, legacy, invalid: [ids]}. Rows written before
    signing carry no signature and are reported as legacy, not as tampering.
    """
    from sqlalchemy import select

    from app.models.domain import SecurityAuditLog

    rows = (await db.execute(
        select(SecurityAuditLog)
        .where(SecurityAuditLog.tenant_id == tenant_id)
        .order_by(SecurityAuditLog.timestamp.desc())
        .limit(max(1, min(50000, limit)))
    )).scalars().all()

    invalid, legacy = [], 0
    for row in rows:
        if not row.signature:
            legacy += 1
            continue
        if _sign_row_obj(row) != row.signature:
            invalid.append(row.id)
    return {
        "total": len(rows),
        "verified": len(rows) - legacy - len(invalid),
        "legacy": legacy,
        "invalid": invalid,
        "status": "TAMPERED" if invalid else ("VERIFIED" if len(rows) > legacy else
                                              ("LEGACY_UNVERIFIABLE" if rows else "EMPTY")),
    }


# Each checkpoint covers this many hours ending at checkpoint time. Windowed
# (not since-genesis) because security_audit_logs has a legitimate opt-in
# retention class (730 days): a digest over ALL rows would report a lawful
# retention purge as tampering. Recent windows are untouchable by retention,
# so a mismatch against a fresh checkpoint IS evidence of deletion/edit.
CHECKPOINT_WINDOW_HOURS = 24


async def _window_state(db, tenant_id: str, start: datetime, end: datetime):
    from sqlalchemy import select

    from app.models.domain import SecurityAuditLog

    sig_rows = (await db.execute(
        select(SecurityAuditLog.signature)
        .where(SecurityAuditLog.tenant_id == tenant_id,
               SecurityAuditLog.signature.isnot(None),
               SecurityAuditLog.timestamp >= start,
               SecurityAuditLog.timestamp < end)
        .order_by(SecurityAuditLog.signature)
    )).scalars().all()
    digest = hashlib.sha256("|".join(sig_rows).encode()).hexdigest()
    return len(sig_rows), digest


async def checkpoint_audit_log(db, tenant_id: str) -> str | None:
    """Anchor a window of the tenant's audit log into the signed ledger.

    Records {window_start, window_end, count, digest-over-signatures} as an
    AUDIT_CHECKPOINT event on the tenant's provenance stream. Because the
    ledger is signed, chained, and append-only, a later DELETE or edit of
    audit rows inside that window shows up as a count/digest mismatch -
    the deletion detection per-row signatures alone cannot provide. Returns
    the ledger entry's chain hash (None when the window is empty).
    """
    from datetime import timedelta

    from app.services.provenance import append_ledger_event

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=CHECKPOINT_WINDOW_HOURS)
    count, digest = await _window_state(db, tenant_id, start, end)
    if count == 0:
        return None

    entry = await append_ledger_event(
        db,
        tenant_id=tenant_id,
        event_type="AUDIT_CHECKPOINT",
        actor_role="audit_checkpointer",
        reasoning=json.dumps({
            "window_start": _canonical_ts(start), "window_end": _canonical_ts(end),
            "count": count, "digest": digest,
        }),
    )
    return entry.chain_hash


async def verify_audit_checkpoint(db, tenant_id: str) -> dict:
    """Recompute the newest AUDIT_CHECKPOINT's window and compare.

    A mismatch on a recent window (which retention cannot lawfully touch)
    means rows were deleted or edited after the checkpoint was anchored.
    """
    from sqlalchemy import select

    from app.models.domain import ProvenanceLedger

    cp = (await db.execute(
        select(ProvenanceLedger)
        .where(ProvenanceLedger.tenant_id == tenant_id,
               ProvenanceLedger.event_type == "AUDIT_CHECKPOINT")
        .order_by(ProvenanceLedger.timestamp.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cp is None:
        return {"status": "NO_CHECKPOINT"}

    try:
        anchored = json.loads(cp.reasoning or "{}")
        start = datetime.fromisoformat(anchored["window_start"]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(anchored["window_end"]).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError) as e:
        return {"status": "MALFORMED_CHECKPOINT", "error": str(e)}

    count, digest = await _window_state(db, tenant_id, start, end)
    matches = (count == anchored.get("count") and digest == anchored.get("digest"))
    return {
        "status": "VERIFIED" if matches else "TAMPERED",
        "checkpoint_id": cp.id,
        "window_start": anchored.get("window_start"),
        "window_end": anchored.get("window_end"),
        "anchored_count": anchored.get("count"),
        "current_count": count,
    }
