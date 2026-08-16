"""
KAEOS HR Vertical — BambooHR Connector

Implementation of HRISBaseConnector for BambooHR.
Handles pulling employee records, org charts, and time-off data.
"""
import logging
from datetime import date
from typing import List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbound import guarded_async_client

logger = logging.getLogger(__name__)

class BambooHRConnector:
    """BambooHR API client for syncing HR data into KAEOS."""
    
    def __init__(self, tenant_id: str, subdomain: str, api_key: str):
        self.tenant_id = tenant_id
        self.subdomain = subdomain
        self.api_key = api_key
        self.base_url = f"https://api.bamboohr.com/api/gateway.php/{self.subdomain}/v1"
        self.auth = (self.api_key, 'x')
        self.headers = {"Accept": "application/json"}

    async def get_employees(self, status: str = "all") -> List[Dict[str, Any]]:
        """Fetch employee directory from BambooHR."""
        url = f"{self.base_url}/employees/directory"
        
        async with guarded_async_client() as client:
            try:
                # In a real implementation, we handle pagination if needed
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                data = res.json()
                return data.get("employees", [])
            except Exception as e:
                logger.error(f"Failed to fetch employees from BambooHR: {e}")
                raise

    async def get_employee_details(self, employee_id: str) -> Dict[str, Any]:
        """Fetch detailed fields for a single employee."""
        # Standard fields to fetch
        fields = "firstName,lastName,jobTitle,department,location,hireDate,workEmail,mobilePhone,status,supervisorEId"
        url = f"{self.base_url}/employees/{employee_id}/?fields={fields}"
        
        async with guarded_async_client() as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(f"Failed to fetch employee details for {employee_id} from BambooHR: {e}")
                raise

    async def get_time_off_requests(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Fetch time off requests for a given date range (YYYY-MM-DD)."""
        url = f"{self.base_url}/time_off/requests?start={start_date}&end={end_date}"
        
        async with guarded_async_client() as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(f"Failed to fetch time off requests from BambooHR: {e}")
                raise
                
    async def get_company_report(self, report_id: str) -> Dict[str, Any]:
        """Fetch a custom report from BambooHR (e.g. Compensation data)."""
        url = f"{self.base_url}/reports/{report_id}?format=json"
        
        async with guarded_async_client() as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(f"Failed to fetch report {report_id} from BambooHR: {e}")
                raise

    async def test_connection(self) -> bool:
        """Verify API credentials."""
        try:
            # A lightweight call to verify auth
            await self.get_employees()
            return True
        except Exception:
            logger.warning("BambooHR connection test failed", exc_info=True)
            return False


async def sync_employees(db: AsyncSession, tenant_id: str, subdomain: str, api_key: str) -> Dict[str, Any]:
    """Pull the BambooHR directory and upsert it into ``hr_employees``.

    Credentials are used for this request only — never persisted (there is no
    connector-credential store for HR yet, so the honest scope of "wiring" the
    connector is a per-call sync, not a saved integration). Matches by
    ``worker_id`` (the BambooHR employee id) within the tenant so re-running a
    sync updates existing rows instead of duplicating them.
    """
    from app.hr.models.core import HREmployee, EmploymentStatus

    connector = BambooHRConnector(tenant_id, subdomain, api_key)
    if not await connector.test_connection():
        return {"ok": False, "error": "Could not authenticate with BambooHR using the supplied subdomain/API key.",
                "created": 0, "updated": 0}

    directory = await connector.get_employees()
    existing = {
        e.worker_id: e for e in (await db.execute(
            select(HREmployee).where(HREmployee.tenant_id == tenant_id)
        )).scalars().all() if e.worker_id
    }

    created = updated = skipped = 0
    for row in directory:
        worker_id = str(row.get("id") or "").strip()
        first = (row.get("firstName") or "").strip()
        last = (row.get("lastName") or "").strip()
        email = (row.get("workEmail") or "").strip()
        if not worker_id or not first or not last or not email:
            # BambooHR directory fields are configurable per-company; a row
            # missing the identity fields we key/require on can't be synced.
            skipped += 1
            continue

        if worker_id in existing:
            emp = existing[worker_id]
            emp.first_name, emp.last_name, emp.email = first, last, email
            emp.job_title = row.get("jobTitle") or emp.job_title
            emp.location = row.get("location") or emp.location
            emp.phone = row.get("mobilePhone") or emp.phone
            db.add(emp)
            updated += 1
        else:
            db.add(HREmployee(
                tenant_id=tenant_id, worker_id=worker_id,
                first_name=first, last_name=last, email=email,
                job_title=row.get("jobTitle") or "Unknown",
                location=row.get("location"), phone=row.get("mobilePhone"),
                status=EmploymentStatus.ACTIVE,
                hire_date=date.today(),
            ))
            created += 1

    await db.commit()
    return {"ok": True, "fetched": len(directory), "created": created, "updated": updated, "skipped": skipped}
