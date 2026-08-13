"""KAEOS - The unified provenance ledger (schema v2).

ONE table, ONE scheme, ONE writer. Before this module, five writers put five
incompatible values in the same `chain_hash` column (an unkeyed sha256, a
sha3-512 chained to the newest row by WALL CLOCK across all tenants, a random
`uuid4()`, a hash of a timestamp string, and a second sha256 with a different
payload shape), so the verify endpoint reported false "TAMPERED" on cleanly
created rules and the flagship trust artifact did not hold under exercise.

The v2 scheme:

- **Signed, not just hashed.** `chain_hash` is an HMAC-SHA256 keyed with a
  ledger key derived from ``SECRET_KEY``. An attacker with database access
  alone cannot rewrite a row and recompute a valid chain; they would need the
  application secret as well. (Postgres deployments additionally revoke
  UPDATE/DELETE on the table from the app role - migration 0032.)
- **Explicit parent, tenant-scoped chains.** Every entry stores the id of its
  parent and belongs to a chain `(tenant_id, chain_scope)`, where the scope is
  the subject rule/skill id, or the ``_tenant`` event stream for subjectless
  events. Chains never cross tenants: under row-level security a tenant can
  verify their own chain end-to-end without reading anyone else's rows.
- **Serialized appends without locks.** A unique index on
  `(tenant_id, chain_scope, parent_id)` makes each parent linkable to at most
  ONE child, and a partial unique index on `(tenant_id, chain_scope) WHERE
  parent_id IS NULL` allows at most one genesis row per chain. Two concurrent
  appends to the same chain cannot fork it - the loser gets an IntegrityError
  inside a SAVEPOINT and retries against the new head. This holds across
  processes and replicas because the database enforces it, not a lock.
- **Recomputable from the row alone.** The signed payload is built strictly
  from persisted columns (including a canonicalized UTC timestamp), so the
  verifier needs nothing but the table and the key.
- **Honest about history.** Rows written before v2 carry no `schema_version`;
  the verifier reports them as ``legacy`` (unverifiable, pre-unification)
  rather than "TAMPERED". A v2 chain may link its genesis to the newest
  legacy row of the same rule for continuity.

Boundary: rotating ``SECRET_KEY`` invalidates HMAC verification for rows
signed under the old key (they will report as invalid, not silently pass).
Export the ledger before rotating if you need continuity of evidence.
"""
import hashlib
import hmac
import json
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

logger = logging.getLogger(__name__)

LEDGER_SCHEMA_VERSION = "v2"
_CHAIN_DOMAIN = "kaeos.provenance.chain.v2"
_GENESIS = "GENESIS"
# The subjectless per-tenant event stream (actuations, exports, governance
# events that are not about one rule).
TENANT_STREAM = "_tenant"
# Bounded retries for append races; each retry re-reads the chain head.
_APPEND_RETRIES = 5


class LedgerAppendError(RuntimeError):
    """The append lost the chain-head race more times than plausible."""


def _ledger_key() -> bytes:
    from app.core.config import get_settings
    secret = get_settings().SECRET_KEY or "dev-only-unsigned-ledger"
    return hashlib.sha256(f"kaeos-ledger-hmac|{secret}".encode()).digest()


def _canonical_ts(ts: Optional[datetime]) -> str:
    """One timestamp representation on every dialect.

    Postgres returns tz-aware datetimes, SQLite may return naive ones (its
    DATETIME storage drops the offset); both were written as UTC, so aware
    values are converted to UTC and naive values are taken as UTC, then
    rendered with a fixed 6-digit microsecond field.
    """
    if ts is None:
        return ""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.isoformat(timespec="microseconds")


