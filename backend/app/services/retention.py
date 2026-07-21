"""KAEOS — Configurable data-retention windows (GDPR Art.5(1)(e) storage limitation).

A retention window says "don't keep this class of data longer than N days." This
module makes that enforceable, not just documented:

  * ``RETENTION_CLASSES`` is a CURATED ALLOW-LIST of purgeable data classes. Each
    entry names a real table and its timestamp column. The list is static and
    hand-audited — retention can NEVER be pointed at an arbitrary table, and in
    particular NOT at ``provenance_ledger`` (append-only, hash-chained integrity)
    or ``skill_executions`` (the Foundry training lineage). Deleting either would
    break guarantees the platform makes elsewhere, so they are simply not here.

  * Retention is OPT-IN. A class with no policy row, or ``enabled=False``, is
    never touched. ``default_days`` is only the value a tenant inherits when it
    enables a class without naming its own window.

  * Every purge is tenant-scoped (``tenant_id`` filter AND Postgres RLS) and
    returns an auditable per-class receipt. ``preview``/``dry_run`` count without
    deleting, so an operator can see the blast radius first.

The scheduled cross-tenant sweep (``sweep_all_tenants``) is safe to run on a
schedule but MUST run under a single-leader guard in a multi-replica deployment
(see docs/DEPLOYMENT.md and the background-job leader lock) so two replicas do
not both purge — the deletes are idempotent, but the duplicated work is waste.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionClass:
    table: str          # SQLAlchemy table name (must exist in Base.metadata)
    ts_column: str      # timestamp column the age cutoff compares against
    default_days: int   # inherited window when a tenant enables without a value
    description: str


# ── The allow-list: transient platform telemetry ONLY ────────────────────────
# Deliberately excludes provenance_ledger (integrity) and skill_executions
# (Foundry training source). Business records-of-record in the domain verticals
# (finance/legal audit trails, etc.) are out of scope — those carry their own
# statutory retention and are managed via their own tooling.
RETENTION_CLASSES: dict[str, RetentionClass] = {
    "signals": RetentionClass(
        "signals", "created_at", 365,
        "External/ingested intelligence signals feeding the Company Brain."),
    "agent_messages": RetentionClass(
        "agent_messages", "created_at", 30,
        "Agent-to-agent protocol messages (transient coordination traffic)."),
    "cost_events": RetentionClass(
        "cost_events", "timestamp", 365,
        "Per-call token/cost telemetry events."),
    "activity_feed_events": RetentionClass(
        "activity_feed_events", "created_at", 90,
        "Agent activity-feed entries surfaced in the UI."),
    "decay_events": RetentionClass(
        "decay_events", "timestamp", 180,
        "Confidence-decay log entries."),
    "reality_events": RetentionClass(
        "reality_events", "created_at", 180,
        "Reality-twin shock/simulation feed events."),
    "system_events": RetentionClass(
        "system_events", "timestamp", 90,
        "Platform system-event stream."),
    "security_audit_logs": RetentionClass(
        "security_audit_logs", "timestamp", 730,
        "Security/access audit log (opt-in: many regimes require a MINIMUM "
        "retention — enable only against your own obligations)."),
}

# Hard guard: nothing in the app may ever schedule these for deletion.
_FORBIDDEN_TABLES = {"provenance_ledger", "skill_executions"}
for _k, _c in RETENTION_CLASSES.items():
    assert _c.table not in _FORBIDDEN_TABLES, f"retention class {_k} targets a forbidden table"


def _table(name: str):
    """Resolve a table object from the registered metadata, or None."""
    from app.models.domain import Base
    import app.core.database  # noqa: F401 — ensure every model module is registered
    return Base.metadata.tables.get(name)


def _cutoff(retain_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=retain_days)


async def list_effective(db: AsyncSession, tenant_id: str) -> list[dict]:
    """Every known class merged with this tenant's overrides (defaults elsewhere)."""
    from app.models.settings import RetentionPolicy

    res = await db.execute(
        select(RetentionPolicy).where(RetentionPolicy.tenant_id == tenant_id)
    )
    overrides = {p.data_class: p for p in res.scalars().all()}

    out = []
    for key, cls in RETENTION_CLASSES.items():
        ov = overrides.get(key)
        out.append({
            "data_class": key,
            "table": cls.table,
            "description": cls.description,
            "default_days": cls.default_days,
            "retain_days": (ov.retain_days if ov and ov.retain_days is not None else cls.default_days),
            "enabled": bool(ov.enabled) if ov else False,
        })
    return out


