"""KAEOS - bidirectional sync engine (realtime inbound + governed outbound).

INBOUND (realtime-first): external systems push changes to
``POST /api/v1/integrations/ingest/{connector_id}`` the moment data changes on
their side (Workday webhook, Salesforce outbound message, a middleware relay).
The request is authenticated by an HMAC-SHA256 signature over the raw body
using the connector's ``webhook_secret`` - the connector id alone grants
nothing. Payloads use the canonical envelope:

    {"entity_type": "employee|account|opportunity|ticket|incident",
     "op": "upsert" | "delete",
     "external_id": "<id in the source system>",
     "data": {...canonical fields...}}

Provider-native conveniences: a Workday worker event or Salesforce sobject
notification in their common shapes is normalized into the envelope
automatically. Anything unrecognizable is recorded in the SyncLedger as
SKIPPED with the reason - the engine never guesses.

Interval fallback: connectors whose systems cannot push still sync on the
scheduler via the existing LiveConnectorService pull path.

OUTBOUND (write-back): a governed KAEOS mutation queues an OutboundWrite; the
dispatcher pushes it through the provider adapter of a CONNECTED connector in
the matching category. Honest failure states, never silent: no connector ->
SKIPPED_NO_CONNECTOR, no credentials -> SKIPPED_NO_CREDENTIALS, HTTP failure
-> FAILED with the error and retry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbound import guarded_async_client
from app.models.sync import OutboundWrite, SyncLedger

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0
CANONICAL_ENTITIES = ("employee", "account", "opportunity", "ticket", "incident")

# entity_type -> connector category expected to receive its write-backs.
# Used only when a write is queued WITHOUT an explicit provider (the actuation
# path): the dispatcher then routes by matching a CONNECTED connector's category.
_ENTITY_CATEGORY = {
    "employee": "hris",
    "account": "crm",
    "opportunity": "crm",
    "ticket": "support",
    "incident": "engineering",
    "issue": "engineering",
    "message": "collaboration",
    "contact": "crm",
}


# ── Inbound: signature + normalization ────────────────────────────────────────

def verify_signature(secret: str, raw_body: bytes, signature: Optional[str]) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def normalize_payload(provider: str, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (canonical_envelope, skip_reason). Exactly one is non-None."""
    # Already canonical?
    if payload.get("entity_type") in CANONICAL_ENTITIES and isinstance(payload.get("data"), dict):
        op = str(payload.get("op", "upsert")).lower()
        if op not in ("upsert", "delete"):
            return None, f"unknown op '{op}'"
        return {"entity_type": payload["entity_type"], "op": op,
                "external_id": str(payload.get("external_id") or ""),
                "data": payload["data"]}, None

    # Workday worker event (common webhook/RaaS shape)
    worker = payload.get("worker") or payload.get("Worker")
    if worker and isinstance(worker, dict):
        name = worker.get("name") or {}
        return {"entity_type": "employee", "op": "upsert",
                "external_id": str(worker.get("id") or worker.get("employeeID") or ""),
                "data": {
                    "email": worker.get("primaryWorkEmail") or worker.get("email"),
                    "first_name": name.get("firstName") or worker.get("firstName"),
                    "last_name": name.get("lastName") or worker.get("lastName"),
                    "job_title": worker.get("businessTitle") or worker.get("title"),
                    "status": worker.get("status") or ("TERMINATED" if worker.get("terminated") else "ACTIVE"),
                }}, None

    # Salesforce sobject notification (common shape)
    sobject = payload.get("sobject") or payload.get("sObject")
    if sobject and isinstance(sobject, dict):
        sobject_type = str(payload.get("sobjectType") or sobject.get("attributes", {}).get("type", "")).lower()
        if sobject_type in ("account",):
            return {"entity_type": "account", "op": "upsert",
                    "external_id": str(sobject.get("Id") or ""),
                    "data": {"name": sobject.get("Name"),
                             "website": sobject.get("Website"),
                             "industry": sobject.get("Industry")}}, None
        if sobject_type in ("opportunity",):
            return {"entity_type": "opportunity", "op": "upsert",
                    "external_id": str(sobject.get("Id") or ""),
                    "data": {"name": sobject.get("Name"),
                             "amount": sobject.get("Amount"),
                             "stage": sobject.get("StageName")}}, None
        return None, f"unsupported sobject type '{sobject_type}'"

    return None, "unrecognized payload shape (send the canonical envelope)"


