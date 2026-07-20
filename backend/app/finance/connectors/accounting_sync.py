"""
KAEOS Finance Domain — Accounting System Sync Connector
Multi-adapter connector for QuickBooks Online, Xero, and NetSuite sync.

Each provider exposes a different REST surface, so the public methods dispatch to
a provider-specific fetch and return that provider's records. Callers are
responsible for field-level mapping into KAEOS canonical models.
"""
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("quickbooks", "xero", "netsuite")


class AccountingSyncConnector:
    """Connector to synchronize KAEOS with external accounting packages."""

    def __init__(self, tenant_id: str, provider: str, credentials: Dict[str, Any]):
        self.tenant_id = tenant_id
        self.provider = provider.lower()  # quickbooks, xero, netsuite
        if self.provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"[AccountingSync] Unsupported provider '{provider}' for tenant "
                f"{self.tenant_id}; expected one of {_SUPPORTED_PROVIDERS}"
            )
        self.credentials = credentials
        self.base_url = self._get_base_url()
        self.headers = self._get_headers()

    def _get_base_url(self) -> str:
        if self.provider == "quickbooks":
            host = self.credentials.get(
                "base_url", "https://quickbooks.api.intuit.com"
            ).rstrip("/")
            return f"{host}/v3/company"
        elif self.provider == "xero":
            return "https://api.xero.com/api.xro/2.0"
        elif self.provider == "netsuite":
            account_id = self.credentials.get("account_id")
            if not account_id:
                raise ValueError(
                    f"[AccountingSync/netsuite] No account_id in credentials for "
                    f"tenant {self.tenant_id}"
                )
            return (
                f"https://{account_id}.suitetalk.api.netsuite.com"
                "/services/rest/record/v1"
            )
        # Unreachable: __init__ validates the provider.
        raise ValueError(f"Unsupported provider {self.provider}")

    def _get_headers(self) -> Dict[str, str]:
        token = self.credentials.get("access_token")
        if not token:
            raise ValueError(
                f"[AccountingSync/{self.provider}] No access_token in credentials "
                f"for tenant {self.tenant_id}"
            )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if self.provider == "quickbooks":
            headers["Content-Type"] = "application/json"
        elif self.provider == "xero":
            # Xero scopes every call to a connected organisation.
            tenant = self.credentials.get("xero_tenant_id")
            if not tenant:
                raise ValueError(
                    f"[AccountingSync/xero] No xero_tenant_id in credentials for "
                    f"tenant {self.tenant_id}"
                )
            headers["Xero-tenant-id"] = tenant
        return headers

    async def _get(self, url: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.get(url, headers=self.headers, params=params)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(
                    f"[AccountingSync/{self.provider}] GET {url} failed for tenant "
                    f"{self.tenant_id}: {e}"
                )
                raise

    async def sync_chart_of_accounts(self) -> List[Dict[str, Any]]:
        """Fetch general ledger accounts from the external system."""
        logger.info(
            f"Syncing chart of accounts from {self.provider} for tenant {self.tenant_id}"
        )
        if self.provider == "quickbooks":
            realm_id = self._require("realm_id")
            data = await self._get(
                f"{self.base_url}/{realm_id}/query",
                params={"query": "select * from Account", "minorversion": "65"},
            )
            return data.get("QueryResponse", {}).get("Account", [])
        elif self.provider == "xero":
            data = await self._get(f"{self.base_url}/Accounts")
            return data.get("Accounts", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/account")
            return data.get("items", [])

    async def sync_invoices(self) -> List[Dict[str, Any]]:
        """Fetch accounts-payable invoices (bills) from the external system."""
        logger.info(f"Syncing AP invoices from {self.provider} for tenant {self.tenant_id}")
        if self.provider == "quickbooks":
            realm_id = self._require("realm_id")
            data = await self._get(
                f"{self.base_url}/{realm_id}/query",
                params={"query": "select * from Bill", "minorversion": "65"},
            )
            return data.get("QueryResponse", {}).get("Bill", [])
        elif self.provider == "xero":
            data = await self._get(
                f"{self.base_url}/Invoices", params={"where": 'Type=="ACCPAY"'}
            )
            return data.get("Invoices", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/vendorBill")
            return data.get("items", [])

    async def sync_receivables(self) -> List[Dict[str, Any]]:
        """Fetch accounts-receivable customer invoices from the external system."""
        logger.info(f"Syncing AR customer invoices from {self.provider} for tenant {self.tenant_id}")
        if self.provider == "quickbooks":
            realm_id = self._require("realm_id")
            data = await self._get(
                f"{self.base_url}/{realm_id}/query",
                params={"query": "select * from Invoice", "minorversion": "65"},
            )
            return data.get("QueryResponse", {}).get("Invoice", [])
        elif self.provider == "xero":
            data = await self._get(
                f"{self.base_url}/Invoices", params={"where": 'Type=="ACCREC"'}
            )
            return data.get("Invoices", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/invoice")
            return data.get("items", [])

    def _require(self, key: str) -> str:
        value = self.credentials.get(key)
        if not value:
            raise ValueError(
                f"[AccountingSync/{self.provider}] No {key} in credentials for "
                f"tenant {self.tenant_id}"
            )
        return value

    async def test_connection(self) -> bool:
        """Verify credentials with a lightweight, real read against the provider."""
        try:
            if self.provider == "quickbooks":
                realm_id = self._require("realm_id")
                await self._get(
                    f"{self.base_url}/{realm_id}/companyinfo/{realm_id}",
                    params={"minorversion": "65"},
                )
            elif self.provider == "xero":
                await self._get(f"{self.base_url}/Organisation")
            else:  # netsuite
                await self._get(f"{self.base_url}/account", params={"limit": "1"})
            return True
        except Exception as e:
            logger.warning(
                f"[AccountingSync/{self.provider}] Connection test failed for tenant "
                f"{self.tenant_id}: {e}"
            )
            return False
