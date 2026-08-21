"""
KAEOS - Live Connector Service (L0 Data Fabric, real integrations)

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
import json
import logging
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.core.config import get_settings
from app.core.outbound import guarded_async_client

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0

from app.services.vendor_adapters import (
    VENDOR_ADAPTERS, VENDOR_NAME_HINTS, VENDOR_REQUIRED_CONFIG,
)

_CORE_PROVIDERS = ("jira", "salesforce", "workday", "sap", "generic_rest")
PROVIDERS = _CORE_PROVIDERS + tuple(VENDOR_ADAPTERS)


# ── Secret encryption ─────────────────────────────────────────────────────────

_KDF_SALT = b"kaeos.byok.fernet.v2"   # fixed app salt for a deterministic KDF
_KDF_ITERATIONS = 200_000


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Derive the at-rest encryption key via PBKDF2-HMAC-SHA256.

    Cached: the salt and iteration count are module constants and the secret
    comes from the (already cached) settings, so the derived key is invariant
    for the process lifetime. Re-deriving cost 200k PBKDF2 iterations (~36 ms of
    event-loop CPU) on every encrypt/decrypt, and LLMRouter.for_tenant() calls
    this once per configured tier, several times per governed decision.

    Key separation: prefers a DEDICATED ``CONNECTOR_ENCRYPTION_KEY`` so the
    at-rest data key is independent of the JWT-signing ``SECRET_KEY`` (a leak of
    one signing context then does not hand over the other). Falls back to
    ``SECRET_KEY`` when the dedicated key is unset, so existing deployments keep
    decrypting their stored secrets unchanged. (Setting a NEW key later rotates
    it - existing ciphertext must be re-encrypted, the standard rotation caveat.)

    Hardened over the old single unsalted sha256:
      - PBKDF2 (200k iterations) instead of one hash pass;
      - NO insecure hardcoded fallback - a missing/weak key raises rather than
        silently using a world-readable default key;
      - entropy floor enforced so BYOK secrets aren't protected by a guessable key.
    """
    settings = get_settings()
    secret = getattr(settings, "CONNECTOR_ENCRYPTION_KEY", "") or settings.SECRET_KEY or ""
    if len(secret) < 16 and not settings.DEV_MODE:
        raise RuntimeError(
            "No strong at-rest key (<16 chars) - refusing to encrypt customer "
            "credentials. Set CONNECTOR_ENCRYPTION_KEY (preferred) or SECRET_KEY."
        )
    if not secret:
        # DEV_MODE only: still avoid a shared constant by requiring *some* key.
        raise RuntimeError("Set CONNECTOR_ENCRYPTION_KEY or SECRET_KEY to store connector credentials.")
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=_KDF_SALT, iterations=_KDF_ITERATIONS)
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return Fernet(key)


def encrypt_secrets(secrets: Dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(secrets).encode()).decode()


def decrypt_secrets(token: str) -> Dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError) as e:
        raise ValueError("Stored credentials cannot be decrypted (SECRET_KEY changed?)") from e


# ── Per-tenant envelope encryption ────────────────────────────────────────────
# Each tenant gets a random Fernet DATA key, wrapped by the master KEK (_fernet)
# and stored in tenant_data_keys. Secrets encrypt under the tenant key, so one
# leaked key no longer opens every tenant, and deleting the row crypto-shreds
# that tenant. The master remains the wrap key AND the legacy read path.

_tenant_fernet_cache: Dict[str, Fernet] = {}


def evict_tenant_key(tenant_id: str) -> None:
    """Drop the cached data key for a tenant (call after rotate/delete)."""
    _tenant_fernet_cache.pop(tenant_id, None)