def canonical_payload(
    *,
    tenant_id: str,
    chain_scope: str,
    rule_id: Optional[str],
    event_type: str,
    actor_hash: Optional[str],
    actor_role: Optional[str],
    evidence_ids: list,
    confidence_at: Optional[float],
    reasoning: Optional[str],
    parent_id: Optional[str],
    timestamp: datetime,
) -> dict:
    """The signed content - strictly the persisted columns, so a verifier can
    rebuild it from the row alone."""
    return {
        "tenant_id": tenant_id,
        "chain_scope": chain_scope,
        "rule_id": rule_id,
        "event_type": event_type,
        "actor_hash": actor_hash,
        "actor_role": actor_role,
        "evidence_ids": [str(e) for e in (evidence_ids or [])],
        "confidence_at": confidence_at,
        "reasoning": reasoning,
        "parent_id": parent_id,
        "timestamp": _canonical_ts(timestamp),
    }


def compute_chain_hash(parent_hash: str, payload: dict) -> str:
    """HMAC-SHA256 over (domain | parent_hash | canonical payload)."""
    message = "|".join((
        _CHAIN_DOMAIN,
        parent_hash,
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
    ))
    return hmac.new(_ledger_key(), message.encode(), hashlib.sha256).hexdigest()


def _row_payload(row) -> dict:
    """Rebuild the signed payload from a persisted row (verification side)."""
    return canonical_payload(
        tenant_id=row.tenant_id,
        chain_scope=row.chain_scope,
        rule_id=row.rule_id,
        event_type=row.event_type,
        actor_hash=row.actor_hash,
        actor_role=row.actor_role,
        evidence_ids=row.evidence_ids or [],
        confidence_at=row.confidence_at,
        reasoning=row.reasoning,
        parent_id=row.parent_id,
        timestamp=row.timestamp,
    )


async def _chain_head(db: AsyncSession, tenant_id: str, scope: str):
    """The current head of a v2 chain: the row no other row names as parent.

    Falls back to the newest LEGACY row of the same rule when the v2 chain is
    empty, so a rule's new chain links to its pre-unification history instead
    of orphaning it.
    """
    from app.models.domain import ProvenanceLedger

    child = aliased(ProvenanceLedger)
    head_q = (
        select(ProvenanceLedger)
        .outerjoin(child, (child.parent_id == ProvenanceLedger.id)
                   & (child.tenant_id == tenant_id)
                   & (child.chain_scope == scope))
        .where(
            ProvenanceLedger.tenant_id == tenant_id,
            ProvenanceLedger.chain_scope == scope,
            ProvenanceLedger.schema_version == LEDGER_SCHEMA_VERSION,
            child.id.is_(None),
        )
    )
    head = (await db.execute(head_q)).scalars().first()
    if head is not None:
        return head

    if scope != TENANT_STREAM:
        legacy_q = (
            select(ProvenanceLedger)
            .where(
                ProvenanceLedger.tenant_id == tenant_id,
                ProvenanceLedger.rule_id == scope,
                ProvenanceLedger.schema_version.is_(None),
            )
            .order_by(ProvenanceLedger.timestamp.desc())
            .limit(1)
        )
        return (await db.execute(legacy_q)).scalars().first()
    return None


