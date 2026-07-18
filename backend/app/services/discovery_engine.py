"""
KAEOS Enterprise Discovery Engine
Phase 16: Enterprise Discovery
Automatically ingests data from Connectors (M365, Workday, Salesforce, ServiceNow)
and generates the Enterprise Twin (Graph nodes and edges).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.enterprise_graph import Team, Project, Vendor, Customer
from app.models.domain import Connector

logger = logging.getLogger(__name__)


class EnterpriseDiscoveryEngine:
    
    @staticmethod
    async def run_discovery_sync(db: AsyncSession, tenant_id: str):
        """
        Runs a full sync across all CONNECTED connectors for a tenant,
        extracting entities to populate the Enterprise Graph.
        """
        logger.info(f"Starting Enterprise Discovery Sync for tenant: {tenant_id}")
        
        # 1. Fetch connected connectors
        q = await db.execute(
            select(Connector)
            .where(Connector.tenant_id == tenant_id)
            .where(Connector.status == "CONNECTED")
        )
        connectors = q.scalars().all()
        
        if not connectors:
            logger.warning("No connected connectors found. Discovery aborted.")
            return {"status": "skipped", "reason": "no_connectors"}
            
        nodes_created = 0
        edges_created = 0
        
        for conn in connectors:
            logger.info(f"Discovering via {conn.name} ({conn.category})...")
            
            # Simulate pulling signals / data from the connector
            # In a real implementation, this would call the respective API (M365, Workday, etc.)
            # Here we mock the parsing logic based on connector category.
            
            if conn.category == "hris":
                # Discover Departments, Teams, Reporting Structure
                n, e = await EnterpriseDiscoveryEngine._process_hris_discovery(db, tenant_id, conn.id)
                nodes_created += n
                edges_created += e
                
            elif conn.category == "crm":
                # Discover Customers, Deals -> Projects
                n, e = await EnterpriseDiscoveryEngine._process_crm_discovery(db, tenant_id, conn.id)
                nodes_created += n
                edges_created += e
                
            elif conn.category == "finance":
                # Discover Vendors, Assets, Spend
                n, e = await EnterpriseDiscoveryEngine._process_finance_discovery(db, tenant_id, conn.id)
                nodes_created += n
                edges_created += e
                
            elif conn.category == "engineering" or conn.category == "support":
                # Discover Projects, Incidents -> Risks
                n, e = await EnterpriseDiscoveryEngine._process_ops_discovery(db, tenant_id, conn.id)
                nodes_created += n
                edges_created += e
                
        await db.commit()
        logger.info(f"Discovery Sync Complete: {nodes_created} nodes, {edges_created} edges created.")
        
        return {
            "status": "success",
            "nodes_created": nodes_created,
            "edges_created": edges_created
        }

    @staticmethod
    async def _process_hris_discovery(db: AsyncSession, tenant_id: str, connector_id: str):
        """Processes HR data (e.g., Workday) into Teams and Relationships."""
        # Mock implementation
        team = Team(tenant_id=tenant_id, department_id="hr_id", name="Discovered HR Team", description="Auto-discovered via HRIS")
        db.add(team)
        return 1, 0

    @staticmethod
    async def _process_crm_discovery(db: AsyncSession, tenant_id: str, connector_id: str):
        """Processes CRM data (e.g., Salesforce) into Customers and Opportunities."""
        # Mock implementation
        customer = Customer(tenant_id=tenant_id, name="Discovered Enterprise Client", arr=150000.0, segment="Enterprise")
        db.add(customer)
        return 1, 0
        
    @staticmethod
    async def _process_finance_discovery(db: AsyncSession, tenant_id: str, connector_id: str):
        """Processes ERP data (e.g., SAP) into Vendors and Budgets."""
        vendor = Vendor(tenant_id=tenant_id, name="Discovered Cloud Provider", service_provided="Infrastructure")
        db.add(vendor)
        return 1, 0
        
    @staticmethod
    async def _process_ops_discovery(db: AsyncSession, tenant_id: str, connector_id: str):
        """Processes Ops/Eng data (e.g., Jira/ServiceNow) into Projects and Risks."""
        project = Project(tenant_id=tenant_id, name="Discovered Migration Project", status="ACTIVE")
        db.add(project)
        return 1, 0
