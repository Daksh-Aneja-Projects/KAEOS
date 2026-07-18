"""
KAEOS E2E Test 20 — Deep Domain Actions
Covers the remaining department functionality not exercised by tests 02–07:
HR candidate stage advancement, finance chart-of-accounts / expense items /
AR dunning, support ticket documentation, sales CPQ + commission payout,
operations resource-allocation checks, reality-twin decisions/simulation,
and the copilot chat stream.
"""
import pytest


@pytest.mark.asyncio
class TestHRDeepActions:
    """HR — candidate funnel state machine."""

    async def test_candidate_advance_stage(self, client):
        """A freshly created candidate advances forward through the funnel."""
        reqs = (await client.get("/hr/requisitions")).json()
        if not reqs:
            pytest.skip("No requisitions to attach a candidate to")
        r = await client.post("/hr/candidates", json={
            "requisition_id": reqs[0]["id"],
            "first_name": "E2E",
            "last_name": "StageWalker",
            "email": "e2e.stagewalker@example.com",
        })
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:200]}"
        cand_id = r.json()["id"]

        # Forward transition APPLIED → RECRUITER_SCREEN
        r2 = await client.post(f"/hr/candidates/{cand_id}/advance",
                               json={"target_stage": "RECRUITER_SCREEN"})
        assert r2.status_code == 200, f"{r2.status_code}: {r2.text[:300]}"

        # Backward transition must be rejected with 409
        r3 = await client.post(f"/hr/candidates/{cand_id}/advance",
                               json={"target_stage": "APPLIED"})
        assert r3.status_code == 409

    async def test_candidate_advance_invalid_stage_422(self, client):
        candidates = (await client.get("/hr/candidates")).json()
        if not candidates:
            pytest.skip("No candidates")
        r = await client.post(f"/hr/candidates/{candidates[0]['id']}/advance",
                              json={"target_stage": "NOT_A_STAGE"})
        assert r.status_code == 422


@pytest.mark.asyncio
class TestFinanceDeepActions:
    """Finance — CoA, expense items, AR dunning agent."""

    async def test_chart_of_accounts(self, client):
        r = await client.get("/finance/chart-of-accounts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_expense_report_items(self, client):
        reports = (await client.get("/finance/expense-reports")).json()
        if not reports:
            pytest.skip("No expense reports seeded")
        r = await client.get(f"/finance/expense-reports/{reports[0]['id']}/items")
        assert r.status_code == 200

    async def test_ar_dunning_agent(self, client, has_ollama):
        """AR agent generates a dunning letter for a receivable (real Ollama)."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        receivables = (await client.get("/finance/receivables")).json()
        if not receivables:
            pytest.skip("No receivables seeded")
        r = await client.post(f"/finance/receivables/{receivables[0]['id']}/dunning")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert "letter" in r.json()


@pytest.mark.asyncio
class TestSupportDeepActions:
    """Support — knowledge documentation agent."""

    async def test_ticket_document_agent(self, client, has_ollama):
        """Documentation agent turns a resolved ticket into a KB draft."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        tickets = (await client.get("/support/tickets")).json()
        if not tickets:
            pytest.skip("No tickets seeded")
        r = await client.post(f"/support/tickets/{tickets[0]['id']}/document")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestSalesDeepActions:
    """Sales — CPQ guardrails and commission payout."""

    async def test_cpq_quote_evaluation(self, client, has_ollama):
        opps = (await client.get("/sales/opportunities")).json()
        if not opps:
            pytest.skip("No opportunities seeded")
        r = await client.post(f"/sales/opportunities/{opps[0]['id']}/cpq?discount=12.5")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    @pytest.mark.ollama
    async def test_commission_payout(self, client):
        """Commission agent calculates payout for the seeded calculation."""
        # Read the id through the API, not by opening kaeos.db directly: the
        # old version hardcoded the SQLite file, so it silently tested nothing
        # (or the WRONG database) whenever the backend ran on Postgres.
        calcs = (await client.get("/sales/commission")).json()
        if not calcs:
            pytest.skip("No seeded commission calculation found")
        calc_id = calcs[0]["id"]
        r = await client.post(f"/sales/commission/{calc_id}/payout")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestOperationsDeepActions:
    """Operations — resource allocation overload check."""

    async def test_resource_allocation_check(self, client, has_ollama):
        allocations = (await client.get("/operations/resources")).json()
        if not allocations:
            pytest.skip("No resource allocations seeded")
        r = await client.post(
            f"/operations/resources/allocations/{allocations[0]['id']}/check")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestRealityTwinDeep:
    """Reality twin — decisions log and scripted simulation."""

    async def test_reality_decisions(self, client):
        r = await client.get("/reality/decision")
        assert r.status_code == 200
        assert "decisions" in r.json()

    async def test_reality_full_simulation(self, client, has_ollama):
        """Scripted shock simulation against the busiest department."""
        r = await client.post("/reality/simulate")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestCopilotChat:
    """Copilot chat — SSE stream produces tokens from the real LLM."""

    async def test_chat_stream(self, client, has_ollama):
        if not has_ollama:
            pytest.skip("Ollama not running")
        async with client.stream("POST", "/chat/stream", json={
            "messages": [{"role": "user", "content": "How many rules are active?"}],
        }) as r:
            assert r.status_code == 200
            content_type = r.headers.get("content-type", "")
            assert "text/event-stream" in content_type
            # Read the first few bytes of the stream to prove it produces data
            got_data = False
            async for chunk in r.aiter_text():
                if chunk.strip():
                    got_data = True
                    break
            assert got_data, "Chat stream produced no data"

    async def test_chat_stream_empty_messages(self, client):
        """Empty message list yields a graceful done event."""
        r = await client.post("/chat/stream", json={"messages": []})
        assert r.status_code == 200
