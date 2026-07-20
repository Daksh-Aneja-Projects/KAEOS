"""
KAEOS Legal Domain — DocuSign Connector
Handles pulling envelope statuses, signing events, and downloading executed PDFs
via the DocuSign eSignature REST API.
"""
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# DocuSign issues a per-account base URI at authentication (the `base_uri` in the
# OAuth userinfo response). Callers should pass it through; this is only the
# fallback for demo/sandbox accounts.
DEFAULT_DOCUSIGN_BASE_URI = "https://demo.docusign.net"


class DocuSignConnector:
    """DocuSign eSignature REST API client for contract tracking."""

    def __init__(
        self,
        tenant_id: str,
        account_id: str,
        integrator_key: str,
        credentials: Dict[str, Any],
    ):
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.integrator_key = integrator_key
        self.credentials = credentials
        # base_uri comes from the account's OAuth userinfo; fall back to the
        # sandbox host only when the caller has not supplied one.
        base_uri = credentials.get("base_uri", DEFAULT_DOCUSIGN_BASE_URI).rstrip("/")
        self.base_url = f"{base_uri}/restapi/v2.1/accounts/{self.account_id}"
        access_token = self.credentials.get("access_token")
        if not access_token:
            raise ValueError(
                f"[DocuSign] No access_token in credentials for tenant {self.tenant_id}"
            )
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

    async def get_envelopes(
        self, from_date: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch envelopes changed since ``from_date`` (ISO-8601 / YYYY-MM-DD)."""
        logger.info(f"Syncing DocuSign envelopes for tenant {self.tenant_id}")
        url = f"{self.base_url}/envelopes"
        params: Dict[str, str] = {"from_date": from_date}
        if status:
            params["status"] = status

        envelopes: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                while True:
                    res = await client.get(url, headers=self.headers, params=params)
                    res.raise_for_status()
                    data = res.json()
                    envelopes.extend(data.get("envelopes", []))
                    # DocuSign paginates via nextUri (an absolute API path).
                    next_uri = data.get("nextUri")
                    if not next_uri:
                        break
                    # nextUri is relative to the API host, before /restapi.
                    host = self.base_url.split("/restapi", 1)[0]
                    url = f"{host}{next_uri}"
                    params = {}
            except Exception as e:
                logger.error(
                    f"[DocuSign] Failed to fetch envelopes for tenant {self.tenant_id}: {e}"
                )
                raise
        return envelopes

    async def get_envelope_recipients(self, envelope_id: str) -> Dict[str, Any]:
        """Fetch the recipient/signing status for a single envelope."""
        url = f"{self.base_url}/envelopes/{envelope_id}/recipients"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.get(url, headers=self.headers)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(
                    f"[DocuSign] Failed to fetch recipients for envelope {envelope_id}: {e}"
                )
                raise

    async def test_connection(self) -> bool:
        """Verify token and account access via the account info endpoint."""
        url = f"{self.base_url}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(url, headers=self.headers)
                res.raise_for_status()
                return True
            except Exception as e:
                logger.warning(
                    f"[DocuSign] Connection test failed for tenant {self.tenant_id}: {e}"
                )
                return False
