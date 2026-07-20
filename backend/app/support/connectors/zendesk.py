"""
KAEOS Support Domain — Zendesk Connector
Synchronizes ticket queues, agent rosters, and CSAT scores from Zendesk
via the Zendesk Support REST API.
"""
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


class ZendeskConnector:
    """Zendesk Support API client for syncing support tickets."""

    def __init__(self, tenant_id: str, subdomain: str, email: str, api_token: str):
        self.tenant_id = tenant_id
        self.subdomain = subdomain
        self.email = email
        self.api_token = api_token
        self.base_url = f"https://{self.subdomain}.zendesk.com/api/v2"
        # Zendesk API-token auth: "{email}/token" as the username.
        self.auth = (f"{self.email}/token", self.api_token)
        self.headers = {"Accept": "application/json"}

    async def get_tickets(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch tickets, following cursor pagination; filter by status if given."""
        logger.info(f"Syncing support tickets from Zendesk for tenant {self.tenant_id}")
        url: Optional[str] = f"{self.base_url}/tickets.json"
        params: Optional[Dict[str, str]] = {"page[size]": "100"}

        tickets: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                while url:
                    res = await client.get(
                        url, auth=self.auth, headers=self.headers, params=params
                    )
                    res.raise_for_status()
                    data = res.json()
                    tickets.extend(data.get("tickets", []))
                    meta = data.get("meta", {})
                    if meta.get("has_more"):
                        url = data.get("links", {}).get("next")
                    else:
                        url = None
                    params = None
            except Exception as e:
                logger.error(
                    f"[Zendesk] Failed to fetch tickets for tenant {self.tenant_id}: {e}"
                )
                raise

        if status:
            tickets = [t for t in tickets if t.get("status") == status]
        return tickets

    async def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """Fetch a single ticket by id."""
        url = f"{self.base_url}/tickets/{ticket_id}.json"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return res.json().get("ticket", {})
            except Exception as e:
                logger.error(f"[Zendesk] Failed to fetch ticket {ticket_id}: {e}")
                raise

    async def test_connection(self) -> bool:
        """Verify credentials via the current-user endpoint."""
        url = f"{self.base_url}/users/me.json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return True
            except Exception as e:
                logger.warning(
                    f"[Zendesk] Connection test failed for tenant {self.tenant_id}: {e}"
                )
                return False
