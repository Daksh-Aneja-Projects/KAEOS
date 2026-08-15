"""
Org Pulse cross-domain aggregation. See backend/app/api/routes/org_pulse.py.

Healthcare, lending, and procurement used to be entirely absent from
_DOMAIN_ANALYTICS - missing from domains[], the unified insight feed, and the
org_health average - even though healthcare_analytics/lending_analytics/
procurement_analytics already existed with the same (db, tenant_id, charts=)
signature as the 7 wired-in domains.
"""
import pytest
from httpx import AsyncClient

T = "tenant_org_pulse_test"

ALL_DOMAIN_SLUGS = {
    "finance", "hr", "sales", "support", "operations", "legal", "engineering",
    "healthcare", "lending", "procurement",
}


async def _seed_departments(db):
    from app.workforce.models.core import Department
    for slug in ALL_DOMAIN_SLUGS:
        db.add(Department(id=f"dept-{slug}", tenant_id=T, name=slug.title(),
                          slug=slug, status="ACTIVE"))
    await db.commit()


@pytest.mark.asyncio
async def test_pulse_covers_all_ten_departments(async_client: AsyncClient, db):
    await _seed_departments(db)
    r = await async_client.get("/api/v1/org/pulse", headers={"X-Tenant-ID": T})
    assert r.status_code == 200, r.text
    body = r.json()
    domains = {d["domain"] for d in body["domains"]}
    assert domains == ALL_DOMAIN_SLUGS
    # Every domain's analytics call must succeed against a seeded-but-sparse
    # tenant, not just the 7 that were already wired in.
    assert all(not d.get("error") for d in body["domains"]), body["domains"]


@pytest.mark.asyncio
async def test_pulse_org_health_averages_all_ten_scored_domains(async_client: AsyncClient, db):
    await _seed_departments(db)
    r = await async_client.get("/api/v1/org/pulse", headers={"X-Tenant-ID": T})
    body = r.json()
    scored = [d["health"] for d in body["domains"] if d["health"] is not None]
    assert len(scored) == 10
    assert body["org_health"] == round(sum(scored) / len(scored))


@pytest.mark.asyncio
async def test_pulse_insight_feed_includes_the_new_domains(async_client: AsyncClient, db):
    """A real warning-severity healthcare insight (42 CFR Part 2 disclosure)
    must reach the same unified feed finance/hr/etc. insights land in."""
    from app.healthcare.models.core import PHIDisclosure

    await _seed_departments(db)
    db.add(PHIDisclosure(
        tenant_id=T, purpose="treatment", recipient="Community Clinic",
        minimum_necessary_justification="Continuity of care handoff.", part2=True,
    ))
    await db.commit()

    r = await async_client.get("/api/v1/org/pulse", headers={"X-Tenant-ID": T})
    body = r.json()
    healthcare_insights = [i for i in body["insights"] if i["domain"] == "healthcare"]
    assert healthcare_insights, body["insights"]
    assert healthcare_insights[0]["severity"] == "warning"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
