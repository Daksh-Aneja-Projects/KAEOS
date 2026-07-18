"""
KAEOS E2E Test 28 — Cross-tenant denial

THE test class this suite was missing. On 2026-07-17 an audit found **105
confirmed cross-tenant defects** in a codebase whose 405-test suite was fully
green — because not one of those 405 tests ever asked the only question that
matters for a multi-tenant product:

    "Can tenant A touch tenant B's data?"

Every test here answers that for one surface. They are written to FAIL LOUDLY
if an endpoint regresses to trusting a tenant_id from a path/body, or forgets
to filter a query. Two real bug shapes they lock closed:

  A. endpoint takes `tenant_id = Depends(get_tenant_id)` and never filters by it
     (e.g. GET /extraction/signals returned every tenant's signals)
  B. endpoint takes tenant_id / a resource id from the PATH or BODY and acts on
     it unchecked (e.g. POST /config/mcp-tools overwrote another tenant's row
     because tool_id was globally unique)

Postgres RLS backstops many of these, but NOT all: `users` is RLS-exempt by
design (login resolves the tenant FROM the user), HITL records live in Redis,
and SQLite dev has no RLS at all. These tests must pass on both engines.

Mechanics: DEV_MODE honours an X-Tenant-ID header (see app/core/tenant.py), so
each request below acts as a chosen tenant. That override is exactly why these
holes are trivially exploitable in dev — which is the point of testing them.
"""
import uuid

import pytest

TENANT_A = "tenant_acme"
TENANT_B = f"tenant_denial_probe_{uuid.uuid4().hex[:8]}"


def _as(tenant: str) -> dict:
    return {"X-Tenant-ID": tenant}


@pytest.mark.asyncio
class TestMCPToolCredentialIsolation:
    """POST /config/mcp-tools served every tenant's PLAINTEXT api_key and let
    any tenant overwrite any other's, because tool_id was globally unique."""

    async def test_key_is_never_returned(self, client):
        tool = f"probe_tool_{uuid.uuid4().hex[:8]}"
        r = await client.post("/config/mcp-tools", json={
            "tool_id": tool, "is_active": True,
            "rate_limit_per_hour": 111, "api_key": "SUPER-SECRET-B",
        }, headers=_as(TENANT_B))
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"

        body = r.json()
        assert "api_key" not in body, "write response echoed the secret back"
        assert body.get("key_configured") is True, "key was not actually stored"

        listing = (await client.get("/config/mcp-tools", headers=_as(TENANT_B))).json()
        assert "SUPER-SECRET-B" not in str(listing), "GET served the key in plaintext"
        assert all("api_key" not in row for row in listing), "GET exposes an api_key field"

    async def test_other_tenants_tools_are_invisible(self, client):
        tool = f"probe_tool_{uuid.uuid4().hex[:8]}"
        await client.post("/config/mcp-tools", json={
            "tool_id": tool, "is_active": True,
            "rate_limit_per_hour": 111, "api_key": "SECRET-B",
        }, headers=_as(TENANT_B))

        seen = (await client.get("/config/mcp-tools", headers=_as(TENANT_A))).json()
        assert tool not in [row["tool_id"] for row in seen], (
            f"tenant {TENANT_A} can see {TENANT_B}'s MCP tool config"
        )

    async def test_write_cannot_clobber_another_tenants_row(self, client):
        """The exact exploit: same tool_id, different tenant."""
        tool = f"probe_tool_{uuid.uuid4().hex[:8]}"
        await client.post("/config/mcp-tools", json={
            "tool_id": tool, "is_active": True,
            "rate_limit_per_hour": 111, "api_key": "SECRET-B",
        }, headers=_as(TENANT_B))

        # Tenant A writes the SAME tool_id — must get its own row.
        r = await client.post("/config/mcp-tools", json={
            "tool_id": tool, "is_active": False,
            "rate_limit_per_hour": 999, "api_key": "SECRET-A",
        }, headers=_as(TENANT_A))
        assert r.status_code == 200, f"tenant A could not create its own row: {r.text[:200]}"

        after = (await client.get("/config/mcp-tools", headers=_as(TENANT_B))).json()
        b_row = next((x for x in after if x["tool_id"] == tool), None)
        assert b_row is not None, "tenant B's row VANISHED — tenant A overwrote it"
        assert b_row["rate_limit_per_hour"] == 111, (
            "tenant A's write clobbered tenant B's config"
        )