async def append_ledger_event(
    db: AsyncSession,
    *,
    tenant_id: str,
    event_type: str,
    reasoning: str,
    rule_id: Optional[str] = None,
    actor_hash: Optional[str] = None,
    actor_role: Optional[str] = None,
    evidence_ids: Optional[list] = None,
    confidence_at: Optional[float] = None,
    scope: Optional[str] = None,
    commit: bool = True,
):
    """THE ledger writer - every provenance entry in the product goes through
    here. Returns the persisted row.

    Appends are serialized by the database (see module docstring): a lost race
    rolls back to a SAVEPOINT (the caller's other pending work survives) and
    retries against the new head. With ``commit=True`` (default, matching the
    behavior of every pre-unification writer) the caller's session is
    committed, so the ledger entry lands atomically with the business change
    already pending in that session.
    """
    from app.models.domain import ProvenanceLedger

    if not tenant_id:
        # RLS binds app.tenant_id on Postgres; an unattributed row would be
        # rejected there and silently unscoped on SQLite. Fail loudly instead.
        raise ValueError("append_ledger_event requires tenant_id")

    scope = scope or (str(rule_id) if rule_id else TENANT_STREAM)
    evidence_ids = [str(e) for e in (evidence_ids or [])]

    last_error: Exception | None = None
    for _attempt in range(_APPEND_RETRIES):
        head = await _chain_head(db, tenant_id, scope)
        parent_id = head.id if head is not None else None
        parent_hash = head.chain_hash if head is not None and head.chain_hash else _GENESIS

        now = datetime.now(timezone.utc)
        payload = canonical_payload(
            tenant_id=tenant_id,
            chain_scope=scope,
            rule_id=str(rule_id) if rule_id else None,
            event_type=event_type,
            actor_hash=actor_hash,
            actor_role=actor_role,
            evidence_ids=evidence_ids,
            confidence_at=confidence_at,
            reasoning=reasoning,
            parent_id=parent_id,
            timestamp=now,
        )
        entry = ProvenanceLedger(
            id=str(uuid_mod.uuid4()),
            tenant_id=tenant_id,
            rule_id=str(rule_id) if rule_id else None,
            event_type=event_type,
            timestamp=now,
            actor_hash=actor_hash,
            actor_role=actor_role,
            evidence_ids=evidence_ids,
            confidence_at=confidence_at,
            reasoning=reasoning,
            parent_id=parent_id,
            chain_scope=scope,
            schema_version=LEDGER_SCHEMA_VERSION,
            chain_hash=compute_chain_hash(parent_hash, payload),
        )
        try:
            async with db.begin_nested():
                db.add(entry)
        except IntegrityError as e:
            # Lost the head race (or duplicate genesis). The savepoint rolled
            # back only this entry; re-read the head and retry.
            last_error = e
            logger.info(
                f"[Ledger] append race on chain ({tenant_id}, {scope}) - retrying"
            )
            continue
        if commit:
            await db.commit()
        return entry

    raise LedgerAppendError(
        f"could not append to chain ({tenant_id}, {scope}) after "
        f"{_APPEND_RETRIES} attempts"
    ) from last_error


async def verify_chain(db: AsyncSession, tenant_id: str, scope: str) -> dict:
    """Recompute and check every v2 entry of one chain; report legacy honestly.

    Returns a rich verdict::

        {status, chain_valid, total, verified, legacy, invalid: [...],
         broken_links: [...], forks: [...]}

    - ``VERIFIED``: every v2 entry recomputes exactly and links resolve.
    - ``TAMPERED``: at least one v2 entry fails recomputation or names a
      missing parent.
    - ``LEGACY_UNVERIFIABLE``: only pre-unification rows exist; nothing can be
      cryptographically verified (``chain_valid`` is None, not False - absence
      of proof is not proof of tampering).
    - ``EMPTY``: no rows at all.
    """
    from app.models.domain import ProvenanceLedger

    if scope == TENANT_STREAM:
        rows_q = select(ProvenanceLedger).where(
            ProvenanceLedger.tenant_id == tenant_id,
            ProvenanceLedger.chain_scope == TENANT_STREAM,
        )
    else:
        # A rule's chain: its v2 rows plus its legacy (pre-scope) rows.
        rows_q = select(ProvenanceLedger).where(
            ProvenanceLedger.tenant_id == tenant_id,
            (ProvenanceLedger.chain_scope == scope)
            | ((ProvenanceLedger.rule_id == scope)
               & (ProvenanceLedger.schema_version.is_(None))),
        )
    rows = (await db.execute(rows_q.order_by(ProvenanceLedger.timestamp.asc()))).scalars().all()

    if not rows:
        return {"status": "EMPTY", "chain_valid": None, "total": 0,
                "verified": 0, "legacy": 0, "invalid": [], "broken_links": [],
                "forks": []}

    by_id = {r.id: r for r in rows}
    v2_rows = [r for r in rows if r.schema_version == LEDGER_SCHEMA_VERSION]
    legacy_count = len(rows) - len(v2_rows)

    invalid, broken_links = [], []
    children: dict = {}
    for row in v2_rows:
        children.setdefault(row.parent_id, []).append(row.id)
        if row.parent_id is None:
            parent_hash = _GENESIS
        else:
            parent = by_id.get(row.parent_id)
            if parent is None:
                # Parent may be outside this scope's row set only if data was
                # deleted or rewired - a real integrity failure.
                parent = await db.get(ProvenanceLedger, row.parent_id)
            if parent is None or not parent.chain_hash:
                broken_links.append(row.id)
                continue
            parent_hash = parent.chain_hash
        expected = compute_chain_hash(parent_hash, _row_payload(row))
        if expected != row.chain_hash:
            invalid.append(row.id)

    forks = [
        {"parent_id": pid, "children": kids}
        for pid, kids in children.items()
        if pid is not None and len(kids) > 1
    ]

    if invalid or broken_links:
        status, chain_valid = "TAMPERED", False
    elif v2_rows:
        status, chain_valid = "VERIFIED", True
    else:
        status, chain_valid = "LEGACY_UNVERIFIABLE", None

    return {
        "status": status,
        "chain_valid": chain_valid,
        "total": len(rows),
        "verified": len(v2_rows) - len(invalid) - len(broken_links),
        "legacy": legacy_count,
        "invalid": invalid,
        "broken_links": broken_links,
        "forks": forks,
    }