async def _fernet_for_tenant(tenant_id: str) -> Fernet:
    cached = _tenant_fernet_cache.get(tenant_id)
    if cached is not None:
        return cached
    from app.core.database import MaintenanceSessionLocal
    from app.models.tenant_data_key import TenantDataKey
    master = _fernet()
    async with MaintenanceSessionLocal() as db:
        row = (await db.execute(
            select(TenantDataKey).where(TenantDataKey.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if row is None:
            data_key = Fernet.generate_key()
            db.add(TenantDataKey(tenant_id=tenant_id,
                                 wrapped_key=master.encrypt(data_key).decode()))
            try:
                await db.commit()
            except Exception:
                # Lost a create race with a concurrent caller - read theirs.
                await db.rollback()
                row = (await db.execute(
                    select(TenantDataKey).where(TenantDataKey.tenant_id == tenant_id)
                )).scalar_one()
                data_key = master.decrypt(row.wrapped_key.encode())
        else:
            data_key = master.decrypt(row.wrapped_key.encode())
    f = Fernet(data_key)
    _tenant_fernet_cache[tenant_id] = f
    return f


async def encrypt_secrets_for_tenant(tenant_id: str, secrets: Dict[str, Any]) -> str:
    f = await _fernet_for_tenant(tenant_id)
    return f.encrypt(json.dumps(secrets).encode()).decode()


async def decrypt_secrets_for_tenant(tenant_id: str, token: str) -> Dict[str, Any]:
    """Decrypt under the tenant key, falling back to the legacy master key.

    The fallback is mandatory: secrets written before this change were encrypted
    under the global master key, and must still decrypt after deploy. The next
    write re-encrypts under the tenant key (lazy migration, no bulk pass).
    """
    try:
        f = await _fernet_for_tenant(tenant_id)
        return json.loads(f.decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        # Legacy global-key ciphertext (or a crypto-shredded/rotated tenant key).
        return decrypt_secrets(token)


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
    """Jira Cloud REST API v3 - email + API token basic auth."""
    domain = "engineering"

    @staticmethod
    def _client(config, secrets) -> httpx.AsyncClient:
        base = config["base_url"].rstrip("/")
        return guarded_async_client(
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
    """Salesforce REST - OAuth2 client-credentials (or pre-issued access token)."""
    domain = "sales"

    async def _token(self, config, secrets) -> tuple[str, str]:
        instance = config["instance_url"].rstrip("/")
        if secrets.get("access_token"):
            return instance, secrets["access_token"]
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
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
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{instance}/services/data/", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                return {"ok": True, "detail": f"Connected - {len(r.json())} API versions available"}
            return {"ok": False, "detail": f"Salesforce responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        instance, token = await self._token(config, secrets)
        soql = config.get("soql", "SELECT Id, Name, StageName, Amount FROM Opportunity ORDER BY LastModifiedDate DESC LIMIT 25")
        version = config.get("api_version", "v59.0")
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
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
                "summary": f"{rec.get('Name', 'record')} - stage {rec.get('StageName', '?')}, "
                           f"amount {rec.get('Amount', '?')}",
                "domain": self.domain,
                "authority": 0.9,
                "pii": False,
            }
            for rec in records
        ]


class WorkdayAdapter:
    """Workday RaaS (report-as-a-service) JSON endpoint - ISU basic auth."""
    domain = "hr"

    async def test(self, config, secrets):
        async with guarded_async_client(timeout=HTTP_TIMEOUT,
                                     auth=(secrets.get("username", ""), secrets.get("password", ""))) as c:
            r = await c.get(config["report_url"], params={"format": "json"})
            if r.status_code == 200:
                return {"ok": True, "detail": "RaaS report reachable"}
            return {"ok": False, "detail": f"Workday responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        async with guarded_async_client(timeout=HTTP_TIMEOUT,
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
    """SAP OData v2/v4 service - basic auth or APIKey header."""
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
        async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=self._auth(secrets)) as c:
            r = await c.get(f"{url}/$metadata", headers=self._headers(secrets))
            if r.status_code == 200:
                return {"ok": True, "detail": "OData service metadata reachable"}
            return {"ok": False, "detail": f"SAP responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        url = config["service_url"].rstrip("/")
        entity_set = config.get("entity_set", "A_SupplierInvoice")
        async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=self._auth(secrets)) as c:
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
    """Any JSON REST endpoint - optional bearer token / API-key header."""
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
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(self._url(config), headers=self._headers(secrets))
            if 200 <= r.status_code < 300:
                return {"ok": True, "detail": f"Endpoint reachable ({r.status_code})"}
            return {"ok": False, "detail": f"Endpoint responded {r.status_code}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
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
        # Any config value that is a URL becomes an outbound request target, and
        # on the sync path the response comes back to the tenant as Signal rows.
        # One check here covers every adapter.
        from app.core.outbound import check_outbound_url
        for key, value in config.items():
            if key.endswith("_url") and isinstance(value, str) and value:
                reason = check_outbound_url(value)
                if reason:
                    return f"Invalid {key}: {reason}"
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
        from app.services import prompt_guard

        now = datetime.now(timezone.utc)
        signals = []
        for rec in records:
            # Poll results are UNTRUSTED: a Slack message or Jira ticket body is
            # attacker-writable. Redact live instruction spans before the text is
            # persisted, because everything downstream reads clean_payload.
            payload, injection = prompt_guard.neutralize(rec["summary"][:2000])
            # A high-risk signal is quarantined rather than dropped: it stays
            # visible to a human, but authority 0.0 keeps it under every
            # consumer's authority floor (e.g. PreCog's > 0.8), so it can never
            # drive an unattended action.
            if injection.should_block:
                logger.warning(
                    "[LiveConnector] quarantining signal from %s: injection risk=%s categories=%s",
                    source_name, injection.risk.value, injection.categories,
                )
                payload = f"[QUARANTINED: prompt-injection detected] {payload}"
            signals.append(Signal(
                id=f"sig_{uuid.uuid4().hex[:12]}",
                tenant_id=tenant_id,
                signal_type="QUARANTINED" if injection.should_block else "LIVE_SYNC",
                source_type=source_name.lower().replace(" ", "_"),
                source_entity=f"{rec['entity']}:{rec['external_id']}",
                external_id=str(rec.get("external_id") or "") or None,
                clean_payload=payload,
                pii_present=bool(rec.get("pii")),
                authority_score=0.0 if injection.should_block else float(rec.get("authority", 0.7)),
                domain=rec.get("domain", "general"),
                created_at=now,
            ))
        return signals

    @staticmethod
    async def persist_signals(db, signals: list) -> Dict[str, int]:
        """Upsert built signals on the natural key (tenant, source_type,
        external_id) so a re-sync UPDATES the existing twin row instead of
        inserting a fresh random-UUID duplicate every poll.

        Signals with no external_id (there is no stable dedup key) are inserted
        as before - they are webhook/demo rows, not repeated pulls.
        """
        from app.models.domain import Signal

        keyed = [s for s in signals if s.external_id]
        existing: Dict[tuple, Signal] = {}
        if keyed:
            keys = {(s.tenant_id, s.source_type, s.external_id) for s in keyed}
            tenants = {s.tenant_id for s in keyed}
            # Bound the dedup read to THIS batch: match only the source_type /
            # external_id values we are about to upsert, not every keyed Signal
            # in the tenant's history (a full-table scan that grows forever).
            # in_() over the two columns over-matches their cross product, so the
            # exact-tuple `in keys` filter below still decides membership - but
            # the DB now returns ~batch_size rows instead of the whole history.
            source_types = {s.source_type for s in keyed}
            ext_ids = {s.external_id for s in keyed}
            rows = (await db.execute(select(Signal).where(
                Signal.tenant_id.in_(tenants),
                Signal.source_type.in_(source_types),
                Signal.external_id.in_(ext_ids),
            ))).scalars().all()
            existing = {(r.tenant_id, r.source_type, r.external_id): r
                        for r in rows if (r.tenant_id, r.source_type, r.external_id) in keys}

        inserted = updated = 0
        inserted_signals: list = []  # H1: the new rows to bridge into the event mesh
        for s in signals:
            prior = existing.get((s.tenant_id, s.source_type, s.external_id)) if s.external_id else None
            if prior is None:
                db.add(s)
                if s.external_id:
                    existing[(s.tenant_id, s.source_type, s.external_id)] = s
                inserted += 1
                inserted_signals.append(s)
            else:
                prior.clean_payload = s.clean_payload
                prior.authority_score = s.authority_score
                prior.signal_type = s.signal_type
                prior.pii_present = s.pii_present
                prior.domain = s.domain
                prior.created_at = s.created_at
                updated += 1
        return {"inserted": inserted, "updated": updated, "inserted_signals": inserted_signals}

    @staticmethod
    async def embed_signals_into_memory(tenant_id: str, signals: list) -> int:
        """H5: embed connector signals into the enterprise-memory vector
        namespace - the one chat.py's RAG grounds on - so the high-volume
        real-world ingest actually lets the copilot answer from real data
        instead of a permanently empty corpus.

        Batched (one embed call per pull), a no-op when embeddings are simulated
        (no real model available), and best-effort: never fails the pull. Skips
        quarantined signals so injection-risk text never becomes grounding.
        """
        live = [s for s in signals
                if getattr(s, "signal_type", None) not in ("QUARANTINED", "DEMO")
                and (getattr(s, "clean_payload", "") or "").strip()]
        if not live:
            return 0
        try:
            from app.core.polystore import get_vector_store
            from app.services.llm_router import get_tenant_router
            llm = await get_tenant_router(tenant_id)
            embeddings = await llm.embed([(s.clean_payload or "")[:8000] for s in live])
            if getattr(llm, "embeddings_simulated", False):
                return 0
            store = get_vector_store()
            n = 0
            for s, emb in zip(live, embeddings):
                await store.upsert(
                    vector_id=f"connector-sig-{s.id}",
                    tenant_id=tenant_id,
                    content=(s.clean_payload or "")[:4000],
                    embedding=emb,
                    metadata={"source": s.source_type,
                              "domain": getattr(s, "domain", None),
                              "signal_id": s.id},
                    namespace="enterprise_memory",
                )
                n += 1
            return n
        except Exception as e:
            logger.warning("[LiveConnector] embedding signals into memory failed: %s", e)
            return 0
