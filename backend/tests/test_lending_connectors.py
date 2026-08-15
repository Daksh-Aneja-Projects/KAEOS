"""Credit bureau connector: never fabricates a score when unconfigured or
unreachable (honesty contract). No network calls - both cases return before
ever touching httpx."""
import pytest

from app.lending.connectors.credit_bureau import CreditBureauConnector


@pytest.mark.asyncio
async def test_pull_report_not_configured_without_credentials():
    conn = CreditBureauConnector("tenant_x", "experian", credentials=None)
    assert conn.configured is False
    result = await conn.pull_report("applicant-123")
    assert result["status"] == "not_configured"
    assert result["score"] is None
    assert result["note"]


@pytest.mark.asyncio
async def test_pull_report_not_configured_for_unknown_bureau():
    conn = CreditBureauConnector("tenant_x", "acme_credit", credentials={"api_key": "k"})
    result = await conn.pull_report("applicant-123")
    assert result["status"] == "not_configured"
    assert result["score"] is None


@pytest.mark.asyncio
async def test_test_connection_false_without_credentials():
    conn = CreditBureauConnector("tenant_x", "equifax", credentials={})
    assert await conn.test_connection() is False
