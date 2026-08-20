"""S4.12 — the startup seed gate must use the SAME tenant scope as the seeders.

``seed_domains_if_empty`` used to count the sentinel table across ALL tenants,
while the guard inside every seeder (``already_seeded``) is scoped to one
tenant. On a multi-tenant database the first tenant with HR employees made
startup skip HR forever, so SEED_TENANT never got its demo data - even though
the seeder's own guard would have allowed it. These two tests pin both halves:
a foreign tenant's rows must NOT suppress seeding, SEED_TENANT's own rows must.
"""
import datetime

import pytest

from app.core import domain_seed
from app.hr.models.core import HREmployee
from tests.conftest import TestingSessionLocal

_HR_ONLY = [("HR", "app.hr.seed", "app.hr.models.core:HREmployee")]


async def _employee(db, tenant: str) -> None:
    db.add(HREmployee(
        tenant_id=tenant, first_name="Ada", last_name="Byron",
        email=f"ada@{tenant}.test", hire_date=datetime.date(2020, 1, 1),
        job_title="Engineer",
    ))
    await db.commit()


@pytest.fixture
def seed_calls(monkeypatch):
    """Run the orchestrator against the test engine, HR only, seeder stubbed.

    Returns the list the stub records its tenant argument into, so a test can
    assert whether the real seeding step would have run.
    """
    import app.hr.seed as hr_seed

    calls: list = []

    async def _record(tenant=None):
        calls.append(tenant)
        return True

    async def _noop():
        return None

    monkeypatch.setattr(domain_seed, "AsyncSessionLocal", TestingSessionLocal)
    monkeypatch.setattr(domain_seed, "_DOMAINS", _HR_ONLY)
    monkeypatch.setattr(domain_seed, "rollup_department_metrics", _noop)
    monkeypatch.setattr(hr_seed, "seed", _record)
    return calls


@pytest.mark.asyncio
async def test_other_tenants_rows_do_not_suppress_seeding(db, seed_calls):
    await _employee(db, "tenant_other")

    await domain_seed.seed_domains_if_empty()

    # The tenant-blind gate counted this foreign row and skipped HR forever.
    assert seed_calls == [domain_seed.SEED_TENANT]


@pytest.mark.asyncio
async def test_seed_tenants_own_rows_still_suppress_seeding(db, seed_calls):
    await _employee(db, domain_seed.SEED_TENANT)

    await domain_seed.seed_domains_if_empty()

    assert seed_calls == []
