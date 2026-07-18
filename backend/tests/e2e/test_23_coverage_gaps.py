"""
KAEOS E2E Test 23 — Coverage Gap Closure
Closes the gaps found in the 2026-07-15 route-coverage audit:
- Enterprise router health (/api/v1/health — distinct from app-root /health)
- Bare provenance chain GET /provenance/{rule_id}
- Finance vendor detail GET /finance/vendors/{vendor_id}
- Debate transcript detail GET /agents/debates/{execution_id}
- Activity feed POST /agents/activity-feed/mark-read
- Fairness POST /fairness/override/{log_id} (admin-gated)
- Generic HITL POST /hitl/{execution_id}/approve|reject (hitl_manager-backed,
  a separate system from the DB-backed /skills/hitl/* pair)
- HR HITL POST /hr/hitl/{execution_id}/approve|reject
- Admin API-key bootstrap POST/DELETE /admin/security/api-keys (ADMIN_SECRET guard)
- WebSocket live feed /ws/{tenant_id} (connect, ping/pong, subscribe, error)
"""
import asyncio
import json
import os
import pytest

from .conftest import BACKEND_ROOT, WS_ROOT  # derived from KAEOS_TEST_URL

TENANT = "tenant_acme"


def _admin_secret() -> str:
    """Resolve ADMIN_SECRET the same way the backend does (env, then backend/.env)."""
    secret = os.environ.get("ADMIN_SECRET", "")
    if secret:
        return secret
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ADMIN_SECRET="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


@pytest.mark.asyncio
class TestEnterpriseHealth:
    """GET /api/v1/health — enterprise router health, not the app-root probe."""

    async def test_api_v1_health(self, client):
        r = await client.get("/health")
        assert r.status_code == 200, f"GET /health → {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data.get("status") == "healthy"
        assert "timestamp" in data


@pytest.mark.asyncio
class TestProvenanceChain:
    """GET /provenance/{rule_id} — bare per-rule lineage chain."""

    async def test_chain_for_seeded_rule(self, client):
        rules = (await client.get("/rules")).json()
        rule_list = rules if isinstance(rules, list) else rules.get("rules", [])
        assert rule_list, "No seeded rules found"
        rule_id = rule_list[0]["id"]

        r = await client.get(f"/provenance/{rule_id}")
        assert r.status_code == 200, f"GET /provenance/{{id}} → {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "chain" in data and isinstance(data["chain"], list)

    async def test_chain_entries_serialize_when_ledger_populated(self, client):
        """If the global ledger has entries, the per-rule chain must serialize them."""
        ledger = (await client.get("/provenance/global/ledger")).json()
        entries = ledger.get("ledger") or ledger.get("entries") or []
        if not entries:
            pytest.skip("Provenance ledger empty — nothing to verify")
        # Concurrent tests append non-rule events (skill executions) whose
        # rule_id yields an empty per-rule chain - verify against entries that
        # are actually rule-scoped, not just whichever landed last.
        candidates = [e.get("rule_id") for e in entries if e.get("rule_id")][:5]
        if not candidates:
            pytest.skip("No rule-scoped ledger entries at this moment")
        chain = None
        for rule_id in candidates:
            r = await client.get(f"/provenance/{rule_id}")
            assert r.status_code == 200, f"chain fetch → {r.status_code}: {r.text[:200]}"
            c = r.json()["chain"]
            assert isinstance(c, list)
            if c:
                chain = c
                break
        assert chain, "Expected at least one ledgered rule with a non-empty chain"
        assert "chain_hash" in chain[0]


@pytest.mark.asyncio
class TestFinanceVendorDetail:
    """GET /finance/vendors/{vendor_id} — detail view of a seeded vendor."""

    async def test_vendor_detail(self, client):
        vendors = (await client.get("/finance/vendors")).json()
        assert isinstance(vendors, list) and vendors, "No seeded vendors"
        vid = vendors[0]["id"]

        r = await client.get(f"/finance/vendors/{vid}")
        assert r.status_code == 200, f"vendor detail → {r.status_code}: {r.text[:200]}"
        v = r.json()
        assert v["id"] == vid
        for key in ("code", "name", "status", "payment_terms", "address"):
            assert key in v, f"Missing '{key}' in vendor detail. Keys: {list(v.keys())}"

    async def test_vendor_detail_unknown_404(self, client):
        r = await client.get("/finance/vendors/not-a-vendor-id")
        assert r.status_code == 404


