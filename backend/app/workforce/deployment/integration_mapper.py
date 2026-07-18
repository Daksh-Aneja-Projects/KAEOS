"""
KAEOS Workforce Layer — Connector Health Check + Integration Mapper

Provides the two pieces of *real* deployment work that previously stood in for
``asyncio.sleep`` placeholders in the deployment pipeline:

  * :class:`ConnectorHealthChecker` — probes the tenant's connected systems and
    reports which are reachable/configured.
  * :class:`IntegrationMapper` — expands a domain pack's ``required_integrations``
    into ``IntegrationRequirement`` rows and marks each satisfied when a connected
    system covers its category (idempotent per department).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Connector
from app.workforce.models.integration import IntegrationRequirement

logger = logging.getLogger(__name__)

# Connector statuses we treat as usable.
_HEALTHY_STATUSES = {"CONNECTED", "SYNCING", "AVAILABLE"}


class ConnectorHealthChecker:
    """Checks the health of the systems referenced by a deployment."""

    @staticmethod
    async def check(db: AsyncSession, tenant_id: str, connected_systems: List[str]) -> Dict[str, Any]:
        """Return a per-system health report.

        ``connected_systems`` may contain connector ids or names. Systems with no
        matching connector row are reported as ``not_connected`` (an honest result,
        not a simulated pass).
        """
        report: List[Dict[str, Any]] = []
        healthy = 0

        for system in connected_systems or []:
            # Resolve by id first, then by (case-insensitive) name.
            res = await db.execute(select(Connector).where(Connector.id == system))
            connector = res.scalar_one_or_none()
            if connector is None:
                res = await db.execute(
                    select(Connector).where(
                        Connector.tenant_id == tenant_id,
                        Connector.name.ilike(str(system)),
                    )
                )
                connector = res.scalar_one_or_none()

            if connector is None:
                report.append({"system": system, "status": "not_connected", "healthy": False})
                continue

            is_healthy = (connector.status or "").upper() in _HEALTHY_STATUSES
            if is_healthy:
                healthy += 1
            report.append({
                "system": connector.name,
                "connector_id": connector.id,
                "category": connector.category,
                "status": connector.status,
                "healthy": is_healthy,
            })

        return {
            "systems": report,
            "total": len(report),
            "healthy": healthy,
            "all_healthy": len(report) > 0 and healthy == len(report),
        }


class IntegrationMapper:
    """Maps a domain pack's required integrations to connected sources."""

    @staticmethod
    async def map(
        db: AsyncSession,
        tenant_id: str,
        department_id: str,
        required_integrations: List[Dict[str, Any]],
        connected_systems: List[str],
    ) -> Dict[str, Any]:
        """Create/refresh IntegrationRequirement rows and mark satisfied ones.

        Idempotent: existing requirements for the department are reused rather
        than duplicated.
        """
        # Preload connectors for this tenant to match against requirements.
        conn_res = await db.execute(select(Connector).where(Connector.tenant_id == tenant_id))
        connectors = conn_res.scalars().all()
        connected_ids = {str(s) for s in (connected_systems or [])}

        # Existing requirements for idempotency.
        existing_res = await db.execute(
            select(IntegrationRequirement).where(
                IntegrationRequirement.department_id == department_id
            )
        )
        existing = {r.category: r for r in existing_res.scalars().all()}

        mapped, satisfied_count = [], 0
        for req in required_integrations or []:
            category = req.get("category", "unknown")
            examples = [e.lower() for e in req.get("examples", [])]

            # Find a connected system that covers this category.
            match = None
            for c in connectors:
                is_connected = c.id in connected_ids or c.name in connected_ids
                covers_category = (c.category or "").lower() == category.lower() or \
                    (c.name or "").lower() in examples
                if is_connected and covers_category:
                    match = c
                    break

            record = existing.get(category)
            if record is None:
                record = IntegrationRequirement(
                    tenant_id=tenant_id,
                    department_id=department_id,
                    category=category,
                    examples=req.get("examples", []),
                    data_provided=req.get("data_provided", []),
                )
                db.add(record)

            if match is not None:
                record.is_satisfied = "true"
                record.satisfied_by_connector_id = match.id
                record.satisfied_by_name = match.name
                satisfied_count += 1
            else:
                record.is_satisfied = "false"

            mapped.append({
                "category": category,
                "satisfied": record.is_satisfied == "true",
                "satisfied_by": record.satisfied_by_name,
                "data_provided": req.get("data_provided", []),
            })

        await db.commit()
        return {
            "mappings": mapped,
            "required": len(mapped),
            "satisfied": satisfied_count,
            "fully_satisfied": len(mapped) > 0 and satisfied_count == len(mapped),
        }
