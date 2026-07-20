"""
KAEOS Sales Domain — Salesforce Connector
Synchronizes pipelines, contact records, and account activities from Salesforce
via the Salesforce REST API (SOQL queries + sObject endpoints).
"""
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


class SalesforceConnector:
    """Salesforce REST API sync client."""

    def __init__(self, tenant_id: str, instance_url: str, credentials: Dict[str, Any]):
        self.tenant_id = tenant_id
        self.instance_url = instance_url.rstrip("/")
        self.credentials = credentials
        self.api_version = credentials.get("api_version", "v58.0")
        self.base_url = f"{self.instance_url}/services/data/{self.api_version}"
        access_token = self.credentials.get("access_token")
        if not access_token:
            raise ValueError(
                f"[Salesforce] No access_token in credentials for tenant {self.tenant_id}"
            )
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

    @staticmethod
    def _soql_literal(value: str) -> str:
        """Escape a value for safe interpolation into a SOQL string literal.

        Per SOQL rules, backslash must be escaped before the single quote. This
        is a targeted escape for the small set of filterable fields below; if the
        connector grows more filter surface, promote this to a proper query
        builder rather than hand-interpolating.
        """
        return value.replace("\\", "\\\\").replace("'", "\\'")

    async def _query(self, soql: str) -> List[Dict[str, Any]]:
        """Run a SOQL query, following queryLocator pagination to completion."""
        records: List[Dict[str, Any]] = []
        url: Optional[str] = f"{self.base_url}/query"
        params: Optional[Dict[str, str]] = {"q": soql}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                while url:
                    res = await client.get(url, headers=self.headers, params=params)
                    res.raise_for_status()
                    data = res.json()
                    records.extend(data.get("records", []))
                    # Salesforce returns an absolute nextRecordsUrl path when more
                    # pages remain; params only apply to the first request.
                    next_url = data.get("nextRecordsUrl")
                    url = f"{self.instance_url}{next_url}" if next_url else None
                    params = None
            except Exception as e:
                logger.error(f"[Salesforce] SOQL query failed for tenant {self.tenant_id}: {e}")
                raise
        return records

    async def get_opportunities(self, stage: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch opportunities, optionally filtered by a pipeline stage."""
        logger.info(f"Syncing opportunities from Salesforce for tenant {self.tenant_id}")
        soql = (
            "SELECT Id, Name, Amount, StageName, CloseDate, AccountId "
            "FROM Opportunity"
        )
        if stage:
            soql += f" WHERE StageName = '{self._soql_literal(stage)}'"
        soql += " ORDER BY CloseDate ASC"
        return await self._query(soql)

    async def get_contacts(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch contact records, optionally scoped to a single account."""
        logger.info(f"Syncing contacts from Salesforce for tenant {self.tenant_id}")
        soql = "SELECT Id, FirstName, LastName, Email, Title, AccountId FROM Contact"
        if account_id:
            soql += f" WHERE AccountId = '{self._soql_literal(account_id)}'"
        return await self._query(soql)

    async def test_connection(self) -> bool:
        """Verify token and org access via the lightweight limits endpoint."""
        url = f"{self.base_url}/limits"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(url, headers=self.headers)
                res.raise_for_status()
                return True
            except Exception as e:
                logger.warning(f"[Salesforce] Connection test failed for tenant {self.tenant_id}: {e}")
                return False