@pytest.mark.asyncio
class TestSignalIsolation:
    """GET /extraction/signals took tenant_id and never filtered on it."""

    async def test_signals_are_scoped_to_caller(self, client):
        a = (await client.get("/extraction/signals", headers=_as(TENANT_A))).json()
        foreign = {s.get("domain") and s["id"] for s in a.get("signals", [])}
        b = (await client.get("/extraction/signals", headers=_as(TENANT_B))).json()
        b_ids = {s["id"] for s in b.get("signals", [])}
        assert not (foreign & b_ids), "signal feeds overlap across tenants"

    async def test_probe_tenant_sees_no_foreign_signals(self, client):
        """A tenant with no data must get an EMPTY feed, not everyone else's."""
        data = (await client.get("/extraction/signals", headers=_as(TENANT_B))).json()
        assert data["signals"] == [], (
            f"a tenant with no signals received {len(data['signals'])} — from other tenants"
        )


@pytest.mark.asyncio
class TestHITLQueueIsolation:
    """Approving another tenant's HITL RESUMES their gated agent action —
    the governance guarantee the product is sold on. Redis-backed, so RLS
    cannot backstop it."""

    async def test_pending_queue_is_scoped(self, client):
        pending = (await client.get("/skills/hitl/pending", headers=_as(TENANT_B))).json()
        assert pending == [], (
            f"a tenant with no executions sees {len(pending)} pending HITL items "
            "(with their context payloads) from other tenants"
        )

    async def test_cannot_approve_another_tenants_execution(self, client):
        """Find a real execution in A, try to approve it as B."""
        a_pending = (await client.get("/skills/hitl/pending", headers=_as(TENANT_A))).json()
        execs = (await client.get("/skills/executions?limit=5", headers=_as(TENANT_A))).json()
        rows = a_pending or (execs if isinstance(execs, list) else execs.get("executions", []))
        if not rows:
            pytest.skip("no executions in tenant A to attempt a cross-tenant approval on")

        victim_id = rows[0]["id"]
        r = await client.post(f"/skills/hitl/{victim_id}/approve", headers=_as(TENANT_B))
        assert r.status_code == 404, (
            f"tenant {TENANT_B} approved {TENANT_A}'s execution {victim_id}: {r.status_code}"
        )

    async def test_cannot_read_another_tenants_hitl_status(self, client):
        execs = (await client.get("/skills/executions?limit=5", headers=_as(TENANT_A))).json()
        rows = execs if isinstance(execs, list) else execs.get("executions", [])
        if not rows:
            pytest.skip("no executions in tenant A")
        r = await client.get(f"/hitl/status/{rows[0]['id']}", headers=_as(TENANT_B))
        assert r.status_code == 404, "HITL status readable across tenants"


@pytest.mark.asyncio
class TestOnboardingIsolation:
    """Provisioning is a platform action; a tenant may only touch its own."""

    async def test_cannot_provision_or_read_another_tenant(self, client):
        for call in (
            client.post("/infrastructure/onboarding",
                        json={"tenant_id": TENANT_A, "tenant_name": "Hijack"},
                        headers=_as(TENANT_B)),
            client.get(f"/infrastructure/onboarding/{TENANT_A}", headers=_as(TENANT_B)),
            client.post(f"/infrastructure/onboarding/{TENANT_A}/advance",
                        json={}, headers=_as(TENANT_B)),
        ):
            r = await call
            assert r.status_code in (403, 503), (
                f"cross-tenant onboarding accepted: {r.status_code} {r.text[:150]}"
            )


@pytest.mark.asyncio
class TestExecutiveCockpitIsolation:
    """The cockpit took tenant_id and ignored it in all four of its queries —
    including reading CostEvent for a HARDCODED "default" tenant."""

    async def test_cockpit_is_scoped_to_caller(self, client):
        r = await client.get("/dashboard/cockpit", headers=_as(TENANT_B))
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data["pioneer_alerts"] == [], "cockpit shows other tenants' signals"
        assert data["debate_queue"] == [], "cockpit shows other tenants' conflicts"
        assert data["org_readiness"] == [], "cockpit shows other tenants' readiness"

    async def test_cost_is_not_hardcoded_default_tenant(self, client):
        """Regression: cost telemetry was fetched for tenant "default"."""
        data = (await client.get("/dashboard/cockpit", headers=_as(TENANT_B))).json()
        cost = data.get("cost")
        if cost and isinstance(cost, dict) and "tenant_id" in cost:
            assert cost["tenant_id"] == TENANT_B, (
                f"cockpit reported tenant {cost['tenant_id']}'s spend to {TENANT_B}"
            )
