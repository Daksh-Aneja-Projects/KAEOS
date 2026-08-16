"""
KAEOS Healthcare — EHR Sync Connector (FHIR R4)

Real FHIR R4 REST client for the EHR systems declared in packs/healthcare.yaml's
required_integrations (Epic, Cerner and Athenahealth all expose a FHIR R4
surface at a tenant-specific base URL). Backs the pack's 'ehr' integration
category so the claim has real code behind it, mirroring
app/finance/connectors/accounting_sync.py's shape.

Callers are responsible for mapping FHIR resources (Patient/Encounter/
Condition) into KAEOS canonical models (PatientEncounter etc.) - this
connector only fetches and returns the raw resources.
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.outbound import guarded_async_client

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("epic", "cerner", "athenahealth")


class EHRSyncConnector:
    """FHIR R4 client to synchronize KAEOS with an external EHR."""

    def __init__(self, tenant_id: str, provider: str, credentials: Dict[str, Any]):
        self.tenant_id = tenant_id
        self.provider = provider.lower()  # epic, cerner, athenahealth
        if self.provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"[EHRSync] Unsupported provider '{provider}' for tenant "
                f"{self.tenant_id}; expected one of {_SUPPORTED_PROVIDERS}"
            )
        self.credentials = credentials
        self.base_url = self._get_base_url()
        self.headers = self._get_headers()

    def _get_base_url(self) -> str:
        # Every FHIR R4 EHR (Epic, Cerner, Athenahealth) exposes its own
        # tenant-scoped base URL - there is no shared public host like
        # QuickBooks/Xero, so it must come from the tenant's stored credentials.
        base = self.credentials.get("fhir_base_url")
        if not base:
            raise ValueError(
                f"[EHRSync/{self.provider}] No fhir_base_url in credentials for "
                f"tenant {self.tenant_id}"
            )
        return base.rstrip("/")

    def _get_headers(self) -> Dict[str, str]:
        token = self.credentials.get("access_token")
        if not token:
            raise ValueError(
                f"[EHRSync/{self.provider}] No access_token in credentials for "
                f"tenant {self.tenant_id}"
            )
        return {"Accept": "application/fhir+json", "Authorization": f"Bearer {token}"}

    async def _get(self, resource_path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        async with guarded_async_client(timeout=30.0) as client:
            try:
                res = await client.get(
                    f"{self.base_url}/{resource_path}", headers=self.headers, params=params,
                )
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logger.error(
                    f"[EHRSync/{self.provider}] GET {resource_path} failed for tenant "
                    f"{self.tenant_id}: {e}"
                )
                raise

    @staticmethod
    def _entries(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]

    async def sync_patients(self, count: int = 50) -> List[Dict[str, Any]]:
        """Fetch Patient resources - the source for PatientEncounter.patient_ref."""
        logger.info(f"Syncing patients from {self.provider} FHIR for tenant {self.tenant_id}")
        bundle = await self._get("Patient", params={"_count": str(count)})
        return self._entries(bundle)

    async def sync_encounters(self, patient_id: Optional[str] = None, count: int = 50) -> List[Dict[str, Any]]:
        """Fetch Encounter resources, optionally scoped to one patient."""
        logger.info(f"Syncing encounters from {self.provider} FHIR for tenant {self.tenant_id}")
        params = {"_count": str(count)}
        if patient_id:
            params["patient"] = patient_id
        bundle = await self._get("Encounter", params=params)
        return self._entries(bundle)

    async def sync_conditions(self, patient_id: Optional[str] = None, count: int = 50) -> List[Dict[str, Any]]:
        """Fetch Condition resources - the diagnosis_codes source for coding."""
        logger.info(f"Syncing conditions from {self.provider} FHIR for tenant {self.tenant_id}")
        params = {"_count": str(count)}
        if patient_id:
            params["patient"] = patient_id
        bundle = await self._get("Condition", params=params)
        return self._entries(bundle)

    async def test_connection(self) -> bool:
        """Verify credentials with the FHIR CapabilityStatement (lightweight, real read)."""
        try:
            await self._get("metadata")
            return True
        except Exception as e:
            logger.warning(
                f"[EHRSync/{self.provider}] Connection test failed for tenant "
                f"{self.tenant_id}: {e}"
            )
            return False
