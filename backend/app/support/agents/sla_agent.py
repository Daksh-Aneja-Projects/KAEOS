"""KAEOS Support Domain - SLA Monitor Agent

Grounded on the SAME live per-policy SLA computation the GET /sla/metrics
endpoint serves (breaches derived from each ticket's first_response_at /
resolved_at against the policy target), NOT the sup_sla_breaches table - which
no code path ever writes, so the agent used to read zero breaches and always
concluded "healthy" while /sla/metrics could report BREACHED off the same data.
"""
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import run_gated_support_skill
from app.services.json_utils import plain_facts


def _summarize_breaches(metrics: list[dict]) -> Dict[str, Any]:
    """Fold live per-policy SLA metrics into breach facts. breached_count is
    None for NO_DATA policies, so coerce it to zero before summing."""
    return {
        "policies_in_breach": [m["policy"] for m in metrics if m["status"] == "BREACHED"],
        "total_breached_tickets": sum((m.get("breached_count") or 0) for m in metrics),
        "policies_measured": sum(1 for m in metrics if m["status"] != "NO_DATA"),
    }


class SLAAgent:
    async def check_sla(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        # Reuse the endpoint's live computation so the agent and /sla/metrics can
        # never disagree. Imported lazily: the router imports this module, so a
        # module-level import back into it would be circular.
        from app.support.api.v1.router import compute_sla_policy_metrics
        metrics = await compute_sla_policy_metrics(db, tenant_id)

        facts = {
            "policies": [
                {"policy": m["policy"], "priority": m["priority"], "status": m["status"],
                 "target_hours": m["target_hours"], "actual_hours": m["actual_hours"],
                 "compliance_pct": m["compliance_pct"], "breached_count": m["breached_count"]}
                for m in metrics
            ],
            **_summarize_breaches(metrics),
        }
        facts = plain_facts(facts)
        return await run_gated_support_skill(
            skill_id="support_sla_monitor",
            steps=[{"step": 1, "name": "Check",
                    "prompt": f"Review SLA posture from these live per-policy metrics "
                              f"and breach counts: {facts}"}],
            context={
                "tenant_id": tenant_id, **facts,
                # GDPR/CCPA lawful basis for the Gate 6 post-execution audit.
                "legal_basis": "legitimate_interests:customer_support",
                "instruction": "Output strict JSON: {sla_health, worst_breaches, actions}.",
            },
            tenant_id=tenant_id,
        )


if __name__ == "__main__":
    # Self-check: the None-coercion and BREACHED filter are the only non-trivial
    # logic here, so prove they hold.
    _m = [
        {"policy": "Gold", "status": "BREACHED", "breached_count": 3},
        {"policy": "Silver", "status": "MET", "breached_count": 0},
        {"policy": "Bronze", "status": "NO_DATA", "breached_count": None},
    ]
    _s = _summarize_breaches(_m)
    assert _s["policies_in_breach"] == ["Gold"], _s
    assert _s["total_breached_tickets"] == 3, _s          # None coerced to 0
    assert _s["policies_measured"] == 2, _s               # NO_DATA excluded
    print("SLA breach summary self-check passed")