async def _apply_upsert(db, tenant_id: str, envelope: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Upsert the canonical entity into the twin. Returns (internal_id, error)."""
    et = envelope["entity_type"]
    data = envelope["data"]

    if et == "employee":
        from app.hr.models.core import HREmployee, EmploymentStatus
        email = (data.get("email") or "").strip().lower()
        if not email:
            return "", "employee payload has no email (the match key)"
        row = (await db.execute(select(HREmployee).where(
            HREmployee.tenant_id == tenant_id, HREmployee.email == email
        ))).scalar_one_or_none()
        if row is None:
            hire = data.get("hire_date")
            try:
                hire_date = datetime.fromisoformat(str(hire)).date() if hire else datetime.now(timezone.utc).date()
            except ValueError:
                hire_date = datetime.now(timezone.utc).date()
            row = HREmployee(tenant_id=tenant_id, email=email,
                             first_name=data.get("first_name") or "Unknown",
                             last_name=data.get("last_name") or "",
                             job_title=data.get("job_title") or "Employee",
                             hire_date=hire_date)
            db.add(row)
        if data.get("first_name"):
            row.first_name = str(data["first_name"])[:64]
        if data.get("last_name"):
            row.last_name = str(data["last_name"])[:64]
        if data.get("job_title"):
            row.job_title = str(data["job_title"])[:128]
        status = str(data.get("status") or "").upper()
        if status in EmploymentStatus.__members__:
            row.status = EmploymentStatus[status]
        await db.flush()
        return row.id, None

    if et == "account":
        from app.sales.models.accounts import Account
        name = (data.get("name") or "").strip()
        if not name:
            return "", "account payload has no name (the match key)"
        row = (await db.execute(select(Account).where(
            Account.tenant_id == tenant_id, Account.name == name
        ))).scalar_one_or_none()
        if row is None:
            row = Account(tenant_id=tenant_id, name=name[:256])
            db.add(row)
        if data.get("website"):
            row.website = str(data["website"])[:256]
        if data.get("industry"):
            row.industry = str(data["industry"])[:128]
        if data.get("health_score") is not None:
            try:
                row.health_score = max(0.0, min(1.0, float(data["health_score"])))
            except (TypeError, ValueError):
                # A non-numeric health score from an external system is dropped
                # rather than written: leaving the prior value is more honest
                # than coercing junk into a scored field.
                pass
        await db.flush()
        return row.id, None

    if et == "opportunity":
        from app.sales.models.pipeline import Opportunity, OpportunityStage
        name = (data.get("name") or "").strip()
        if not name:
            return "", "opportunity payload has no name (the match key)"
        row = (await db.execute(select(Opportunity).where(
            Opportunity.tenant_id == tenant_id, Opportunity.name == name
        ))).scalar_one_or_none()
        if row is None:
            row = Opportunity(tenant_id=tenant_id, name=name[:256])
            db.add(row)
        if data.get("amount") is not None:
            try:
                row.amount = Decimal(str(data["amount"]))   # money: no float round-trip
            except (TypeError, ValueError, InvalidOperation):
                pass
        stage = str(data.get("stage") or "").upper().replace(" ", "_")
        if stage in OpportunityStage.__members__:
            row.stage = OpportunityStage[stage]
        await db.flush()
        return row.id, None

    if et == "ticket":
        from app.support.models.tickets import Ticket, TicketStatus, TicketPriority
        subject = (data.get("subject") or "").strip()
        if not subject:
            return "", "ticket payload has no subject (the match key)"
        row = (await db.execute(select(Ticket).where(
            Ticket.tenant_id == tenant_id, Ticket.subject == subject
        ))).scalar_one_or_none()
        if row is None:
            row = Ticket(tenant_id=tenant_id, subject=subject[:256])
            db.add(row)
        status = str(data.get("status") or "").upper()
        if status in TicketStatus.__members__:
            row.status = TicketStatus[status]
        priority = str(data.get("priority") or "").upper()
        if priority in TicketPriority.__members__:
            row.priority = TicketPriority[priority]
        await db.flush()
        return row.id, None

    if et == "incident":
        from app.engineering.models.incidents import Incident, IncidentSeverity, IncidentStatus
        number = (data.get("incident_number") or envelope.get("external_id") or "").strip()
        if not number:
            return "", "incident payload has no incident_number"
        row = (await db.execute(select(Incident).where(
            Incident.tenant_id == tenant_id, Incident.incident_number == number
        ))).scalar_one_or_none()
        if row is None:
            row = Incident(tenant_id=tenant_id, incident_number=number[:32],
                           title=(data.get("title") or number)[:256])
            db.add(row)
        if data.get("title"):
            row.title = str(data["title"])[:256]
        sev = str(data.get("severity") or "").upper()
        if sev in IncidentSeverity.__members__:
            row.severity = IncidentSeverity[sev]
        status = str(data.get("status") or "").upper()
        if status in IncidentStatus.__members__:
            row.status = IncidentStatus[status]
        await db.flush()
        return row.id, None

    return "", f"unsupported entity_type '{et}'"


async def ingest_webhook(connector_id: str, signature: Optional[str],
                         raw_body: bytes) -> Dict[str, Any]:
    """Realtime inbound: verify, normalize, upsert into the twin, ledger it.

    Returns {"status": ..., "ledger_id": ...}. Raises PermissionError on a bad
    signature and LookupError on an unknown connector - the route maps these
    to 401/404.
    """
    from app.core.database import MaintenanceSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import decrypt_secrets

    # Resolve the connector + secret on the maintenance session: this is a
    # PUBLIC endpoint, so there is no tenant context yet - the connector row
    # itself tells us the tenant.
    async with MaintenanceSessionLocal() as mdb:
        connector = (await mdb.execute(select(Connector).where(
            Connector.id == connector_id
        ))).scalar_one_or_none()
        if connector is None:
            raise LookupError("connector not found")
        cred = (await mdb.execute(select(ConnectorCredential).where(
            ConnectorCredential.connector_id == connector_id
        ))).scalar_one_or_none()
        secret = ""
        provider = (cred.provider if cred else None) or (connector.category or "generic")
        if cred is not None:
            try:
                secret = decrypt_secrets(cred.secrets_encrypted).get("webhook_secret", "")
            except Exception:
                # No readable secret (missing or rotated SECRET_KEY) -> treat as
                # "no webhook secret configured" rather than failing the sync.
                secret = ""
        tenant_id = connector.tenant_id

    if not verify_signature(secret, raw_body, signature):
        raise PermissionError("invalid or missing webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        payload = None

    # From here on we act AS the tenant (RLS via the contextvar the app uses).
    from app.core.context import current_tenant_id
    from app.core.database import AsyncSessionLocal
    token = current_tenant_id.set(tenant_id)
    try:
        async with AsyncSessionLocal() as db:
            if payload is None:
                entry = SyncLedger(tenant_id=tenant_id, connector_id=connector_id,
                                   provider=provider, direction="IN",
                                   entity_type="unknown", op="UPSERT",
                                   status="SKIPPED", detail="body is not valid JSON")
                db.add(entry)
                await db.commit()
                return {"status": "skipped", "reason": "invalid json", "ledger_id": entry.id}

            envelope, skip = normalize_payload(provider, payload)
            if envelope is None:
                entry = SyncLedger(tenant_id=tenant_id, connector_id=connector_id,
                                   provider=provider, direction="IN",
                                   entity_type=str(payload.get("entity_type") or "unknown")[:64],
                                   op="UPSERT", status="SKIPPED", detail=skip)
                db.add(entry)
                await db.commit()
                return {"status": "skipped", "reason": skip, "ledger_id": entry.id}

            if envelope["op"] == "delete":
                # Deletion is a governed, destructive act - record it for the
                # actuation/HITL path rather than silently destroying twin rows.
                entry = SyncLedger(tenant_id=tenant_id, connector_id=connector_id,
                                   provider=provider, direction="IN",
                                   entity_type=envelope["entity_type"],
                                   external_id=envelope["external_id"],
                                   op="DELETE", status="SKIPPED",
                                   detail="inbound deletes require governed approval; "
                                          "recorded, not applied")
                db.add(entry)
                await db.commit()
                return {"status": "recorded", "note": "delete requires governed approval",
                        "ledger_id": entry.id}

            internal_id, err = await _apply_upsert(db, tenant_id, envelope)
            entry = SyncLedger(
                tenant_id=tenant_id, connector_id=connector_id, provider=provider,
                direction="IN", entity_type=envelope["entity_type"],
                external_id=envelope["external_id"], internal_id=internal_id or None,
                op="UPSERT", status="APPLIED" if err is None else "FAILED", detail=err,
            )
            db.add(entry)
            # keep the connector's counters honest
            connector_row = (await db.execute(select_connector_for_update(connector_id))).scalar_one_or_none()
            if connector_row is not None:
                connector_row.events_ingested = (connector_row.events_ingested or 0) + 1
                connector_row.last_sync_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "applied" if err is None else "failed",
                    "error": err, "internal_id": internal_id or None,
                    "ledger_id": entry.id}
    finally:
        current_tenant_id.reset(token)


def select_connector_for_update(connector_id: str):
    from app.models.domain import Connector
    return select(Connector).where(Connector.id == connector_id)


# ── Outbound: queue + dispatch ────────────────────────────────────────────────

MAX_ATTEMPTS = 5


async def queue_outbound(tenant_id: str, entity_type: str, internal_id: str,
                         op: str, payload: Dict[str, Any],
                         external_id: Optional[str] = None,
                         provider: Optional[str] = None,
                         idempotency_key: Optional[str] = None,
                         db: Optional[AsyncSession] = None) -> Optional[str]:
    """Queue a governed mutation for write-back. Never raises into callers.

    ``db`` is the CALLER's session and should be passed whenever one exists: the
    queue row then lives in the same transaction as the change that caused it, so
    a caller that rolls back does not leave an orphaned write-back queued for a
    mutation that never happened. Opening an independent AsyncSessionLocal (the
    previous unconditional behaviour) committed the queue row on a separate
    connection and transaction, which both broke that atomicity and, in tests,
    wrote to a different engine than the one the fixtures created the schema on
    (surfacing as a swallowed "no such table: outbound_writes" on every sync).

    Falls back to its own session only for callers with no session in hand
    (background sweeps).
    """
    row = OutboundWrite(
        tenant_id=tenant_id, provider=provider,
        category=_ENTITY_CATEGORY.get(entity_type),
        entity_type=entity_type, internal_id=internal_id,
        external_id=external_id, op=op.upper(), payload=payload,
    )
    if idempotency_key:
        row.idempotency_key = idempotency_key[:64]
    try:
        if db is not None:
            db.add(row)
            # Flush, don't commit: the caller owns the transaction boundary.
            await db.flush()
            return row.id
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as own:
            own.add(row)
            await own.commit()
            return row.id
    except Exception as e:
        logger.error("[Sync] queue_outbound failed: %s", e)
        return None


async def _write_via_adapter(provider: str, cred, config: Dict[str, Any],
                             secrets: Dict[str, Any], write: OutboundWrite) -> Optional[str]:
    """Push one write to the external system. Returns error or None.

    generic_rest is the reference adapter (works against any REST endpoint the
    client points it at - and is how the engine is integration-tested for real
    over local HTTP). salesforce implements the real sobject REST call and
    activates the moment client credentials are stored.
    """
    body = {"entity_type": write.entity_type, "op": write.op,
            "external_id": write.external_id, "internal_id": write.internal_id,
            "data": write.payload}
    idem = write.idempotency_key or write.id

    if provider == "generic_rest":
        base = (config.get("base_url") or "").rstrip("/")
        if not base:
            return "generic_rest connector has no base_url configured"
        headers = {"Content-Type": "application/json", "Idempotency-Key": idem}
        if secrets.get("api_key"):
            headers["Authorization"] = f"Bearer {secrets['api_key']}"
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(f"{base}/kaeos/sync", json=body, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
        return None

    if provider == "servicenow":
        return await _write_servicenow(config, secrets, write, idem)

    if provider == "zendesk":
        return await _write_zendesk(config, secrets, write, idem)

    if provider == "jira":
        return await _write_jira(config, secrets, write, idem)

    if provider == "slack":
        return await _write_slack(config, secrets, write, idem)

    if provider == "hubspot":
        return await _write_hubspot(config, secrets, write, idem)

    if provider == "github":
        return await _write_github(config, secrets, write, idem)

    if provider == "pagerduty":
        return await _write_pagerduty(config, secrets, write, idem)

    if provider == "salesforce":
        instance = (config.get("instance_url") or "").rstrip("/")
        token = secrets.get("access_token")
        if not instance or not token:
            return "salesforce connector missing instance_url/access_token"
        sobject = {"account": "Account", "opportunity": "Opportunity"}.get(write.entity_type)
        if sobject is None:
            return f"salesforce write-back does not map entity_type '{write.entity_type}'"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        api = "v59.0"
        # guarded_async_client (not raw httpx): pins the connect-time IP against
        # DNS-rebind and forces follow_redirects off, so a tenant-supplied
        # instance_url cannot be rebound/redirected to internal/metadata hosts.
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
            if write.external_id:
                url = f"{instance}/services/data/{api}/sobjects/{sobject}/{write.external_id}"
                resp = await client.patch(url, json=write.payload, headers=headers)
                if resp.status_code >= 400:
                    return f"HTTP {resp.status_code}: {resp.text[:300]}"
                return None
            # CREATE - idempotent like the Zendesk/Jira/ServiceNow adapters: stamp
            # the idem token into Description as a [kaeos:<idem>] marker and
            # SOQL-probe for it first, so a lost create response cannot duplicate
            # the record. Marker charset excludes SOQL LIKE wildcards (% _) and
            # quotes, so it is safe to inline into the query literal.
            marker = "kaeos:" + re.sub(r"[^A-Za-z0-9.-]", "-", idem)[:60]
            # nosec B608 - not attacker-controlled: sobject is one of two hardcoded
            # literals (Account/Opportunity, else an early return above) and marker
            # is sanitized to [A-Za-z0-9.-] so it cannot carry SOQL wildcards/quotes.
            soql = f"SELECT Id FROM {sobject} WHERE Description LIKE '%{marker}%' LIMIT 1"  # nosec B608
            probe = await client.get(f"{instance}/services/data/{api}/query",
                                     headers=headers, params={"q": soql})
            if probe.status_code < 400 and (probe.json().get("records") or []):
                return None
            payload = dict(write.payload or {})
            desc = str(payload.get("Description") or "").strip()
            payload["Description"] = (f"{desc}\n[{marker}]" if desc else f"[{marker}]")
            resp = await client.post(
                f"{instance}/services/data/{api}/sobjects/{sobject}",
                json=payload, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
        return None

    if provider == "workday":
        # Real Workday write-back needs a customer tenant + ISU credentials;
        # there is no public sandbox. The adapter shape is here so it activates
        # at deployment - until then the outcome is an HONEST failure state.
        return ("workday write-back requires a customer Workday tenant and ISU "
                "credentials (no public sandbox exists); configure them to activate")

    return f"no write-back adapter for provider '{provider}'"


# ServiceNow entity_type -> Table API table name.
_SERVICENOW_TABLE = {"incident": "incident", "task": "task", "sc_task": "sc_task",
                     "problem": "problem", "change": "change_request"}


def _outbound_fields(write: OutboundWrite) -> Dict[str, Any]:
    """The actual SoR field dict for any adapter. Actuation queues
    {system, operation, state}; a direct queue_outbound passes the fields as the
    payload itself. Shared by every write-back adapter below."""
    state = write.payload.get("state") if isinstance(write.payload, dict) else None
    return dict(state) if isinstance(state, dict) else dict(write.payload or {})


async def _write_servicenow(config: Dict[str, Any], secrets: Dict[str, Any],
                            write: OutboundWrite, idem: str) -> Optional[str]:
    """ServiceNow Table API write-back for incidents/tasks. Basic auth.

    Idempotent creates: the idempotency token is stamped on ServiceNow's native
    ``correlation_id`` field and we query for it before creating, so a create
    whose HTTP response was lost is not duplicated on the retry - the second
    attempt finds the existing record and returns success instead of a duplicate.
    Updates target the record by sys_id (our external_id).
    """
    instance = (config.get("instance_url") or "").rstrip("/")
    if not instance:
        return "servicenow connector has no instance_url configured"
    user, pwd = secrets.get("username", ""), secrets.get("password", "")
    if not user:
        return "servicenow connector missing username/password"
    table = config.get("table") or _SERVICENOW_TABLE.get(write.entity_type, "incident")
    fields = _outbound_fields(write)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    base = f"{instance}/api/now/table/{table}"

    async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=(user, pwd)) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.delete(f"{base}/{write.external_id}", headers=headers)
            if resp.status_code >= 400 and resp.status_code != 404:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        if write.external_id:
            # UPDATE by sys_id.
            resp = await client.patch(f"{base}/{write.external_id}", json=fields, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on correlation_id. If a prior attempt already
        # created the record (response lost), do not create a second one.
        probe = await client.get(base, headers=headers, params={
            "sysparm_query": f"correlation_id={idem}", "sysparm_limit": 1,
            "sysparm_fields": "sys_id"})
        if probe.status_code < 400 and (probe.json().get("result") or []):
            return None
        fields = {**fields, "correlation_id": idem}
        resp = await client.post(base, json=fields, headers=headers)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def _write_zendesk(config: Dict[str, Any], secrets: Dict[str, Any],
                         write: OutboundWrite, idem: str) -> Optional[str]:
    """Zendesk API v2 ticket write-back. Basic auth '{email}/token' + api_token
    (the same credentials the inbound ZendeskAdapter uses).

    Idempotent creates: the idem token is stamped on the ticket's native
    ``external_id`` field and searched for before the create, so a create whose
    HTTP response was lost is not duplicated - the retry finds the existing
    ticket and returns success. Updates/deletes target the ticket by its Zendesk
    id (our external_id).
    """
    base = (config.get("subdomain_url") or "").rstrip("/")
    if not base:
        return "zendesk connector has no subdomain_url configured"
    email, token = secrets.get("email", ""), secrets.get("api_token", "")
    if not email or not token:
        return "zendesk connector missing email/api_token"
    auth = (f"{email}/token", token)
    fields = _outbound_fields(write)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=auth) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.delete(f"{base}/api/v2/tickets/{write.external_id}.json",
                                       headers=headers)
            if resp.status_code >= 400 and resp.status_code != 404:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        if write.external_id:
            resp = await client.put(f"{base}/api/v2/tickets/{write.external_id}.json",
                                    json={"ticket": fields}, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on the ticket's external_id field.
        probe = await client.get(f"{base}/api/v2/search.json", headers=headers,
                                 params={"query": f"type:ticket external_id:{idem}"})
        if probe.status_code < 400 and (probe.json().get("results") or []):
            return None
        resp = await client.post(f"{base}/api/v2/tickets.json",
                                 json={"ticket": {**fields, "external_id": idem}},
                                 headers=headers)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def _write_jira(config: Dict[str, Any], secrets: Dict[str, Any],
                      write: OutboundWrite, idem: str) -> Optional[str]:
    """Jira Cloud REST v3 issue write-back. Basic auth email + api_token (the
    same credentials the inbound JiraAdapter uses).

    Idempotent creates: the idem token is carried as a ``kaeos-<idem>`` label and
    searched via JQL before the create, so a lost response does not duplicate the
    issue. Updates/deletes target the issue by key (our external_id). A create
    needs project + issuetype; connector config may supply defaults
    (``project_key`` / ``issue_type``) so a bare payload still lands.

    ponytail: field writes only. A Jira status change is a POST to the
    /transitions endpoint, not a field, so a `status` field is a no-op here;
    add a transitions call if a tenant needs governed status moves.
    """
    base = (config.get("base_url") or "").rstrip("/")
    if not base:
        return "jira connector has no base_url configured"
    email, api_token = secrets.get("email", ""), secrets.get("api_token", "")
    if not email or not api_token:
        return "jira connector missing email/api_token"
    auth = (email, api_token)
    fields = _outbound_fields(write)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=auth) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.delete(f"{base}/rest/api/3/issue/{write.external_id}",
                                       headers=headers)
            if resp.status_code >= 400 and resp.status_code != 404:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        if write.external_id:
            resp = await client.put(f"{base}/rest/api/3/issue/{write.external_id}",
                                    json={"fields": fields}, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on a kaeos-<idem> label (Jira labels forbid spaces).
        label = "kaeos-" + re.sub(r"[^A-Za-z0-9_.-]", "-", idem)[:60]
        probe = await client.get(f"{base}/rest/api/3/search", headers=headers,
                                 params={"jql": f'labels = "{label}"', "maxResults": 1})
        if probe.status_code < 400 and (probe.json().get("issues") or []):
            return None
        create_fields: Dict[str, Any] = {}
        if config.get("project_key"):
            create_fields["project"] = {"key": config["project_key"]}
        if config.get("issue_type"):
            create_fields["issuetype"] = {"name": config["issue_type"]}
        create_fields.update(fields)   # payload wins over config defaults
        create_fields["labels"] = [*create_fields.get("labels", []), label]
        resp = await client.post(f"{base}/rest/api/3/issue",
                                 json={"fields": create_fields}, headers=headers)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def _write_slack(config: Dict[str, Any], secrets: Dict[str, Any],
                       write: OutboundWrite, idem: str) -> Optional[str]:
    """Slack Web API chat.postMessage. Bearer bot token (the same the inbound
    SlackAdapter uses). Channel comes from the payload or the connector config.

    Slack returns HTTP 200 with ``ok:false`` on API errors, so the JSON body is
    checked, not just the status code.

    ponytail: chat.postMessage has no server-side idempotency and is append-only,
    so a lost-response retry can post a duplicate. The idem token is stamped into
    the message's event metadata for downstream dedup; a client-side sent-token
    cache is the upgrade if duplicates ever matter.
    """
    bot_token = secrets.get("bot_token", "")
    if not bot_token:
        return "slack connector missing bot_token"
    fields = _outbound_fields(write)
    channel = fields.get("channel") or config.get("channel_id")
    if not channel:
        return "slack write-back has no channel (set channel_id in config or payload)"
    text = fields.get("text") or fields.get("message") or ""
    if not text:
        return "slack write-back has no message text"
    body = {"channel": channel, "text": text,
            "metadata": {"event_type": "kaeos_writeback",
                         "event_payload": {"idempotency_key": idem}}}
    headers = {"Authorization": f"Bearer {bot_token}",
               "Content-Type": "application/json; charset=utf-8"}
    base = (config.get("api_url") or "https://slack.com").rstrip("/")
    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{base}/api/chat.postMessage",
                                 json=body, headers=headers)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        if not data.get("ok"):
            return f"Slack API error: {data.get('error', 'unknown')}"
    return None


# HubSpot entity_type -> CRM v3 object type.
_HUBSPOT_OBJECT = {"account": "companies", "opportunity": "deals", "contact": "contacts"}


async def _write_hubspot(config: Dict[str, Any], secrets: Dict[str, Any],
                         write: OutboundWrite, idem: str) -> Optional[str]:
    """HubSpot CRM v3 object write-back. Private-app Bearer access_token (the
    same credential the inbound HubSpotAdapter uses).

    Idempotent creates: the idem token is stamped on a ``kaeos_idem`` property
    and searched via the CRM search API before the create, so a create whose
    HTTP response was lost is not duplicated - the retry finds the existing
    object and returns success. Updates PATCH by HubSpot object id (our
    external_id); deletes archive the object (HubSpot's delete semantics).

    ponytail: kaeos_idem must exist as a custom single-line-text property on
    the object type in the portal - without it both the search probe and the
    create return HTTP 400, surfacing as an honest FAILED. Upgrade path:
    auto-create the property via /crm/v3/properties on the first 400.
    """
    base = (config.get("api_url") or "https://api.hubapi.com").rstrip("/")
    token = secrets.get("access_token", "")
    if not token:
        return "hubspot connector missing access_token"
    obj = config.get("object_type") or _HUBSPOT_OBJECT.get(write.entity_type, "deals")
    fields = _outbound_fields(write)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json"}
    objects = f"{base}/crm/v3/objects/{obj}"

    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.delete(f"{objects}/{write.external_id}", headers=headers)
            if resp.status_code >= 400 and resp.status_code != 404:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        if write.external_id:
            resp = await client.patch(f"{objects}/{write.external_id}",
                                      json={"properties": fields}, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on the kaeos_idem property.
        probe = await client.post(f"{objects}/search", headers=headers, json={
            "filterGroups": [{"filters": [{"propertyName": "kaeos_idem",
                                           "operator": "EQ", "value": idem}]}],
            "limit": 1})
        if probe.status_code < 400 and (probe.json().get("results") or []):
            return None
        resp = await client.post(objects, headers=headers,
                                 json={"properties": {**fields, "kaeos_idem": idem}})
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def _write_github(config: Dict[str, Any], secrets: Dict[str, Any],
                        write: OutboundWrite, idem: str) -> Optional[str]:
    """GitHub REST v3 issue write-back. Bearer personal access token (the same
    credential the inbound GitHubAdapter uses); owner/repo from connector config.

    Idempotent creates: the idem token is stamped into the issue body as a
    ``[kaeos:<idem>]`` marker and searched via the issue search API before the
    create, so a lost response does not duplicate the issue. Updates PATCH the
    issue by number (our external_id).

    ponytail: DELETE closes the issue as not_planned and leaves an honest
    comment saying so - GitHub has no REST issue delete for normal tokens
    (delete needs the GraphQL deleteIssue mutation + admin rights); wire that
    mutation if hard deletes ever matter.
    """
    base = (config.get("api_url") or "https://api.github.com").rstrip("/")
    token = secrets.get("token", "")
    if not token:
        return "github connector missing token"
    owner, repo = config.get("owner", ""), config.get("repo", "")
    if not owner or not repo:
        return "github connector missing owner/repo in config"
    fields = _outbound_fields(write)
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    issues = f"{base}/repos/{owner}/{repo}/issues"
    # Marker charset excludes quotes/brackets so it is safe inside the search
    # query literal and the [kaeos:...] body marker (same idiom as salesforce).
    marker = "kaeos:" + re.sub(r"[^A-Za-z0-9.-]", "-", idem)[:60]

    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.patch(f"{issues}/{write.external_id}", headers=headers,
                                      json={"state": "closed", "state_reason": "not_planned"})
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            # Honest trace on the issue itself; best-effort (the close already landed).
            await client.post(f"{issues}/{write.external_id}/comments", headers=headers,
                              json={"body": "KAEOS delete: GitHub does not allow deleting "
                                            "issues via the REST API, so this issue was "
                                            f"closed as not planned instead. [{marker}]"})
            return None

        if write.external_id:
            resp = await client.patch(f"{issues}/{write.external_id}",
                                      json=fields, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on the [kaeos:<idem>] body marker via issue search.
        probe = await client.get(f"{base}/search/issues", headers=headers,
                                 params={"q": f'repo:{owner}/{repo} in:body "{marker}"',
                                         "per_page": 1})
        if probe.status_code < 400 and (probe.json().get("items") or []):
            return None
        if not fields.get("title"):
            return "github issue create needs a title in the payload"
        body_text = str(fields.get("body") or "").strip()
        payload = {**fields,
                   "body": f"{body_text}\n\n[{marker}]" if body_text else f"[{marker}]"}
        resp = await client.post(issues, json=payload, headers=headers)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def _write_pagerduty(config: Dict[str, Any], secrets: Dict[str, Any],
                           write: OutboundWrite, idem: str) -> Optional[str]:
    """PagerDuty REST v2 incident write-back. ``Token token=<api_key>`` auth
    (the same credential the inbound PagerDutyAdapter uses) plus the ``From``
    header (a PagerDuty user email) when configured - PagerDuty requires it on
    incident writes.

    Idempotent creates: the REST /incidents endpoint natively dedups on
    ``incident_key`` per service, but a retried create with the same key gets
    HTTP 400 (matching open incident), so we probe GET /incidents?incident_key=
    first and report the retry as success instead of a failure.

    ponytail: DELETE resolves the incident with a note saying so - PagerDuty
    has no incident delete at all; no upgrade path exists, that is the API.
    """
    base = (config.get("api_url") or "https://api.pagerduty.com").rstrip("/")
    api_key = secrets.get("api_key", "")
    if not api_key:
        return "pagerduty connector missing api_key"
    fields = _outbound_fields(write)
    headers = {"Authorization": f"Token token={api_key}",
               "Accept": "application/vnd.pagerduty+json;version=2",
               "Content-Type": "application/json"}
    if config.get("from_email"):
        headers["From"] = str(config["from_email"])

    async with guarded_async_client(timeout=HTTP_TIMEOUT) as client:
        if write.op == "DELETE" and write.external_id:
            resp = await client.put(
                f"{base}/incidents/{write.external_id}", headers=headers,
                json={"incident": {"type": "incident_reference", "status": "resolved",
                                   "resolution": "Resolved by KAEOS: PagerDuty incidents "
                                                 "cannot be deleted, so this delete was "
                                                 "applied as a resolve."}})
            if resp.status_code >= 400 and resp.status_code != 404:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        if write.external_id:
            resp = await client.put(f"{base}/incidents/{write.external_id}", headers=headers,
                                    json={"incident": {"type": "incident_reference", **fields}})
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
            return None

        # CREATE - idempotent on incident_key (probe first: PagerDuty rejects a
        # duplicate key with HTTP 400, which must read as success on a retry).
        probe = await client.get(f"{base}/incidents", headers=headers,
                                 params={"incident_key": idem, "limit": 1})
        if probe.status_code < 400 and (probe.json().get("incidents") or []):
            return None
        service_id = fields.get("service_id") or config.get("service_id")
        if not service_id:
            return "pagerduty incident create needs a service_id (config or payload)"
        title = fields.get("title") or fields.get("summary")
        if not title:
            return "pagerduty incident create needs a title in the payload"
        incident = {k: v for k, v in fields.items() if k != "service_id"}
        incident.update({"type": "incident", "title": title, "incident_key": idem,
                         "service": {"id": service_id, "type": "service_reference"}})
        resp = await client.post(f"{base}/incidents", headers=headers,
                                 json={"incident": incident})
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def dispatch_outbound(tenant_id: Optional[str] = None, limit: int = 25) -> Dict[str, int]:
    """Deliver PENDING/FAILED-retryable outbound writes through connectors.

    Runs on the MAINTENANCE (owner) session: the scheduled dispatcher scans
    across tenants with no request context, and under Postgres RLS a tenant-less
    app-role session sets no ``app.tenant_id`` GUC, so the SELECT would match
    ZERO rows and write-backs would never dispatch. The owner role is RLS-exempt;
    isolation is preserved because delivery filters connectors by the write's own
    ``tenant_id``.
    """
    from app.core.database import MaintenanceSessionLocal

    sent = failed = skipped = dead = 0
    async with MaintenanceSessionLocal() as db:
        # DEAD is terminal: attempts >= MAX_ATTEMPTS are never reselected, so a
        # poison write can no longer sit at the head of the queue forever.
        q = select(OutboundWrite).where(OutboundWrite.status.in_(("PENDING", "FAILED")),
                                        OutboundWrite.attempts < MAX_ATTEMPTS)
        if tenant_id:
            q = q.where(OutboundWrite.tenant_id == tenant_id)
        writes = (await db.execute(q.order_by(OutboundWrite.created_at).limit(limit))).scalars().all()

        for w in writes:
            # CRIT: each write is isolated. One dead outbound endpoint (an adapter
            # that raises, e.g. httpx ConnectError/timeout) must fail ONLY its own
            # row - without this guard the exception unwound the whole batch loop
            # before commit, rolling back every attempts++ and status write, so the
            # oldest poison row was reselected every tick and froze the queue for
            # every tenant. We catch, mark this row FAILED/DEAD, and carry on.
            w.attempts = (w.attempts or 0) + 1
            try:
                err = await _deliver_one(db, w)
            except Exception as e:  # noqa: BLE001 - isolation is the whole point
                err = f"{type(e).__name__}: {str(e)[:280]}"
                logger.warning("[Sync] outbound write %s raised: %s", w.id, err)

            if err is None:
                w.status = "SENT"
                w.last_error = None
                sent += 1
            elif err.startswith("SKIPPED_"):
                w.status, w.last_error = err.split(":", 1)
                skipped += 1
            elif w.attempts >= MAX_ATTEMPTS:
                w.status = "DEAD"
                w.last_error = f"DEAD after {w.attempts} attempts: {err[:860]}"
                dead += 1
            else:
                w.status = "FAILED"
                w.last_error = err[:900]
                failed += 1
            # Per-write durability: commit each row on its own so a DB-level error
            # on one write cannot roll back its already-processed siblings.
            try:
                await db.commit()
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                logger.error("[Sync] commit failed for outbound write %s: %s", w.id, e)
    return {"sent": sent, "failed": failed, "skipped": skipped, "dead": dead}


async def _deliver_one(db: AsyncSession, w: OutboundWrite) -> Optional[str]:
    """Route one outbound write to a connector and push it. Returns:
    None on success, ``SKIPPED_<STATE>:<reason>`` for honest no-op states, or a
    plain error string for a (retryable) failure. Writes a SyncLedger OUT row.
    Raising is allowed - the caller isolates it per write.
    """
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import decrypt_secrets

    cq = select(Connector).where(Connector.tenant_id == w.tenant_id,
                                 Connector.status.in_(("CONNECTED", "SYNCING")))
    connectors = (await db.execute(cq)).scalars().all()
    target = None
    _SN_ENTITIES = set(_SERVICENOW_TABLE)
    for c in connectors:
        cred = (await db.execute(select(ConnectorCredential).where(
            ConnectorCredential.connector_id == c.id))).scalar_one_or_none()
        prov = (cred.provider if cred else None)
        if w.provider and prov == w.provider:
            target = (c, cred)
            break
        if not w.provider and w.category and (c.category or "").lower() == w.category:
            target = (c, cred)
            break
        if not w.provider and prov == "servicenow" and w.entity_type in _SN_ENTITIES:
            target = (c, cred)
            break
        if not w.provider and prov == "generic_rest" and target is None:
            target = (c, cred)   # generic sink accepts anything

    if target is None:
        return (f"SKIPPED_NO_CONNECTOR:no CONNECTED connector for "
                f"provider={w.provider or '-'} category={w.category or '-'}")
    connector, cred = target
    if cred is None:
        return f"SKIPPED_NO_CREDENTIALS:connector '{connector.name}' has no stored credentials"
    secrets = decrypt_secrets(cred.secrets_encrypted)

    err = await _write_via_adapter(cred.provider, cred, cred.config or {}, secrets, w)
    db.add(SyncLedger(
        tenant_id=w.tenant_id, connector_id=connector.id,
        provider=cred.provider, direction="OUT",
        entity_type=w.entity_type, external_id=w.external_id,
        internal_id=w.internal_id, op=w.op,
        status="APPLIED" if err is None else "FAILED", detail=err,
    ))
    return err
