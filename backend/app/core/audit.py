"""KAEOS — Security audit logging.

Writes a real, runtime audit trail to `security_audit_logs`: authentication
events, RBAC denials, configuration changes, data exports, and agent executions.
Previously this table was only ever populated by the seed script, so the
"who did what" trail shown in the UI was demo fiction. This is the runtime path.

Design:
  * Best-effort: an audit write must never break the request it is auditing, so
    every failure is caught and logged, not raised.
  * `actor_hash` stores a salted hash of the principal (email/user id), not the
    raw identity, so the log itself is not a fresh PII store (it is pseudonymous)
    while still being attributable when correlated with the users table.
  * Append-only in practice: nothing in the app deletes from this table, and no
    UPDATE path exists. (A DB owner can still rewrite rows — enforce that with
    Postgres grants in a hardened deployment.)
"""
import hashlib
import logging

logger = logging.getLogger("kaeos.audit")


def _hash_actor(actor: str | None) -> str:
    if not actor:
        return "anonymous"
    from app.core.config import get_settings
    salt = (get_settings().SECRET_KEY or "kaeos")[:16]
    return hashlib.sha256(f"{salt}:{actor}".encode()).hexdigest()[:64]


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
    """Persist one audit event. Never raises."""
    from app.core.config import get_settings
    if not get_settings().AUDIT_LOG_ENABLED:
        return
    try:
        import uuid
        from datetime import datetime, timezone
        from app.core.database import AsyncSessionLocal
        from app.core.context import current_tenant_id
        from app.models.domain import SecurityAuditLog

        # Bind the tenant so the RLS-scoped session can insert (and so an audit
        # row can never land untenanted).
        tid = tenant_id or current_tenant_id.get() or ""
        if not tid:
            logger.warning("[audit] dropping event with no tenant: %s/%s", event_type, action)
            return
        current_tenant_id.set(tid)

        async with AsyncSessionLocal() as db:
            db.add(SecurityAuditLog(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                event_type=event_type,
                actor_hash=_hash_actor(actor),
                actor_role=actor_role,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                result=result,
                ip_address=(ip_address or "")[:45] or None,
                details=details or {},
                timestamp=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception as e:  # audit must never break the audited action
        logger.warning("[audit] failed to record %s/%s: %s", event_type, action, e)
