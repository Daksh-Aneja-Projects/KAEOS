"""
KAEOS Procurement Domain — Procurement System Sync Connector
Multi-adapter connector for Coupa, SAP Ariba, and NetSuite (the three
procurement systems the domain pack declares under required_integrations,
app/workforce/domain_packs/packs/procurement.yaml).

Each provider exposes a different REST surface, so the public methods dispatch
to a provider-specific fetch and return that provider's records. Callers are
responsible for field-level mapping into KAEOS canonical models (PurchaseOrder
/ PurchaseRequest / VendorContract). Mirrors the shape of
app.finance.connectors.accounting_sync.AccountingSyncConnector.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("coupa", "ariba", "netsuite")


class ProcurementSyncConnector:
    """Connector to synchronize KAEOS with an external procurement system."""

    def __init__(self, tenant_id: str, provider: str, credentials: Dict[str, Any]):
        self.tenant_id = tenant_id
        self.provider = provider.lower()  # coupa, ariba, netsuite
        if self.provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"[ProcurementSync] Unsupported provider '{provider}' for tenant "
                f"{self.tenant_id}; expected one of {_SUPPORTED_PROVIDERS}"
            )
        self.credentials = credentials
        self.base_url = self._get_base_url()
        self.headers = self._get_headers()

    def _get_base_url(self) -> str:
        if self.provider == "coupa":
            instance = self.credentials.get("instance")
            if not instance:
                raise ValueError(
                    f"[ProcurementSync/coupa] No instance in credentials for "
                    f"tenant {self.tenant_id}"
                )
            return f"https://{instance}.coupahost.com/api"
        elif self.provider == "ariba":
            realm = self.credentials.get("realm")
            if not realm:
                raise ValueError(
                    f"[ProcurementSync/ariba] No realm in credentials for "
                    f"tenant {self.tenant_id}"
                )
            return f"https://openapi.ariba.com/api/procure-to-pay/v1/{realm}"
        else:  # netsuite
            account_id = self.credentials.get("account_id")
            if not account_id:
                raise ValueError(
                    f"[ProcurementSync/netsuite] No account_id in credentials for "
                    f"tenant {self.tenant_id}"
                )
            return (
                f"https://{account_id}.suitetalk.api.netsuite.com"
                "/services/rest/record/v1"
            )

    def _get_headers(self) -> Dict[str, str]:
        token = self.credentials.get("access_token")
        if not token:
            raise ValueError(
                f"[ProcurementSync/{self.provider}] No access_token in credentials "
                f"for tenant {self.tenant_id}"
            )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if self.provider == "coupa":
            headers["Content-Type"] = "application/json"
        return headers

    async def _get(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.get(url, headers=self.headers, params=params)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(
                    f"[ProcurementSync/{self.provider}] GET {url} failed for tenant "
                    f"{self.tenant_id}: {e}"
                )
                raise

    async def sync_purchase_orders(self) -> List[Dict[str, Any]]:
        """Fetch purchase orders from the external procurement system."""
        logger.info(f"Syncing purchase orders from {self.provider} for tenant {self.tenant_id}")
        if self.provider == "coupa":
            data = await self._get(f"{self.base_url}/purchase_orders")
            return data if isinstance(data, list) else data.get("purchase_orders", [])
        elif self.provider == "ariba":
            data = await self._get(f"{self.base_url}/purchaseOrders")
            return data.get("purchaseOrders", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/purchaseOrder")
            return data.get("items", [])

    async def sync_requisitions(self) -> List[Dict[str, Any]]:
        """Fetch purchase requisitions from the external procurement system."""
        logger.info(f"Syncing requisitions from {self.provider} for tenant {self.tenant_id}")
        if self.provider == "coupa":
            data = await self._get(f"{self.base_url}/requisitions")
            return data if isinstance(data, list) else data.get("requisitions", [])
        elif self.provider == "ariba":
            data = await self._get(f"{self.base_url}/requisitions")
            return data.get("requisitions", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/purchaseRequisition")
            return data.get("items", [])

    async def sync_vendors(self) -> List[Dict[str, Any]]:
        """Fetch supplier / vendor master records from the external system."""
        logger.info(f"Syncing vendors from {self.provider} for tenant {self.tenant_id}")
        if self.provider == "coupa":
            data = await self._get(f"{self.base_url}/suppliers")
            return data if isinstance(data, list) else data.get("suppliers", [])
        elif self.provider == "ariba":
            data = await self._get(f"{self.base_url}/suppliers")
            return data.get("suppliers", [])
        else:  # netsuite
            data = await self._get(f"{self.base_url}/vendor")
            return data.get("items", [])

    async def test_connection(self) -> bool:
        """Verify credentials with a lightweight, real read against the provider."""
        try:
            if self.provider == "coupa":
                await self._get(f"{self.base_url}/purchase_orders", params={"limit": "1"})
            elif self.provider == "ariba":
                await self._get(f"{self.base_url}/purchaseOrders", params={"limit": "1"})
            else:  # netsuite
                await self._get(f"{self.base_url}/purchaseOrder", params={"limit": "1"})
            return True
        except Exception as e:
            logger.warning(
                f"[ProcurementSync/{self.provider}] Connection test failed for tenant "
                f"{self.tenant_id}: {e}"
            )
            return False
