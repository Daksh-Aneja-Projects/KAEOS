"""KAEOS Operations Domain - Vendor Risk Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import run_gated_operations_skill
from app.operations.models.vendors import VendorContract, VendorPerformance
from app.services.json_utils import plain_facts


class VendorAgent:
    async def evaluate_vendor(self, db: AsyncSession, vendor_id: str, tenant_id: str) -> Dict[str, Any]:
        contract = (await db.execute(
            select(VendorContract).where(
                VendorContract.id == vendor_id, VendorContract.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not contract:
            raise ValueError(f"Vendor contract {vendor_id} not found")

        perf = (await db.execute(
            select(VendorPerformance)
            .where(VendorPerformance.vendor_contract_id == vendor_id,
                   VendorPerformance.tenant_id == tenant_id)
            .order_by(desc(VendorPerformance.created_at))
            .limit(1)
        )).scalar_one_or_none()

        facts = {
            "vendor_name": contract.vendor_name,
            "service_provided": contract.service_provided,
            "contract_value": contract.contract_value,
            "renewal_date": str(contract.renewal_date) if contract.renewal_date else None,
            "latest_delivery_rating": perf.delivery_rating if perf else None,
            "latest_sla_compliance_score": perf.sla_compliance_score if perf else None,
            "latest_overall_performance_score": perf.overall_performance_score if perf else None,
        }
        facts = plain_facts(facts)
        return await run_gated_operations_skill(
            skill_id="operations_vendor_risk",
            steps=[{"step": 1, "name": "Evaluate",
                    "prompt": f"Evaluate this vendor relationship for risk and renewal readiness: {facts}"}],
            context={
                "vendor_id": vendor_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {risk_level, renew_recommendation, concerns}.",
            },
            tenant_id=tenant_id,
        )
