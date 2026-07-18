"""
KAEOS Enterprise Discovery Engine
Phase 16
Automatically discovers Enterprise Twin topology from external connectors.
"""

import logging
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.graph.graph_service import GraphService

logger = logging.getLogger(__name__)


class EnterpriseDiscoveryEngine:
    
    def __init__(self, graph_service: GraphService):
        self.graph = graph_service

    async def run_discovery(self, db: AsyncSession, tenant_id: str, connector_id: str, connector_type: str, raw_payload: List[Dict[str, Any]]):
        """
        Parses payload from an external connector and auto-generates the Enterprise Graph.
        """
        logger.info(f"DiscoveryEngine: Running discovery for {tenant_id} via {connector_type}")
        
        if connector_type == "WORKDAY":
            await self._discover_workday_hierarchy(tenant_id, raw_payload)
        elif connector_type == "SALESFORCE":
            await self._discover_salesforce_accounts(tenant_id, raw_payload)
        elif connector_type == "JIRA":
            await self._discover_jira_projects(tenant_id, raw_payload)
        else:
            logger.warning(f"Unsupported discovery type: {connector_type}")

    async def _discover_workday_hierarchy(self, tenant_id: str, payload: List[Dict[str, Any]]):
        """
        Maps Workday employee/department data to Enterprise Graph nodes.
        """
        for item in payload:
            emp_id = f"emp_{item.get('employee_id')}"
            dept_id = f"dept_{item.get('department_id')}"
            manager_id = f"emp_{item.get('manager_id')}"
            
            # Register Department
            await self.graph.register_entity(dept_id, "Department", {"name": item.get("department_name")})
            
            # Register Employee
            await self.graph.register_entity(emp_id, "Employee", {
                "name": item.get("name"),
                "title": item.get("title")
            })
            
            # Map Hierarchy
            await self.graph.link_entities(emp_id, dept_id, "WORKS_IN")
            if item.get("manager_id"):
                await self.graph.link_entities(emp_id, manager_id, "REPORTS_TO")

    async def _discover_salesforce_accounts(self, tenant_id: str, payload: List[Dict[str, Any]]):
        for item in payload:
            acc_id = f"cust_{item.get('account_id')}"
            await self.graph.register_entity(acc_id, "Customer", {"name": item.get("name"), "arr": item.get("arr")})
            
            # Link to sales department
            await self.graph.link_entities(acc_id, "dept_sales", "OWNED_BY")

    async def _discover_jira_projects(self, tenant_id: str, payload: List[Dict[str, Any]]):
        for item in payload:
            proj_id = f"proj_{item.get('project_id')}"
            await self.graph.register_entity(proj_id, "Project", {"name": item.get("name"), "status": item.get("status")})
            
            # Link dependencies if available
            for dep in item.get("dependencies", []):
                await self.graph.link_entities(proj_id, f"proj_{dep}", "DEPENDS_ON")
