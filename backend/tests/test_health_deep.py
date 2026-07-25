"""Health probes — fast readiness by default, opt-in deep dependency probe."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_health_fast_is_ok(async_client):
    r = await async_client.get("/health")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "backends" in body
    # The fast probe must NOT include the deep dependency section.
    assert "dependencies" not in body


async def test_health_live_is_always_ok(async_client):
    r = await async_client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_health_deep_probes_dependencies(async_client):
    r = await async_client.get("/health?deep=true")
    assert r.status_code in (200, 503)
    deps = r.json().get("dependencies")
    assert isinstance(deps, dict)
    # Both non-critical dependencies are reported (available true/false), never crash.
    assert "redis" in deps and "available" in deps["redis"]
    assert "llm" in deps and "available" in deps["llm"]