class ProvenanceEngine:
    """L11 - Knowledge Provenance & Lineage Ledger.

    Compatibility facade over the unified writer/verifier above. Existing
    callers (skill executor, rules lifecycle, gates) keep their API; every
    entry they write now lands in the one signed scheme.
    """

    @staticmethod
    def calculate_chain_hash(parent_hash: str, payload: dict) -> str:
        return compute_chain_hash(parent_hash, payload)

    async def log_event(
        self,
        db_session: AsyncSession,
        rule_id: UUID,
        event_type: str,
        actor_hash: str,
        actor_role: str,
        evidence_ids: list,
        confidence_at: float,
        reasoning: str,
        parent_id: UUID = None,  # kept for API compat; the chain derives it
        tenant_id: str = None,
    ) -> str:
        """Append an event about a rule/skill. Returns the entry's chain hash.

        ``parent_id`` is accepted for backward compatibility but the parent is
        derived from the chain head - callers guessing their own parent was one
        of the ways the old chains forked.
        """
        from app.models.domain import Rule

        if tenant_id is None and rule_id is not None:
            rule = await db_session.get(Rule, str(rule_id))
            tenant_id = getattr(rule, "tenant_id", None)

        entry = await append_ledger_event(
            db_session,
            tenant_id=tenant_id,
            rule_id=str(rule_id) if rule_id else None,
            event_type=event_type,
            actor_hash=actor_hash,
            actor_role=actor_role,
            evidence_ids=evidence_ids,
            confidence_at=confidence_at,
            reasoning=reasoning,
        )
        return entry.chain_hash

    async def verify_chain_integrity(
        self, db_session: AsyncSession, rule_id: UUID, tenant_id: str = None
    ) -> bool:
        """Boolean compatibility wrapper over ``verify_chain``.

        True unless a v2 entry provably fails verification. Legacy-only chains
        return True here (nothing failed); the rich endpoint distinguishes
        LEGACY_UNVERIFIABLE from VERIFIED.
        """
        if tenant_id is None:
            from app.models.domain import ProvenanceLedger
            any_row = (await db_session.execute(
                select(ProvenanceLedger.tenant_id)
                .where(ProvenanceLedger.rule_id == str(rule_id))
                .limit(1)
            )).scalar_one_or_none()
            if any_row is None:
                return True
            tenant_id = any_row
        verdict = await verify_chain(db_session, tenant_id, str(rule_id))
        return verdict["status"] != "TAMPERED"
