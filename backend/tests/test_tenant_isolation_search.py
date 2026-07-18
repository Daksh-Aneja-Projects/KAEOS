"""
Regression: cross-tenant data leak in global search.

`GET /search` had NO tenant filter - it queried every Rule/Skill/Signal/
Question in the database regardless of caller. Proven live by inserting a rule
under `tenant_competitor_secret` and reading it back as `tenant_acme`.

The endpoint was low-risk while nothing called it; it became user-facing the
moment the search box was wired to the Company Brain, which is exactly how a
dormant hole ships.

This is the highest-severity class in a multi-tenant product: every list query
is scoped by hand, so one omission leaks a customer's data to another. Postgres
Row-Level Security would make it structurally impossible - see the review notes.
"""
import pytest
from httpx import AsyncClient

OTHER = "tenant_competitor_secret"
MINE = "tenant_isolation_test"


@pytest.mark.asyncio
async def test_search_does_not_leak_other_tenants(async_client: AsyncClient, db):
    from app.models.domain import Rule

    db.add(Rule(
        id="leak-test-rule", tenant_id=OTHER,
        statement="ZZSECRET competitor merger plan",
        trigger_json={}, action_json={}, confidence_scalar=0.9,
        is_archived=False, version=1,
    ))
    db.add(Rule(
        id="own-test-rule", tenant_id=MINE,
        statement="ZZSECRET my own rule",
        trigger_json={}, action_json={}, confidence_scalar=0.9,
        is_archived=False, version=1,
    ))
    await db.commit()

    r = await async_client.get("/api/v1/search?q=ZZSECRET", headers={"X-Tenant-ID": MINE})
    assert r.status_code == 200
    statements = [x["statement"] for x in r.json()["results"]["rules"]]

    assert not any("competitor merger" in s for s in statements), (
        "CROSS-TENANT LEAK: search returned another tenant's rule"
    )
    # ...and the caller's own data must still be findable.
    assert any("my own rule" in s for s in statements)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
