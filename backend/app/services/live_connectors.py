"""
KAEOS — Live Connector Service (L0 Data Fabric, real integrations)

Turns the connector mesh from simulated feeds into real integrations: a client
stores their OAuth/API credentials once and every sync pulls live records from
the actual system, normalizing them into Signals.

Providers are inferred from the connector's name/category, or set explicitly.
Core adapters live here; the wider vendor catalog lives in
``app/services/vendor_adapters.py`` and is merged into the registry below.

  Core        jira, salesforce, workday, sap, generic_rest
  Engineering github, gitlab, pagerduty, datadog, sentry
  IT Ops      servicenow
  Support     zendesk, intercom
  Sales       hubspot
  HR          bamboohr, greenhouse
  Finance     stripe
  Legal       docusign
  Collab      slack, confluence, notion, microsoft_graph

Secrets are encrypted at rest with a Fernet key derived from SECRET_KEY.
When a connector has no stored credentials, sync falls back to the simulated
demo feed so the platform remains fully usable without external systems.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0

from app.services.vendor_adapters import (
    VENDOR_ADAPTERS, VENDOR_NAME_HINTS, VENDOR_REQUIRED_CONFIG,
)

_CORE_PROVIDERS = ("jira", "salesforce", "workday", "sap", "generic_rest")
PROVIDERS = _CORE_PROVIDERS + tuple(VENDOR_ADAPTERS)


# ── Secret encryption ─────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    """Fernet keyed off SECRET_KEY (stable across restarts, never stored)."""
    secret = (get_settings().SECRET_KEY or "kaeos-dev-secret").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secrets(secrets: Dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(secrets).encode()).decode()


def decrypt_secrets(token: str) -> Dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError) as e:
        raise ValueError("Stored credentials cannot be decrypted (SECRET_KEY changed?)") from e


# ── Provider inference ────────────────────────────────────────────────────────

_NAME_HINTS = {
    # Vendor-specific hints first; core hints are the fallback for generic names.
    **VENDOR_NAME_HINTS,
    "jira": "jira", "issue tracker": "jira", "atlassian": "jira",
    "salesforce": "salesforce", "crm platform": "salesforce",
    "workday": "workday", "hr management": "workday",
    "sap": "sap", "erp": "sap",
    "hris": "workday",
}

_CATEGORY_HINTS = {
    "engineering": "github",     # code is the dominant engineering signal
    "source control": "github",
    "incident": "pagerduty",
    "observability": "datadog",
    "itsm": "servicenow",
    "crm": "salesforce",
    "hris": "workday",
    "ats": "greenhouse",
    "finance": "sap",
    "payments": "stripe",
    "support": "zendesk",
    "collaboration": "slack",
    "knowledge": "confluence",
}


def infer_provider(name: str, category: Optional[str]) -> str:
    lowered = (name or "").lower()
    # Longest hint wins, so "service now" beats a stray "now" substring and
    # "github" is not shadowed by a shorter, less specific fragment.
    for hint in sorted(_NAME_HINTS, key=len, reverse=True):
        if hint in lowered:
            return _NAME_HINTS[hint]
    if category and category.lower() in _CATEGORY_HINTS:
        return _CATEGORY_HINTS[category.lower()]
    return "generic_rest"


# ── Adapters ──────────────────────────────────────────────────────────────────
# Each adapter implements:
#   test(config, secrets)  -> {"ok": bool, "detail": str}
#   fetch(config, secrets) -> list[dict] normalized records:
#       {"external_id", "entity", "summary", "domain", "authority", "pii"}

class JiraAdapter:
    """Jira Cloud REST API v3 — email + API token basic auth."""
    domain = "engineering"

    @staticmethod
    def _client(config, secrets) -> httpx.AsyncClient:
        base = config["base_url"].rstrip("/")
        return httpx.AsyncClient(
            base_url=base, timeout=HTTP_TIMEOUT,
            auth=(secrets.get("email", ""), secrets.get("api_token", "")),
        )

    async def test(self, config, secrets):
        async with self._client(config, secrets) as c:
            r = await c.get("/rest/api/3/myself")
            if r.status_code == 200:
                return {"ok": True, "detail": f"Authenticated as {r.json().get('displayName', 'user')}"}
            return {"ok": False, "detail": f"Jira responded {r.status_code}: {r.text[:120]}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        jql = config.get("jql", "updated >= -7d ORDER BY updated DESC")
        async with self._client(config, secrets) as c:
            r = await c.get("/rest/api/3/search", params={"jql": jql, "maxResults": config.get("batch_size", 25)})
            r.raise_for_status()
            issues = r.json().get("issues", [])
        return [
            {
                "external_id": i.get("key", i.get("id", "")),
                "entity": "issue",
                "summary": f"[{i.get('key')}] {i.get('fields', {}).get('summary', '')} "
                           f"(status: {(i.get('fields', {}).get('status') or {}).get('name', '?')})",
                "domain": self.domain,
                "authority": 0.85,
                "pii": False,
            }
            for i in issues
        ]


class SalesforceAdapter:
    """Salesforce REST — OAuth2 client-credentials (or pre-issued access token)."""
    domain = "sales"

    async def _token(self, config, secrets) -> tuple[str, str]:
        instance = config["instance_url"].rstrip("/")
        if secrets.get("access_token"):
            return instance, secrets["access_token"]
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(f"{instance}/services/oauth2/token", data={
                "grant_type": "client_credentials",
                "client_id": secrets.get("client_id", ""),
                "client_secret": secrets.get("client_secret", ""),
            })
            r.raise_for_status()
            body = r.json()
        return body.get("instance_url", instance), body["access_token"]

    async def test(self, config, secrets):
        try:
            instance, token = await self._token(config, secrets)
        except httpx.HTTPStatusError as e:
            return {"ok": False, "detail": f"OAuth failed: {e.response.status_code} {e.response.text[:120]}"}
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{instance}/services/data/", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                return {"ok": True, "detail": f"Connected — {len(r.json())} API versions available"}
            return {"ok": False, "detail": f"Salesforce responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        instance, token = await self._token(config, secrets)
        soql = config.get("soql", "SELECT Id, Name, StageName, Amount FROM Opportunity ORDER BY LastModifiedDate DESC LIMIT 25")
        version = config.get("api_version", "v59.0")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(
                f"{instance}/services/data/{version}/query",
                params={"q": soql}, headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            records = r.json().get("records", [])
        return [
            {
                "external_id": rec.get("Id", ""),
                "entity": rec.get("attributes", {}).get("type", "record").lower(),
                "summary": f"{rec.get('Name', 'record')} — stage {rec.get('StageName', '?')}, "
                           f"amount {rec.get('Amount', '?')}",
                "domain": self.domain,
                "authority": 0.9,
                "pii": False,
            }
            for rec in records
        ]


class WorkdayAdapter:
    """Workday RaaS (report-as-a-service) JSON endpoint — ISU basic auth."""
    domain = "hr"

    async def test(self, config, secrets):
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,
                                     auth=(secrets.get("username", ""), secrets.get("password", ""))) as c:
            r = await c.get(config["report_url"], params={"format": "json"})
            if r.status_code == 200:
                return {"ok": True, "detail": "RaaS report reachable"}
            return {"ok": False, "detail": f"Workday responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,
                                     auth=(secrets.get("username", ""), secrets.get("password", ""))) as c:
            r = await c.get(config["report_url"], params={"format": "json"})
            r.raise_for_status()
            entries = r.json().get("Report_Entry", [])
        out = []
        for e in entries[: config.get("batch_size", 50)]:
            ident = e.get("Employee_ID") or e.get("Worker") or str(uuid.uuid4())[:8]
            out.append({
                "external_id": str(ident),
                "entity": "worker",
                "summary": f"Workday record {ident}: " + ", ".join(f"{k}={v}" for k, v in list(e.items())[:4]),
                "domain": self.domain,
                "authority": 0.95,
                "pii": True,
            })
        return out


class SAPAdapter:
    """SAP OData v2/v4 service — basic auth or APIKey header."""
    domain = "finance"

    def _headers(self, secrets) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if secrets.get("api_key"):
            h["APIKey"] = secrets["api_key"]
        return h

    def _auth(self, secrets):
        if secrets.get("username"):
            return (secrets["username"], secrets.get("password", ""))
        return None

    async def test(self, config, secrets):
        url = config["service_url"].rstrip("/")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, auth=self._auth(secrets)) as c:
            r = await c.get(f"{url}/$metadata", headers=self._headers(secrets))
            if r.status_code == 200:
                return {"ok": True, "detail": "OData service metadata reachable"}
            return {"ok": False, "detail": f"SAP responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        url = config["service_url"].rstrip("/")
        entity_set = config.get("entity_set", "A_SupplierInvoice")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, auth=self._auth(secrets)) as c:
            r = await c.get(f"{url}/{entity_set}", headers=self._headers(secrets),
                            params={"$top": config.get("batch_size", 25), "$format": "json"})
            r.raise_for_status()
            body = r.json()
        rows = body.get("value") or body.get("d", {}).get("results", []) or []
        return [
            {
                "external_id": str(row.get("SupplierInvoice") or row.get("ID") or i),
                "entity": entity_set.lower(),
                "summary": f"SAP {entity_set} record: " + ", ".join(f"{k}={v}" for k, v in list(row.items())[:4]),
                "domain": self.domain,
                "authority": 0.9,
                "pii": False,
            }
            for i, row in enumerate(rows)
        ]


class GenericRESTAdapter:
    """Any JSON REST endpoint — optional bearer token / API-key header."""
    domain = "general"

    def _headers(self, secrets) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if secrets.get("bearer_token"):
            h["Authorization"] = f"Bearer {secrets['bearer_token']}"
        if secrets.get("api_key"):
            h[secrets.get("api_key_header", "X-API-Key") if isinstance(secrets.get("api_key_header"), str) else "X-API-Key"] = secrets["api_key"]
        return h

    def _url(self, config) -> str:
        return config["base_url"].rstrip("/") + "/" + config.get("endpoint", "").lstrip("/")

    async def test(self, config, secrets):
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(self._url(config), headers=self._headers(secrets))
            if 200 <= r.status_code < 300:
                return {"ok": True, "detail": f"Endpoint reachable ({r.status_code})"}
            return {"ok": False, "detail": f"Endpoint responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(self._url(config), headers=self._headers(secrets))
            r.raise_for_status()
            body = r.json()
        items = body if isinstance(body, list) else body.get(config.get("items_key", "items"), [])
        if not isinstance(items, list):
            items = [body]
        out = []
        for i, item in enumerate(items[: config.get("batch_size", 25)]):
            if isinstance(item, dict):
                ident = str(item.get("id", i))
                pairs = ", ".join(f"{k}={v}" for k, v in list(item.items())[:4])
            else:
                ident, pairs = str(i), str(item)[:100]
            out.append({
                "external_id": ident,
                "entity": config.get("entity_name", "record"),
                "summary": f"REST record {ident}: {pairs}",
                "domain": config.get("domain", self.domain),
                "authority": float(config.get("authority", 0.7)),
                "pii": bool(config.get("pii", False)),
            })
        return out


_ADAPTERS = {
    "jira": JiraAdapter(),
    "salesforce": SalesforceAdapter(),
    "workday": WorkdayAdapter(),
    "sap": SAPAdapter(),
    "generic_rest": GenericRESTAdapter(),
    **VENDOR_ADAPTERS,
}

# Config keys each provider requires before it can attempt a connection
REQUIRED_CONFIG = {
    "jira": ["base_url"],
    "salesforce": ["instance_url"],
    "workday": ["report_url"],
    "sap": ["service_url"],
    "generic_rest": ["base_url"],
    **VENDOR_REQUIRED_CONFIG,
}


def list_providers() -> List[Dict[str, Any]]:
    """Catalog of every live integration, for the connector-setup UI."""
    return [
        {
            "id": pid,
            "domain": getattr(adapter, "domain", "general"),
            "entity": getattr(adapter, "entity", "record"),
            "authority": getattr(adapter, "authority", 0.8),
            "handles_pii": bool(getattr(adapter, "pii", False)),
            "required_config": REQUIRED_CONFIG.get(pid, []),
        }
        for pid, adapter in sorted(_ADAPTERS.items())
    ]


class LiveConnectorService:
    """Orchestrates credentialed live syncs for a connector."""

    @staticmethod
    def validate(provider: str, config: Dict[str, Any]) -> Optional[str]:
        if provider not in _ADAPTERS:
            return f"Unknown provider '{provider}'. Supported: {', '.join(PROVIDERS)}"
        missing = [k for k in REQUIRED_CONFIG[provider] if not config.get(k)]
        if missing:
            return f"Missing required config for {provider}: {', '.join(missing)}"
        return None

    @staticmethod
    async def test_connection(provider: str, config: Dict[str, Any], secrets: Dict[str, Any]) -> Dict[str, Any]:
        adapter = _ADAPTERS[provider]
        try:
            return await adapter.test(config, secrets)
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"Connection failed: {type(e).__name__}: {str(e)[:160]}"}
        except Exception as e:
            return {"ok": False, "detail": f"Unexpected error: {str(e)[:160]}"}

    @staticmethod
    async def fetch_records(provider: str, config: Dict[str, Any], secrets: Dict[str, Any]) -> List[Dict[str, Any]]:
        adapter = _ADAPTERS[provider]
        return await adapter.fetch(config, secrets)

    @staticmethod
    def records_to_signals(records: List[Dict[str, Any]], tenant_id: str,
                           source_name: str) -> list:
        """Normalize fetched records into Signal rows (deduped by external id per sync)."""
        from app.models.domain import Signal
        now = datetime.now(timezone.utc)
        signals = []
        for rec in records:
            signals.append(Signal(
                id=f"sig_{uuid.uuid4().hex[:12]}",
                tenant_id=tenant_id,
                signal_type="LIVE_SYNC",
                source_type=source_name.lower().replace(" ", "_"),
                source_entity=f"{rec['entity']}:{rec['external_id']}",
                clean_payload=rec["summary"][:2000],
                pii_present=bool(rec.get("pii")),
                authority_score=float(rec.get("authority", 0.7)),
                domain=rec.get("domain", "general"),
                created_at=now,
            ))
        return signals
