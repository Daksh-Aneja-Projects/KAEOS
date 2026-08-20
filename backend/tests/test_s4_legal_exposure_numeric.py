"""S4.7 — legal estimated exposure is money, not free text.

`leg_matters.estimated_exposure` was Text, so a matter's exposure could not be
summed, compared or ordered. It is now Numeric(18,2) end to end: the API takes a
Decimal (rejecting prose) and returns a JSON number.

The Text -> Numeric conversion itself lives in Postgres-only migration
0054_legal_exposure_numeric; SQLite builds the table from the model via
create_all, so there is nothing to smoke-test here — the Postgres drift gate
covers it.
"""
import uuid

import pytest
from httpx import AsyncClient


def _t() -> str:
    return f"tenant_{uuid.uuid4().hex[:8]}"


def test_column_is_exact_numeric():
    from sqlalchemy import Numeric

    from app.legal.models.core import LegalMatter

    col_type = LegalMatter.__table__.c.estimated_exposure.type
    assert isinstance(col_type, Numeric)
    assert (col_type.precision, col_type.scale) == (18, 2)


@pytest.mark.asyncio
async def test_exposure_round_trips_as_a_number(async_client: AsyncClient):
    tenant = _t()
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant}, json={
        "title": "Exposure Round Trip", "matter_type": "Litigation",
        "estimated_exposure": 125000.50,
    })
    assert r.status_code == 201, r.text

    r2 = await async_client.get("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant})
    assert r2.status_code == 200, r2.text
    m = next(x for x in r2.json() if x["title"] == "Exposure Round Trip")
    assert m["exposure"] == 125000.5
    assert isinstance(m["exposure"], (int, float))


@pytest.mark.asyncio
async def test_prose_exposure_is_rejected(async_client: AsyncClient):
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": _t()}, json={
        "title": "Vague Exposure", "matter_type": "Corporate",
        "estimated_exposure": "not money",
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_exposure_is_optional_and_stays_null(async_client: AsyncClient):
    tenant = _t()
    r = await async_client.post("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant}, json={
        "title": "Unquantified Matter", "matter_type": "Corporate",
    })
    assert r.status_code == 201, r.text

    r2 = await async_client.get("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant})
    m = next(x for x in r2.json() if x["title"] == "Unquantified Matter")
    assert m["exposure"] is None
