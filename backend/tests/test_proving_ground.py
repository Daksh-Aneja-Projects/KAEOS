"""Governance Proving Ground — the Assurance Score is a CI regression gate.

If any gate regresses (stops blocking a known-bad action), that attack escapes
and the Assurance Score drops below 1.0 — failing this test. The 'teeth' test
proves the battery actually detects a regression rather than always reading green.
"""
import pytest

from app.services import proving_ground
from app.services.proving_ground import run_battery


def test_battery_is_perfect_on_clean_tree():
    """Every known-bad action in the versioned battery is CAUGHT by the live
    gates. A drop here means a governance control silently stopped blocking."""
    r = run_battery()
    assert r["total"] >= 10, "battery too small to be meaningful"
    assert r["perfect"], f"gates let known-bad actions through: {r['escaped']}"
    assert r["assurance_score"] == 1.0


def test_battery_covers_multiple_departments_and_gates():
    r = run_battery()
    depts = {x["department"] for x in r["results"]}
    gates = {x["gate"] for x in r["results"]}
    assert len(depts) >= 5, f"battery too narrow across departments: {depts}"
    # Beyond the compliance registry, the kernel gates must be probed too.
    assert "prompt_guard" in gates and "consequence" in gates


def test_battery_has_teeth_detects_a_regressed_gate(monkeypatch):
    """Simulate the compliance pipeline regressing to always-verified; the
    compliance attacks must then ESCAPE and the score must fall below 1.0."""
    monkeypatch.setattr(proving_ground, "run_checks",
                        lambda tags, ctx: {"verified": True, "blocking": [], "results": []})
    r = run_battery()
    assert not r["perfect"], "a neutered compliance pipeline must be detected"
    assert r["assurance_score"] < 1.0
    escaped_gates = {e["gate"] for e in r["escaped"]}
    assert any(g.startswith("compliance:") for g in escaped_gates)


@pytest.mark.asyncio
async def test_proving_ground_endpoints(async_client):
    r = await async_client.get("/api/v1/proving-ground/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assurance_score"] == 1.0 and body["perfect"] is True

    s = await async_client.get("/api/v1/proving-ground/scenarios")
    assert s.status_code == 200
    assert len(s.json()["scenarios"]) == body["total"]