async def set_policy(
    db: AsyncSession, tenant_id: str, data_class: str,
    *, retain_days: Optional[int], enabled: bool,
) -> dict:
    """Upsert one tenant's policy for a class. Validates against the allow-list."""
    from app.models.settings import RetentionPolicy

    if data_class not in RETENTION_CLASSES:
        raise ValueError(
            f"unknown data_class '{data_class}'. Valid: {sorted(RETENTION_CLASSES)}")
    if retain_days is not None and retain_days < 1:
        raise ValueError("retain_days must be >= 1 (or null to use the default)")

    res = await db.execute(
        select(RetentionPolicy).where(
            RetentionPolicy.tenant_id == tenant_id,
            RetentionPolicy.data_class == data_class,
        )
    )
    row = res.scalar_one_or_none()
    if not row:
        row = RetentionPolicy(tenant_id=tenant_id, data_class=data_class)
        db.add(row)
    row.retain_days = retain_days
    row.enabled = enabled
    await db.commit()
    await db.refresh(row)
    return {
        "data_class": data_class,
        "retain_days": row.retain_days if row.retain_days is not None
        else RETENTION_CLASSES[data_class].default_days,
        "enabled": row.enabled,
    }


async def apply_for_tenant(db: AsyncSession, tenant_id: str, *, dry_run: bool = True) -> dict:
    """Purge (or, in dry-run, count) rows past their window for every ENABLED class.

    Returns ``{tenant_id, dry_run, total, classes: {class: {cutoff, count}}}``.
    Only enabled classes act; disabled/unset classes are reported as skipped.
    """
    effective = await list_effective(db, tenant_id)
    result: dict[str, dict] = {}
    total = 0

    for policy in effective:
        key = policy["data_class"]
        if not policy["enabled"]:
            result[key] = {"skipped": "not enabled"}
            continue
        cls = RETENTION_CLASSES[key]
        table = _table(cls.table)
        if table is None or cls.ts_column not in table.c or "tenant_id" not in table.c:
            result[key] = {"skipped": "table/column unavailable"}
            continue

        cutoff = _cutoff(policy["retain_days"])
        ts_col = table.c[cls.ts_column]
        where = (table.c.tenant_id == tenant_id) & (ts_col < cutoff)

        if dry_run:
            count = (await db.execute(
                select(func.count()).select_from(table).where(where)
            )).scalar_one()
        else:
            res = await db.execute(delete(table).where(where))
            count = int(res.rowcount or 0)

        total += int(count)
        result[key] = {"cutoff": cutoff.isoformat(), "count": int(count)}

    if not dry_run:
        await db.commit()

    logger.info(
        "[Retention] tenant=%s dry_run=%s purged/matched %d rows across %d classes",
        tenant_id, dry_run, total, len(RETENTION_CLASSES),
    )
    return {"tenant_id": tenant_id, "dry_run": dry_run, "total": total, "classes": result}


async def sweep_all_tenants(*, dry_run: bool = False) -> list[dict]:
    """Scheduled cross-tenant sweep. Runs on the OWNER session, per-tenant context.

    MUST be single-leader in multi-replica deployments (idempotent, but running
    twice is wasted work). Iterates the tenants table and applies each tenant's
    enabled policies under that tenant's RLS context.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.context import current_tenant_id

    # Enumerate tenants from the registry (platform-global table).
    async with AsyncSessionLocal() as db:
        tenants_tbl = _table("tenants")
        if tenants_tbl is None:
            return []
        rows = (await db.execute(select(tenants_tbl.c.id))).fetchall()
        tenant_ids = [r[0] for r in rows]

    receipts = []
    for tid in tenant_ids:
        current_tenant_id.set(tid)
        async with AsyncSessionLocal() as db:
            try:
                receipts.append(await apply_for_tenant(db, tid, dry_run=dry_run))
            except Exception as e:  # one tenant's failure must not abort the sweep
                logger.warning("[Retention] sweep failed for tenant %s: %s", tid, e)
                receipts.append({"tenant_id": tid, "error": str(e)})
    return receipts
