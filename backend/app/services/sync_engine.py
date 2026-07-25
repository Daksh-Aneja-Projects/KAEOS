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
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import OutboundWrite, SyncLedger

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0
CANONICAL_ENTITIES = ("employee", "account", "opportunity", "ticket", "incident")

# entity_type -> connector category expected to receive its write-backs
_ENTITY_CATEGORY = {
    "employee": "hris",
    "account": "crm",
    "opportunity": "crm",
    "ticket": "support",
    "incident": "engineering",
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
                row.amount = float(data["amount"])
            except (TypeError, ValueError):
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

async def queue_outbound(tenant_id: str, entity_type: str, internal_id: str,
                         op: str, payload: Dict[str, Any],
                         external_id: Optional[str] = None,
                         provider: Optional[str] = None,
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

    if provider == "generic_rest":
        base = (config.get("base_url") or "").rstrip("/")
        if not base:
            return "generic_rest connector has no base_url configured"
        headers = {"Content-Type": "application/json"}
        if secrets.get("api_key"):
            headers["Authorization"] = f"Bearer {secrets['api_key']}"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(f"{base}/kaeos/sync", json=body, headers=headers)
            if resp.status_code >= 400:
                return f"HTTP {resp.status_code}: {resp.text[:300]}"
        return None

    if provider == "salesforce":
        instance = (config.get("instance_url") or "").rstrip("/")
        token = secrets.get("access_token")
        if not instance or not token:
            return None if False else "salesforce connector missing instance_url/access_token"
        sobject = {"account": "Account", "opportunity": "Opportunity"}.get(write.entity_type)
        if sobject is None:
            return f"salesforce write-back does not map entity_type '{write.entity_type}'"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if write.external_id:
                url = f"{instance}/services/data/v59.0/sobjects/{sobject}/{write.external_id}"
                resp = await client.patch(url, json=write.payload, headers=headers)
            else:
                url = f"{instance}/services/data/v59.0/sobjects/{sobject}"
                resp = await client.post(url, json=write.payload, headers=headers)
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


async def dispatch_outbound(tenant_id: Optional[str] = None, limit: int = 25) -> Dict[str, int]:
    """Deliver PENDING/FAILED-retryable outbound writes through connectors."""
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import decrypt_secrets

    sent = failed = skipped = 0
    async with AsyncSessionLocal() as db:
        q = select(OutboundWrite).where(OutboundWrite.status.in_(("PENDING", "FAILED")),
                                        OutboundWrite.attempts < 5)
        if tenant_id:
            q = q.where(OutboundWrite.tenant_id == tenant_id)
        writes = (await db.execute(q.order_by(OutboundWrite.created_at).limit(limit))).scalars().all()

        for w in writes:
            w.attempts = (w.attempts or 0) + 1
            # Find a CONNECTED connector for the write's provider/category.
            cq = select(Connector).where(Connector.tenant_id == w.tenant_id,
                                         Connector.status.in_(("CONNECTED", "SYNCING")))
            connectors = (await db.execute(cq)).scalars().all()
            target = None
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
                if not w.provider and prov == "generic_rest" and target is None:
                    target = (c, cred)   # generic sink accepts anything

            if target is None:
                w.status = "SKIPPED_NO_CONNECTOR"
                w.last_error = (f"no CONNECTED connector for "
                                f"provider={w.provider or '-'} category={w.category or '-'}")
                skipped += 1
                continue
            connector, cred = target
            if cred is None:
                w.status = "SKIPPED_NO_CREDENTIALS"
                w.last_error = f"connector '{connector.name}' has no stored credentials"
                skipped += 1
                continue
            try:
                secrets = decrypt_secrets(cred.secrets_encrypted)
            except Exception as e:
                w.status = "FAILED"
                w.last_error = f"credential decrypt failed: {e}"
                failed += 1
                continue

            err = await _write_via_adapter(cred.provider, cred, cred.config or {},
                                           secrets, w)
            if err is None:
                w.status = "SENT"
                w.last_error = None
                sent += 1
            else:
                w.status = "FAILED"
                w.last_error = err[:900]
                failed += 1
            db.add(SyncLedger(
                tenant_id=w.tenant_id, connector_id=connector.id,
                provider=cred.provider, direction="OUT",
                entity_type=w.entity_type, external_id=w.external_id,
                internal_id=w.internal_id, op=w.op,
                status="APPLIED" if err is None else "FAILED", detail=err,
            ))
        await db.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped}
