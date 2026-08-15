"""
Status-vocabulary regression tests for the healthcare dashboard/seed.

PatientEncounter.status has exactly one documented canonical vocabulary
(OPEN|TRIAGED|CODED|CLOSED) and ClinicalTask.status has exactly one
(OPEN|IN_PROGRESS|PENDING_HITL|DONE|BLOCKED). The dashboard's open_encounters
and open_clinical_tasks counts, and the analytics service, both key off those
exact strings - a seed writing an out-of-vocabulary value (COMPLETED,
IN_PROGRESS-for-an-encounter, DISCHARGED) silently drops a row from the count.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import func as sqlfunc, select

from app.healthcare.models.core import ClinicalTask, PatientEncounter

TENANT = "tenant_acme"  # dev-context tenant resolved for unauthenticated tests


async def _seed_hand_countable_fixture(db):
    """Mirrors app/healthcare/seed.py's status distribution exactly: 8
    encounters (1 OPEN, 3 TRIAGED, 4 CLOSED) and 6 clinical tasks (1 DONE,
    5 open)."""
    enc_statuses = ["CLOSED", "TRIAGED", "CLOSED", "TRIAGED", "CLOSED", "OPEN", "TRIAGED", "CLOSED"]
    for i, s in enumerate(enc_statuses, start=1):
        db.add(PatientEncounter(tenant_id=TENANT, encounter_number=f"ENC-V-{i}",
                                patient_ref=f"pt-anon-v{i}", encounter_type="office_visit", status=s))
    task_statuses = ["DONE", "IN_PROGRESS", "OPEN", "OPEN", "OPEN", "BLOCKED"]
    for i, s in enumerate(task_statuses, start=1):
        db.add(ClinicalTask(tenant_id=TENANT, task_type="coding", status=s))
    await db.commit()


@pytest.mark.asyncio
async def test_dashboard_open_counts_match_hand_counted_expectation(async_client: AsyncClient, db):
    await _seed_hand_countable_fixture(db)
    r = await async_client.get("/api/v1/healthcare/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_encounters"] == 8
    # OPEN(1) + TRIAGED(3) = 4, hand-counted from the fixture above - the two
    # clinically-active encounters (TRIAGED) must be counted as open.
    assert body["open_encounters"] == 4
    # 6 tasks, 1 DONE -> 5 open, hand-counted from the fixture above.
    assert body["open_clinical_tasks"] == 5


@pytest.mark.asyncio
async def test_analytics_open_tasks_matches_dashboard(async_client: AsyncClient, db):
    await _seed_hand_countable_fixture(db)
    r = await async_client.get("/api/v1/healthcare/analytics")
    assert r.status_code == 200, r.text
    kpis = {k["key"]: k["value"] for k in r.json()["kpis"]}
    assert kpis["open_tasks"] == 5
    assert kpis["open_encounters"] == 4


@pytest.mark.asyncio
async def test_seed_writes_only_canonical_statuses_and_is_idempotent(monkeypatch, db):
    import app.healthcare.seed as healthcare_seed
    from tests.conftest import TestingSessionLocal, test_engine

    monkeypatch.setattr(healthcare_seed, "AsyncSessionLocal", TestingSessionLocal)
    monkeypatch.setattr(healthcare_seed, "async_engine", test_engine)
    monkeypatch.setattr(healthcare_seed, "TENANT", TENANT)

    await healthcare_seed.seed()

    enc_statuses = (await db.execute(
        select(PatientEncounter.status).where(PatientEncounter.tenant_id == TENANT))).scalars().all()
    assert set(enc_statuses) <= {"OPEN", "TRIAGED", "CODED", "CLOSED"}

    task_statuses = (await db.execute(
        select(ClinicalTask.status).where(ClinicalTask.tenant_id == TENANT))).scalars().all()
    assert set(task_statuses) <= {"OPEN", "IN_PROGRESS", "PENDING_HITL", "DONE", "BLOCKED"}

    enc_count_1 = (await db.execute(select(sqlfunc.count()).select_from(PatientEncounter)
                                    .where(PatientEncounter.tenant_id == TENANT))).scalar()
    assert enc_count_1 == 8

    # A second run (direct script invocation, a re-triggered startup seed)
    # must be a no-op, not a duplicate-row write or a unique-constraint crash.
    await healthcare_seed.seed()
    enc_count_2 = (await db.execute(select(sqlfunc.count()).select_from(PatientEncounter)
                                    .where(PatientEncounter.tenant_id == TENANT))).scalar()
    assert enc_count_2 == enc_count_1
