from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.operations.agents.gated_runner import run_gated_operations_skill

class ResourceAgent:
    async def check_resources(self, db: AsyncSession, resource_id: str, tenant_id: str) -> Dict[str, Any]:
        result = await run_gated_operations_skill(
            skill_id="operations_resource_check",
            steps=[{"step": 1, "name": "Check", "prompt": f"Check resource {resource_id}"}],
            context={"resource_id": resource_id, "tenant_id": tenant_id},
            tenant_id=tenant_id,
        )
        return result

    async def check_overload(self, db: AsyncSession, allocation_id: str, tenant_id: str) -> Dict[str, Any]:
        """Evaluate a specific allocation for utilization overload."""
        from sqlalchemy import select
        from app.operations.models.resources import Resource, ResourceAllocation

        alloc = (await db.execute(
            select(ResourceAllocation).where(
                ResourceAllocation.id == allocation_id,
                ResourceAllocation.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not alloc:
            raise ValueError(f"Allocation {allocation_id} not found")

        resource = (await db.execute(
            select(Resource).where(
                Resource.id == alloc.resource_id, Resource.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        # None means "unknown", not "0% utilized" — track it so overload isn't
        # reported False for an allocation whose true utilization we don't have.
        util_known = alloc.utilization_percentage is not None
        utilization = float(alloc.utilization_percentage) if util_known else 0.0

        result = await run_gated_operations_skill(
            skill_id="operations_overload_check",
            steps=[{
                "step": 1, "name": "Assess Overload",
                "prompt": (
                    f"Resource '{resource.name if resource else alloc.resource_id}' is allocated "
                    f"at {utilization}% utilization. Assess overload risk and recommend rebalancing."
                ),
            }],
            context={"allocation_id": allocation_id, "utilization": utilization,
                     "tenant_id": tenant_id},
            tenant_id=tenant_id,
        )
        result["allocation_id"] = allocation_id
        result["utilization"] = utilization if util_known else None
        # >= 100% is at capacity, which is overloaded; unknown utilization is
        # flagged for review, never reported as safely under-utilized.
        result["overloaded"] = bool(util_known and utilization >= 100)
        result["utilization_known"] = util_known
        return result
