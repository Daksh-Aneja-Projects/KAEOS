"""
KAEOS E2E Test 19 — Governance & Enterprise Operations
Tests HITL governance surfaces, fairness auditing, temporal calendar,
webhooks lifecycle, event log, readiness probe, system stats, connector
lifecycle (connect/disconnect), conflict resolution, and the marketplace
template import.
"""
import pytest

from .conftest import BACKEND_ROOT  # derived from KAEOS_TEST_URL — never hardcode a port


@pytest.mark.asyncio
class TestGovernanceSurfaces:
    """HITL + fairness governance."""

    async def test_hitl_pending_queue(self, client):
        r = await client.get("/hitl/pending")
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data and "count" in data

    async def test_hitl_status_unknown_404(self, client):
        r = await client.get("/hitl/status/not-an-execution-id")
        assert r.status_code == 404

    async def test_hitl_resolve_unknown_404(self, client):
        r = await client.post("/hitl/resolve", json={
            "execution_id": "not-an-execution-id", "approved": True,
        })
        assert r.status_code == 404

    async def test_hitl_decision_feed(self, client):
        r = await client.get("/hitl/decision-feed")
        assert r.status_code == 200
        assert "decisions" in r.json()

    async def test_fairness_audit_log(self, client):
        r = await client.get("/fairness/audit-log?limit=20")
        assert r.status_code == 200


@pytest.mark.asyncio
class TestTemporalCalendar:
    """Temporal engine — calendar events CRUD + seasonality context."""

    async def test_calendar_create_list_delete(self, client):
        r = await client.post("/calendar/events", json={
            "name": "E2E Quarter Close",
            "calendar_type": "CUSTOM",
            "description": "End-of-quarter finance close window",
            "start_date": "2026-09-25T00:00:00",
            "end_date": "2026-09-30T23:59:59",
            "department": "finance",
            "priority_boost_pct": 25.0,
            "is_blocking": False,
        })
        assert r.status_code == 200, f"create → {r.status_code}: {r.text[:300]}"
        created = r.json()
        event_id = created.get("id") or created.get("event", {}).get("id")

        r2 = await client.get("/calendar/events")
        assert r2.status_code == 200
        events = r2.json().get("events", [])
        assert isinstance(events, list)

        if event_id:
            r3 = await client.delete(f"/calendar/events/{event_id}")
            assert r3.status_code == 200

    async def test_calendar_context(self, client):
        r = await client.get("/calendar/context?department=finance")
        assert r.status_code == 200
        data = r.json()
        assert "seasonality" in data
        assert "deadline_proximity" in data


@pytest.mark.asyncio
class TestWebhooksAndEvents:
    """Webhook subscriptions lifecycle + system event log."""

    async def test_webhook_create_list_delete(self, client):
        r = await client.post("/webhooks", json={
            "name": "E2E Hook",
            "endpoint": "https://example.com/e2e-hook",
            "events": ["rule.created", "skill.executed"],
        })
        assert r.status_code == 200, f"create → {r.status_code}: {r.text[:300]}"
        hook_id = r.json().get("id")
        assert hook_id, "Webhook create returned no id"

        r2 = await client.get("/webhooks")
        assert r2.status_code == 200
        subs = r2.json().get("subscriptions", [])
        assert any(s["id"] == hook_id for s in subs), "Created webhook not in list"

        r3 = await client.delete(f"/webhooks/{hook_id}")
        assert r3.status_code == 200

    async def test_webhook_unknown_event_rejected(self, client):
        r = await client.post("/webhooks", json={
            "name": "Bad Hook", "endpoint": "https://example.com/x",
            "events": ["not.an.event"],
        })
        assert r.status_code == 400

    async def test_events_log(self, client):
        r = await client.get("/events/log?limit=25")
        assert r.status_code == 200


@pytest.mark.asyncio
class TestSystemProbes:
    """Health, readiness, and stats."""

    async def test_ready_probe(self, client):
        r = await client.get("/ready")
        assert r.status_code == 200

    async def test_system_stats(self, client):
        r = await client.get("/system/stats")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    async def test_admin_api_keys_gated(self, client):
        """API-key bootstrap is disabled (503) without ADMIN_SECRET, never open."""
        r = await client.post(
            f"{BACKEND_ROOT}/admin/security/api-keys",
            params={"tenant_id": "tenant_probe", "name": "e2e"},
        )
        # 503 = ADMIN_SECRET unset (dev), 403 = set but wrong secret. Both prove the gate.
        assert r.status_code in (503, 403), f"Admin key endpoint unguarded: {r.status_code}"


@pytest.mark.asyncio
class TestConnectorLifecycle:
    """Connector connect / disconnect round-trip (admin-gated)."""

    async def test_connect_disconnect_roundtrip(self, client):
        data = (await client.get("/connectors")).json()
        available = [c for c in data.get("connectors", [])
                     if c.get("status") == "AVAILABLE"]
        if not available:
            pytest.skip("No AVAILABLE connectors to exercise connect/disconnect")
        conn_id = available[0]["id"]

        r = await client.post(f"/connectors/{conn_id}/connect")
        assert r.status_code == 200, f"connect → {r.status_code}: {r.text[:300]}"
        assert r.json()["status"] == "CONNECTED"

        r2 = await client.post(f"/connectors/{conn_id}/disconnect")
        assert r2.status_code == 200, f"disconnect → {r2.status_code}: {r2.text[:300]}"


@pytest.mark.asyncio
class TestConflictResolution:
    """Conflict case resolution."""

    async def test_resolve_open_conflict(self, client):
        data = (await client.get("/conflicts")).json()
        open_cases = [c for c in data.get("conflicts", [])
                      if c.get("status") in ("OPEN", "IN_REVIEW")]
        if not open_cases:
            pytest.skip("No open conflicts to resolve")
        case_id = open_cases[0]["id"]
        r = await client.post(f"/conflicts/{case_id}/resolve", json={
            "resolution_type": "MERGE",
            "resolution_note": "E2E: merged overlapping scopes into one rule",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestMarketplaceWrite:
    """Marketplace template creation."""

    async def test_create_marketplace_template(self, client):
        r = await client.post("/marketplace", json={
            "name": "E2E Test Pack",
            "category": "Testing",
            "description": "Created by the e2e suite to verify marketplace writes",
            "author": "E2E Suite",
            "tags": ["e2e", "testing"],
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
