"""Data-lifecycle: retention windows + right-to-erasure.

Runs on the in-memory unit harness (no live server). Proves:
  * the retention allow-list can never target the integrity/ledger tables;
  * retention is opt-in (no policy → nothing deleted) and only deletes rows
    older than the configured window, leaving fresh rows intact;
  * unknown data classes are rejected;
  * subject erasure tombstones direct identifiers in place.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, func

from app.services import retention
from app.services.privacy_erasure import erase_subject
from app.models.domain import Signal
from app.hr.models.core import HREmployee

_OLD = datetime(2000, 1, 1, tzinfo=timezone.utc)   # comfortably past any window
TENANT = "tenant_acme"


def test_registry_excludes_integrity_tables():
    """The provenance ledger and Foundry training lineage are never purgeable."""
    targeted = {c.table for c in retention.RETENTION_CLASSES.values()}
    assert "provenance_ledger" not in targeted
    assert "skill_executions" not in targeted


def test_registry_tables_are_real_and_time_scoped():
    """Every declared class points at a real, tenant-scoped, timestamped table."""
    from app.models.domain import Base
    import app.core.database  # noqa: F401 — register all tables
    for key, cls in retention.RETENTION_CLASSES.items():
        tbl = Base.metadata.tables.get(cls.table)
        assert tbl is not None, f"{key}: table {cls.table} not registered"
        assert cls.ts_column in tbl.c, f"{key}: missing ts column {cls.ts_column}"
        assert "tenant_id" in tbl.c, f"{key}: {cls.table} is not tenant-scoped"


@pytest.mark.asyncio
async def test_retention_is_opt_in_noop_without_policy(db):
    """With no policy configured, an old row is NOT deleted."""
    db.add(Signal(tenant_id=TENANT, domain="hr", created_at=_OLD))
    await db.commit()

    receipt = await retention.apply_for_tenant(db, TENANT, dry_run=False)
    assert receipt["total"] == 0
    remaining = (await db.execute(
        select(func.count()).select_from(Signal.__table__)
        .where(Signal.tenant_id == TENANT)
    )).scalar_one()
    assert remaining == 1


@pytest.mark.asyncio
async def test_retention_purges_only_old_rows(db):
    """Enabled window deletes rows past the cutoff, keeps fresh rows."""
    db.add(Signal(tenant_id=TENANT, domain="hr", created_at=_OLD))          # stale
    db.add(Signal(tenant_id=TENANT, domain="hr",
                  created_at=datetime.now(timezone.utc)))                    # fresh
    await db.commit()

    await retention.set_policy(db, TENANT, "signals", retain_days=1, enabled=True)

    # Dry-run counts the one stale row without deleting.
    preview = await retention.apply_for_tenant(db, TENANT, dry_run=True)
    assert preview["classes"]["signals"]["count"] == 1
    still_two = (await db.execute(
        select(func.count()).select_from(Signal.__table__)
        .where(Signal.tenant_id == TENANT)
    )).scalar_one()
    assert still_two == 2, "dry-run must not delete"

    # Real run deletes exactly the stale row.
    applied = await retention.apply_for_tenant(db, TENANT, dry_run=False)
    assert applied["total"] == 1
    remaining = (await db.execute(
        select(func.count()).select_from(Signal.__table__)
        .where(Signal.tenant_id == TENANT)
    )).scalar_one()
    assert remaining == 1, "the fresh row must survive"


@pytest.mark.asyncio
async def test_set_policy_rejects_unknown_class(db):
    with pytest.raises(ValueError):
        await retention.set_policy(db, TENANT, "provenance_ledger",
                                   retain_days=1, enabled=True)
    with pytest.raises(ValueError):
        await retention.set_policy(db, TENANT, "does_not_exist",
                                   retain_days=1, enabled=True)


@pytest.mark.asyncio
async def test_erase_subject_tombstones_pii(db):
    emp = HREmployee(
        tenant_id=TENANT, first_name="Ada", last_name="Lovelace",
        email="ada@example.com", hire_date=date(2020, 1, 1), job_title="Engineer",
    )
    db.add(emp)
    await db.commit()
    emp_id = emp.id

    receipt = await erase_subject(db, TENANT, email="ada@example.com")
    assert receipt["total_rows_anonymised"] >= 1

    # erase_subject issues a Core UPDATE; expire the identity-map cache so the
    # re-read reflects the DB (a fresh request session would never see the cache).
    db.expire_all()
    row = (await db.execute(
        select(HREmployee).where(HREmployee.id == emp_id)
    )).scalar_one()
    assert row.first_name == "[ERASED]"
    assert row.last_name == "[ERASED]"
    assert "ada@example.com" != row.email
    assert "invalid.example" in row.email
