"""
KAEOS HR Vertical — BambooHR Connector

Implementation of HRISBaseConnector for BambooHR.
Handles pulling employee records, org charts, and time-off data.
"""
import logging
import httpx
from typing import List, Dict, Any

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
        
        async with httpx.AsyncClient() as client:
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
        
        async with httpx.AsyncClient() as client:
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
        
        async with httpx.AsyncClient() as client:
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
        
        async with httpx.AsyncClient() as client:
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
            return False