@pytest.mark.asyncio
class TestDebateTranscriptDetail:
    """GET /agents/debates/{execution_id} — full transcript for one debate."""

    async def test_debate_detail_from_recent(self, client):
        recent = (await client.get("/agents/debates/recent")).json()
        transcripts = recent.get("transcripts", [])
        if not transcripts:
            pytest.skip("No debate transcripts recorded yet")
        exec_id = transcripts[0]["execution_id"]

        r = await client.get(f"/agents/debates/{exec_id}")
        assert r.status_code == 200, f"debate detail → {r.status_code}: {r.text[:200]}"
        d = r.json()
        for key in ("proposer", "advocate", "arbitrator", "skill_id"):
            assert key in d, f"Missing '{key}' in debate detail. Keys: {list(d.keys())}"

    async def test_debate_detail_unknown_404(self, client):
        r = await client.get("/agents/debates/not-an-execution-id")
        assert r.status_code == 404


@pytest.mark.asyncio
class TestActivityFeedMarkRead:
    """POST /agents/activity-feed/mark-read — the feed's only mutation."""

    async def test_mark_read_flow(self, client):
        unread = (await client.get("/agents/activity-feed?limit=5&unread_only=true")).json()
        events = unread.get("events", [])
        if not events:
            # Nothing unread — still verify the endpoint accepts an empty batch
            r = await client.post("/agents/activity-feed/mark-read", json={"event_ids": []})
            assert r.status_code == 200
            assert r.json().get("marked") == 0
            return

        target_id = events[0]["id"]
        r = await client.post("/agents/activity-feed/mark-read", json={"event_ids": [target_id]})
        assert r.status_code == 200, f"mark-read → {r.status_code}: {r.text[:200]}"
        assert r.json().get("marked", 0) >= 1

        # The event must no longer appear in the unread feed
        after = (await client.get("/agents/activity-feed?limit=50&unread_only=true")).json()
        assert target_id not in [e["id"] for e in after.get("events", [])]


@pytest.mark.asyncio
class TestFairnessOverride:
    """POST /fairness/override/{log_id} — admin-gated audited override."""

    async def test_override_unknown_404(self, client):
        r = await client.post("/fairness/override/not-a-log-id", json={
            "override_by": "e2e_test", "justification": "negative-path check",
        })
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"

    async def test_override_real_log(self, client):
        logs = (await client.get("/fairness/audit-log?limit=20")).json().get("logs", [])
        if not logs:
            pytest.skip("No fairness audit logs recorded yet")
        # Prefer a log not yet overridden so the mutation is observable
        target = next((l for l in logs if not l.get("was_overridden")), logs[0])

        r = await client.post(f"/fairness/override/{target['id']}", json={
            "override_by": "e2e_test",
            "justification": "E2E verification of the override path",
        })
        assert r.status_code == 200, f"override → {r.status_code}: {r.text[:300]}"
        assert r.json().get("status") == "overridden"

        refreshed = (await client.get("/fairness/audit-log?limit=50")).json().get("logs", [])
        match = next((l for l in refreshed if l["id"] == target["id"]), None)
        assert match is not None
        assert match["was_overridden"] is True
        assert match["override_by"] == "e2e_test"


@pytest.mark.asyncio
class TestGenericHitlApproveReject:
    """POST /hitl/{execution_id}/approve|reject — hitl_manager-backed pair."""

    async def test_approve_unknown_404(self, client):
        r = await client.post("/hitl/not-an-execution-id/approve", json={
            "reason": "negative path", "approver": "e2e_test",
        })
        assert r.status_code == 404

    async def test_reject_unknown_404(self, client):
        r = await client.post("/hitl/not-an-execution-id/reject", json={
            "reason": "negative path", "approver": "e2e_test",
        })
        assert r.status_code == 404

    async def test_approve_pending_if_any(self, client):
        """Opportunistic positive path: approve a live pending HITL entry if one exists."""
        pending = (await client.get("/hitl/pending")).json().get("pending", [])
        if not pending:
            pytest.skip("No pending hitl_manager entries (gate-7 escalations) at this moment")
        exec_id = pending[0].get("execution_id") or pending[0].get("exec_id") or pending[0].get("id")

        r = await client.post(f"/hitl/{exec_id}/approve", json={
            "reason": "E2E approval", "approver": "e2e_test",
        })
        assert r.status_code == 200, f"approve → {r.status_code}: {r.text[:300]}"
        assert r.json().get("status") == "approved"

        status = (await client.get(f"/hitl/status/{exec_id}")).json()
        assert status.get("status") in ("RESOLVED", "APPROVED", "RESUMED", "COMPLETED"), status


