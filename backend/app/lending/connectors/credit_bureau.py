"""
KAEOS Lending Domain — Credit Bureau Connector

Adapter to pull a real consumer credit report/score from an external bureau
(Equifax, Experian and TransUnion each expose a similar REST report-by-
consumer-identifier surface). Mirrors app/finance/connectors/accounting_sync.py's
shape.

Unlike accounting sync (raises at construction when uncredentialed - a caller
that reaches it already knows the integration must be configured), a credit
pull is invoked speculatively during intake: a tenant with no bureau
credentials on file is a normal, expected state, not a defect. HONESTY
CONTRACT: pull_report NEVER fabricates a score when unconfigured or
unreachable - it returns an explicit not-configured / unavailable status with
score=None instead of a guess or a hardcoded default.
"""
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_SUPPORTED_BUREAUS = ("equifax", "experian", "transunion")


class CreditBureauConnector:
    """Connector to pull a consumer credit report from an external bureau."""

    def __init__(self, tenant_id: str, bureau: str, credentials: Optional[Dict[str, Any]] = None):
        self.tenant_id = tenant_id
        self.bureau = (bureau or "").lower()
        self.credentials = credentials or {}

    @property
    def configured(self) -> bool:
        return self.bureau in _SUPPORTED_BUREAUS and bool(self.credentials.get("api_key"))

    def _base_url(self) -> str:
        if self.bureau == "equifax":
            return "https://api.equifax.com/business/consumer-credit/v1"
        if self.bureau == "experian":
            return "https://api.experian.com/consumerservices/credit-profile/v2"
        if self.bureau == "transunion":
            return "https://api.transunion.com/credit-report/v1"
        raise ValueError(f"Unsupported credit bureau '{self.bureau}'")

    async def pull_report(self, applicant_ref: str) -> Dict[str, Any]:
        """Pull a real credit report for ``applicant_ref``. Returns
        ``{status, score, report, note}`` where ``status`` is one of
        'ok' | 'not_configured' | 'unavailable'. NEVER fabricates a score: an
        unconfigured tenant or a failed pull returns ``score: None`` with an
        explanatory note - the caller (intake) must fall back to a manually
        entered credit score, never invent one."""
        if not self.credentials.get("api_key") or self.bureau not in _SUPPORTED_BUREAUS:
            return {
                "status": "not_configured", "score": None, "report": None,
                "note": (f"No {self.bureau or 'credit bureau'} API credentials on file "
                         f"for tenant {self.tenant_id}; credit score must be entered "
                         "manually."),
            }

        headers = {"Authorization": f"Bearer {self.credentials['api_key']}",
                   "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(f"{self._base_url()}/reports/{applicant_ref}",
                                       headers=headers)
                res.raise_for_status()
                data = res.json()
        except Exception as e:
            logger.warning(f"[CreditBureau/{self.bureau}] pull failed for tenant "
                           f"{self.tenant_id}: {e}")
            return {"status": "unavailable", "score": None, "report": None,
                    "note": f"{self.bureau} report pull failed: {e}"}

        score = data.get("score") or data.get("creditScore") or data.get("riskScore")
        return {"status": "ok", "score": score, "report": data, "note": None}

    async def test_connection(self) -> bool:
        """Verify credentials with a lightweight, real read against the bureau."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(
                    f"{self._base_url()}/status",
                    headers={"Authorization": f"Bearer {self.credentials['api_key']}"})
                res.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"[CreditBureau/{self.bureau}] connection test failed for "
                           f"tenant {self.tenant_id}: {e}")
            return False
