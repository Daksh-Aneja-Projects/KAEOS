"""
KAEOS Operations Domain — Jira Connector
Handles pulling projects, milestones, tasks, and issue statuses from Jira
via the Jira Cloud REST API v3.
"""
import logging
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class JiraConnector:
    """Jira Cloud REST API sync client."""

    def __init__(self, tenant_id: str, subdomain: str, email: str, api_token: str):
        self.tenant_id = tenant_id
        self.subdomain = subdomain
        self.email = email
        self.api_token = api_token
        self.base_url = f"https://{self.subdomain}.atlassian.net/rest/api/3"
        # Jira Cloud basic auth: account email + API token.
        self.auth = (self.email, self.api_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get_projects(self) -> List[Dict[str, Any]]:
        """Fetch projects via the paginated project search endpoint."""
        logger.info(f"Syncing Jira projects for tenant {self.tenant_id}")
        url = f"{self.base_url}/project/search"
        start_at = 0
        projects: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                while True:
                    res = await client.get(
                        url,
                        auth=self.auth,
                        headers=self.headers,
                        params={"startAt": start_at, "maxResults": 50},
                    )
                    res.raise_for_status()
                    data = res.json()
                    values = data.get("values", [])
                    projects.extend(values)
                    if data.get("isLast", True) or not values:
                        break
                    start_at += len(values)
            except Exception as e:
                logger.error(
                    f"[Jira] Failed to fetch projects for tenant {self.tenant_id}: {e}"
                )
                raise
        return projects

    async def get_issues(self, jql: str = "order by created DESC") -> List[Dict[str, Any]]:
        """Fetch issues matching a JQL query, following pagination."""
        logger.info(f"Syncing Jira issues for tenant {self.tenant_id}")
        url = f"{self.base_url}/search"
        start_at = 0
        issues: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                while True:
                    res = await client.get(
                        url,
                        auth=self.auth,
                        headers=self.headers,
                        params={"jql": jql, "startAt": start_at, "maxResults": 50},
                    )
                    res.raise_for_status()
                    data = res.json()
                    batch = data.get("issues", [])
                    issues.extend(batch)
                    total = data.get("total", 0)
                    start_at += len(batch)
                    if not batch or start_at >= total:
                        break
            except Exception as e:
                logger.error(
                    f"[Jira] Failed to fetch issues for tenant {self.tenant_id}: {e}"
                )
                raise
        return issues

    async def test_connection(self) -> bool:
        """Verify credentials via the current-user endpoint."""
        url = f"{self.base_url}/myself"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(url, auth=self.auth, headers=self.headers)
                res.raise_for_status()
                return True
            except Exception as e:
                logger.warning(
                    f"[Jira] Connection test failed for tenant {self.tenant_id}: {e}"
                )
                return False
