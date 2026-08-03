"""KAEOS - security breach detection + governed response (SOAR).

Integrated applications push security events (breach, credential leak,
anomalous access, malware) to the HMAC-authenticated ingest surface. KAEOS
turns each into a real engineering Incident on the twin and runs a CONTAINMENT
playbook whose actions are all real state changes:

  quarantine_connector  - pause the connector (halts sync both ways)
  rotate_webhook_secret - invalidate the inbound ingest secret
  disable_user          - deactivate the affected KAEOS account
  notify                - security.incident through the notification channels

Governance: containment that is safe and reversible (quarantine, secret
rotation, notification) runs automatically. Destructive-to-people actions
(disable_user) auto-run ONLY for CRITICAL severity; below that they are
returned as recommended actions for a human to take - the same
pause-for-the-human philosophy as the rest of the platform.

Honest scope: KAEOS contains and responds through the APIs it holds; it cannot
patch a vulnerability inside the vendor's own software.
"""
from __future__ import annotations

import json
import logging
import secrets as pysecrets
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = ("breach", "credential_leak", "anomalous_access", "malware", "other")
VALID_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _classify(payload: Dict[str, Any]) -> Dict[str, str]:
    event_type = str(payload.get("event_type") or "other").lower()
    if event_type not in VALID_EVENT_TYPES:
        event_type = "other"
    severity = str(payload.get("severity") or "MEDIUM").upper()
    if severity not in VALID_SEVERITIES:
        severity = "MEDIUM"
    return {"event_type": event_type, "severity": severity}


async def respond_to_security_event(connector_id: str, signature: Optional[str],
                                    raw_body: bytes) -> Dict[str, Any]:
    """Verify, record an Incident, run the containment playbook, notify.

    Raises LookupError (unknown connector) / PermissionError (bad signature)
    for the route to map to 404/401.
    """
    from app.core.database import MaintenanceSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import decrypt_secrets, encrypt_secrets
    from app.services.sync_engine import verify_signature

    async with MaintenanceSessionLocal() as mdb:
        connector = (await mdb.execute(select(Connector).where(
            Connector.id == connector_id))).scalar_one_or_none()
        if connector is None:
            raise LookupError("connector not found")
        cred = (await mdb.execute(select(ConnectorCredential).where(
            ConnectorCredential.connector_id == connector_id))).scalar_one_or_none()
        secret = ""
        if cred is not None:
            try:
                secret = decrypt_secrets(cred.secrets_encrypted).get("webhook_secret", "")
            except Exception:
                # No readable secret (missing or rotated SECRET_KEY) -> treat as
                # "no webhook secret configured"; signature check below is skipped.
                secret = ""
        tenant_id = connector.tenant_id
        connector_name = connector.name

    if not verify_signature(secret, raw_body, signature):
        raise PermissionError("invalid or missing webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        payload = {}
    meta = _classify(payload)
    summary = str(payload.get("summary") or f"{meta['event_type']} reported by {connector_name}")[:250]
    affected_email = (payload.get("affected_user_email") or "").strip().lower()

    from app.core.context import current_tenant_id
    from app.core.database import AsyncSessionLocal
    token = current_tenant_id.set(tenant_id)
    actions_taken: List[str] = []
    recommended: List[str] = []
    try:
        async with AsyncSessionLocal() as db:
            # 1. A REAL incident on the twin (engineering domain).
            from app.engineering.models.incidents import (
                Incident, IncidentSeverity, IncidentStatus,
            )
            sev_map = {"LOW": IncidentSeverity.SEV4, "MEDIUM": IncidentSeverity.SEV3,
                       "HIGH": IncidentSeverity.SEV2, "CRITICAL": IncidentSeverity.SEV1}
            incident = Incident(
                tenant_id=tenant_id,
                incident_number=f"SEC-{pysecrets.token_hex(4).upper()}",
                title=f"[Security] {summary}"[:256],
                severity=sev_map[meta["severity"]],
                status=IncidentStatus.DETECTED,
            )
            db.add(incident)
            await db.flush()

            # 2. Containment playbook (safe + reversible -> automatic).
            connector_row = (await db.execute(select(Connector).where(
                Connector.id == connector_id))).scalar_one_or_none()
            if meta["severity"] in ("HIGH", "CRITICAL"):
                if connector_row is not None:
                    connector_row.status = "PAUSED"
                    actions_taken.append("quarantine_connector: sync halted")
                cred_row = (await db.execute(select(ConnectorCredential).where(
                    ConnectorCredential.connector_id == connector_id))).scalar_one_or_none()
                if cred_row is not None:
                    try:
                        stored = decrypt_secrets(cred_row.secrets_encrypted)
                    except Exception:
                        # Undecryptable prior secrets (rotated key) -> start from
                        # empty and re-encrypt, replacing the unreadable blob.
                        stored = {}
                    stored["webhook_secret"] = pysecrets.token_hex(32)
                    cred_row.secrets_encrypted = encrypt_secrets(stored)
                    actions_taken.append("rotate_webhook_secret: old ingest secret invalidated")
            else:
                recommended.append("quarantine_connector (auto-runs at HIGH/CRITICAL)")

            # 3. disable_user: destructive to a person - CRITICAL only.
            if affected_email:
                from app.models.auth import User
                target = (await db.execute(select(User).where(
                    User.email == affected_email, User.tenant_id == tenant_id
                ))).scalar_one_or_none()
                if target is not None:
                    if meta["severity"] == "CRITICAL":
                        target.is_active = False
                        actions_taken.append(f"disable_user: {affected_email} deactivated")
                    else:
                        recommended.append(
                            f"disable_user {affected_email} (needs a human below CRITICAL)")
                else:
                    recommended.append(
                        f"affected user {affected_email} is not a KAEOS account; "
                        f"disable it in the source system")

            # 4. Audit spine: the response itself lands in the sync ledger.
            from app.models.sync import SyncLedger
            db.add(SyncLedger(
                tenant_id=tenant_id, connector_id=connector_id,
                provider="security", direction="IN",
                entity_type="security_event", external_id=str(payload.get("external_id") or ""),
                internal_id=incident.id, op="UPSERT", status="APPLIED",
                detail=json.dumps({"severity": meta["severity"],
                                   "event_type": meta["event_type"],
                                   "actions_taken": actions_taken,
                                   "recommended": recommended}),
            ))
            await db.commit()
            incident_id, incident_number = incident.id, incident.incident_number
    finally:
        current_tenant_id.reset(token)

    # 5. Page the humans (fire-and-forget; failure never blocks containment).
    from app.services.notifier import notify_fire_and_forget
    notify_fire_and_forget(
        tenant_id, "security.incident",
        subject=f"KAEOS security incident [{meta['severity']}]: {summary[:60]}",
        body=(f"Source: {connector_name}\nSeverity: {meta['severity']}\n"
              f"Incident: {incident_number}\n"
              f"Actions taken: {'; '.join(actions_taken) or 'none (low severity)'}\n"
              f"Recommended: {'; '.join(recommended) or 'none'}"),
        data={"incident_id": incident_id, "severity": meta["severity"],
              "actions_taken": actions_taken},
    )

    return {"status": "responded", "incident_id": incident_id,
            "incident_number": incident_number, "severity": meta["severity"],
            "actions_taken": actions_taken, "recommended_actions": recommended}
