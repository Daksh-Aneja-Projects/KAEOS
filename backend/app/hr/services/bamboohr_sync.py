"""
KAEOS HR Vertical — BambooHR Sync Service

Orchestrates syncing data from BambooHR into the KAEOS Core HR models.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.hr.connectors.bamboohr import BambooHRConnector
from app.hr.models.core import HREmployee, EmploymentStatus

logger = logging.getLogger(__name__)

class BambooHRSyncService:
    
    @staticmethod
    async def sync_employees(db: AsyncSession, tenant_id: str, subdomain: str, api_key: str):
        """Pulls all employees from BambooHR and upserts them into the KAEOS HR database."""
        connector = BambooHRConnector(tenant_id, subdomain, api_key)
        
        logger.info(f"Starting BambooHR employee sync for tenant {tenant_id}")
        raw_employees = await connector.get_employees()
        
        synced_count = 0
        for emp_data in raw_employees:
            bamboo_id = str(emp_data.get("id"))
            
            # Fetch detailed data for full mapping
            try:
                details = await connector.get_employee_details(bamboo_id)
            except Exception as e:
                logger.warning(f"Could not fetch details for {bamboo_id}, skipping. {e}")
                continue
                
            email = details.get("workEmail")
            if not email:
                continue # We require email as unique identifier
                
            # Upsert into Employee table
            q = await db.execute(
                select(HREmployee).where(HREmployee.tenant_id == tenant_id).where(HREmployee.email == email)
            )
            employee = q.scalar_one_or_none()
            
            status_map = {
                "Active": EmploymentStatus.ACTIVE,
                "Inactive": EmploymentStatus.TERMINATED,
            }
            mapped_status = status_map.get(details.get("status"), EmploymentStatus.ACTIVE)
            
            # Parse Dates
            hire_date = None
            if details.get("hireDate") and details.get("hireDate") != "0000-00-00":
                hire_date = datetime.strptime(details.get("hireDate"), "%Y-%m-%d").date()
                
            if not employee:
                employee = HREmployee(
                    tenant_id=tenant_id,
                    worker_id=bamboo_id,
                    first_name=details.get("firstName", "Unknown"),
                    last_name=details.get("lastName", "Unknown"),
                    email=email,
                    phone=details.get("mobilePhone"),
                    status=mapped_status,
                    hire_date=hire_date or datetime.now().date(),
                    job_title=details.get("jobTitle", "Employee"),
                    location=details.get("location"),
                )
                db.add(employee)
            else:
                employee.worker_id = bamboo_id
                employee.first_name = details.get("firstName", employee.first_name)
                employee.last_name = details.get("lastName", employee.last_name)
                employee.phone = details.get("mobilePhone", employee.phone)
                employee.status = mapped_status
                if hire_date:
                    employee.hire_date = hire_date
                employee.job_title = details.get("jobTitle", employee.job_title)
                employee.location = details.get("location", employee.location)
                db.add(employee)
                
            synced_count += 1
            
        await db.commit()
        logger.info(f"BambooHR sync complete. Upserted {synced_count} employees.")
        return synced_count