@pytest.mark.asyncio
class TestHrHitlApproveReject:
    """POST /hr/hitl/{execution_id}/approve|reject — HR-scoped HITL pair."""

    async def test_hr_approve_unknown_404(self, client):
        r = await client.post("/hr/hitl/not-an-execution-id/approve", json={
            "reason": "negative path", "approver": "e2e_test",
        })
        assert r.status_code == 404

    async def test_hr_reject_unknown_404(self, client):
        r = await client.post("/hr/hitl/not-an-execution-id/reject", json={
            "reason": "negative path", "approver": "e2e_test",
        })
        assert r.status_code == 404


@pytest.mark.asyncio
class TestAdminApiKeyBootstrap:
    """POST/DELETE /admin/security/api-keys — ADMIN_SECRET-guarded, app-root mounted."""

    async def test_create_rejected_without_secret(self, client):
        r = await client.post(
            f"{BACKEND_ROOT}/admin/security/api-keys",
            params={"tenant_id": TENANT, "name": "e2e-probe"},
        )
        # 403 when ADMIN_SECRET configured, 503 when disabled — never success
        assert r.status_code in (403, 503), f"guard must reject: {r.status_code}"

    async def test_create_rejected_with_wrong_secret(self, client):
        r = await client.post(
            f"{BACKEND_ROOT}/admin/security/api-keys",
            params={"tenant_id": TENANT, "name": "e2e-probe"},
            headers={"X-Admin-Secret": "definitely-wrong-secret"},
        )
        assert r.status_code in (403, 503)

    async def test_full_key_lifecycle_with_secret(self, client):
        secret = _admin_secret()
        if not secret:
            pytest.skip("ADMIN_SECRET not resolvable — cannot exercise positive path")

        r = await client.post(
            f"{BACKEND_ROOT}/admin/security/api-keys",
            params={"tenant_id": TENANT, "name": "e2e-lifecycle", "role": "operator"},
            headers={"X-Admin-Secret": secret},
        )
        assert r.status_code == 200, f"create key → {r.status_code}: {r.text[:300]}"
        key_data = r.json()
        assert key_data.get("api_key", "").startswith("kt_")
        assert key_data.get("tenant_id") == TENANT
        key_id = key_data["key_id"]

        # The freshly minted key must authenticate a real API call
        r2 = await client.get("/rules", headers={"Authorization": f"Bearer {key_data['api_key']}"})
        assert r2.status_code == 200, f"kt_ key auth → {r2.status_code}: {r2.text[:200]}"

        r3 = await client.delete(
            f"{BACKEND_ROOT}/admin/security/api-keys/{key_id}",
            headers={"X-Admin-Secret": secret},
        )
        assert r3.status_code == 200, f"revoke → {r3.status_code}: {r3.text[:200]}"


@pytest.mark.asyncio
class TestWebSocketLiveFeed:
    """WS /ws/{tenant_id} — connect handshake, ping/pong, subscribe, error path."""

    @staticmethod
    async def _recv_until(ws, expected_type: str, timeout: float = 15.0) -> dict:
        """Drain broadcast noise until a control frame of expected_type arrives."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"No '{expected_type}' frame within {timeout}s")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == expected_type:
                return msg

    async def test_ws_control_protocol(self, client):
        websockets = pytest.importorskip("websockets")

        uri = f"{WS_ROOT}/ws/{TENANT}"
        async with websockets.connect(uri, open_timeout=15) as ws:
            connected = await self._recv_until(ws, "connected")
            assert connected["tenant_id"] == TENANT

            await ws.send(json.dumps({"type": "ping"}))
            pong = await self._recv_until(ws, "pong")
            assert "timestamp" in pong

            await ws.send(json.dumps({"type": "subscribe", "channels": ["activity_feed", "hitl_required"]}))
            sub = await self._recv_until(ws, "subscribed")
            assert sub["channels"] == ["activity_feed", "hitl_required"]

            await ws.send(json.dumps({"type": "bogus_control"}))
            err = await self._recv_until(ws, "error")
            assert "bogus_control" in err.get("message", "")

    async def test_ws_plaintext_ping(self, client):
        websockets = pytest.importorskip("websockets")

        uri = f"{WS_ROOT}/ws/{TENANT}"
        async with websockets.connect(uri, open_timeout=15) as ws:
            await self._recv_until(ws, "connected")
            await ws.send("ping")
            deadline = asyncio.get_event_loop().time() + 15
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                assert remaining > 0, "No plaintext 'pong' within 15s"
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                if raw == "pong":
                    break
