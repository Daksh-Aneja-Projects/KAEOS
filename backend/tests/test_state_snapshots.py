"""
Phase 1A regression tests.

  * Enterprise State is append-only: each mutation inserts a new snapshot row and
    get_state returns the latest (previously overwritten in place under a UNIQUE
    tenant_id constraint).
  * create_all is gated OFF in production (Alembic is the schema authority) and
    ON for dev/test.
"""
from types import SimpleNamespace

import pytest

from app.services.state.state_service import StateService

pytestmark = pytest.mark.asyncio


async def test_state_is_append_only_timeseries(db):
    from sqlalchemy import func, select
    from app.models.enterprise_state import FinanceState

    tenant = "tenant_snap"
    await StateService.mutate_state(db, tenant, "finance",
                                    {"total_cash": 100.0, "financial_health_score": 0.9})
    await StateService.mutate_state(db, tenant, "finance",
                                    {"total_cash": 200.0, "financial_health_score": 0.8})

    count = (await db.execute(
        select(func.count()).select_from(FinanceState).where(FinanceState.tenant_id == tenant)
    )).scalar()
    assert count == 2, "each mutation must append a new snapshot, not overwrite"

    latest = await StateService.get_state(db, tenant, "finance")
    assert latest.total_cash == 200.0
    assert latest.financial_health_score == 0.8


async def test_state_carries_prior_values_forward(db):
    tenant = "tenant_carry"
    await StateService.mutate_state(db, tenant, "hr",
                                    {"total_headcount": 50, "hr_health_score": 0.95})
    # Second mutation only touches one field; the other must carry forward.
    await StateService.mutate_state(db, tenant, "hr", {"hr_health_score": 0.7})
    latest = await StateService.get_state(db, tenant, "hr")
    assert latest.total_headcount == 50, "unmutated fields carry forward into the new snapshot"
    assert latest.hr_health_score == 0.7


def test_create_all_gated_off_in_production(monkeypatch):
    from app.core import database

    monkeypatch.setattr(database, "settings",
                        SimpleNamespace(is_sqlite=False, is_production_like=True))
    monkeypatch.delenv("KAEOS_ALLOW_CREATE_ALL", raising=False)
    assert database._create_all_allowed() is False

    monkeypatch.setenv("KAEOS_ALLOW_CREATE_ALL", "true")
    assert database._create_all_allowed() is True


def test_create_all_allowed_in_dev_and_sqlite(monkeypatch):
    from app.core import database

    monkeypatch.setattr(database, "settings",
                        SimpleNamespace(is_sqlite=True, is_production_like=True))
    assert database._create_all_allowed() is True

    monkeypatch.setattr(database, "settings",
                        SimpleNamespace(is_sqlite=False, is_production_like=False))
    assert database._create_all_allowed() is True
