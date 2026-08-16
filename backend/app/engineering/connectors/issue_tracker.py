"""
KAEOS Engineering Domain — Issue Tracker / Source Control Connector

Real adapter to the GitHub REST API (v2022-11-28), backing the "Issue Tracker"
and "Code Repository" integrations engineering's seed data lists as CONNECTED.
Follows the same httpx pattern as app/finance/connectors/accounting_sync.py: a
thin, credentials-scoped class. Callers map the returned records into KAEOS's
own eng_pull_requests / eng_pipeline_runs rows; this connector does no ORM
writes itself.
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.outbound import guarded_async_client

logger = logging.getLogger(__name__)


class GitHubIssueTrackerConnector:
    """Connector to a single GitHub repository's issues, pull requests, and
    Actions workflow runs."""

    def __init__(self, tenant_id: str, credentials: Dict[str, Any]):
        self.tenant_id = tenant_id
        self.credentials = credentials
        self.base_url = credentials.get("api_url", "https://api.github.com").rstrip("/")
        token = credentials.get("token")
        if not token:
            raise ValueError(
                f"[GitHubIssueTracker] No token in credentials for tenant {self.tenant_id}"
            )
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self) -> str:
        owner = self.credentials.get("owner")
        repo = self.credentials.get("repo")
        if not owner or not repo:
            raise ValueError(
                f"[GitHubIssueTracker] No owner/repo in credentials for tenant {self.tenant_id}"
            )
        return f"{owner}/{repo}"

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        async with guarded_async_client(timeout=30.0) as client:
            try:
                res = await client.get(url, headers=self.headers, params=params)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(
                    f"[GitHubIssueTracker] GET {url} failed for tenant {self.tenant_id}: {e}"
                )
                raise

    async def sync_open_issues(self) -> List[Dict[str, Any]]:
        """Fetch open issues. GitHub's /issues endpoint also returns pull
        requests, tagged with a 'pull_request' key — filtered out here so
        callers get issues only."""
        logger.info(f"Syncing open issues from GitHub for tenant {self.tenant_id}")
        data = await self._get(
            f"{self.base_url}/repos/{self._repo()}/issues",
            params={"state": "open", "per_page": 50},
        )
        return [i for i in data if "pull_request" not in i]

    async def sync_pull_requests(self, state: str = "open") -> List[Dict[str, Any]]:
        """Fetch pull requests — the source eng_pull_requests rows map from."""
        logger.info(f"Syncing {state} pull requests from GitHub for tenant {self.tenant_id}")
        return await self._get(
            f"{self.base_url}/repos/{self._repo()}/pulls",
            params={"state": state, "per_page": 50},
        )

    async def sync_workflow_runs(self) -> List[Dict[str, Any]]:
        """Fetch GitHub Actions workflow runs — the source eng_pipeline_runs
        rows map from."""
        logger.info(f"Syncing workflow runs from GitHub for tenant {self.tenant_id}")
        data = await self._get(
            f"{self.base_url}/repos/{self._repo()}/actions/runs",
            params={"per_page": 50},
        )
        return data.get("workflow_runs", [])

    async def test_connection(self) -> bool:
        """Verify credentials with a lightweight, real read against GitHub."""
        try:
            await self._get(f"{self.base_url}/repos/{self._repo()}")
            return True
        except Exception as e:
            logger.warning(
                f"[GitHubIssueTracker] Connection test failed for tenant {self.tenant_id}: {e}"
            )
            return False
