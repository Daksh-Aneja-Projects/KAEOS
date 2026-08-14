"""
KAEOS Healthcare — Analytics Service

Real SQL aggregates over tenant data, returned in the shared domain-analytics
shape the frontend DomainAnalytics component renders:

  { domain, kpis: [{key,label,value,format}], charts: [...], insights: [...] }

Honesty contract: a metric the platform cannot actually measure is returned as
value=None with a note, never a fabricated 0.
"""
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.healthcare.models.core import (
    ClinicalTask, ConsentRecord, PatientEncounter, PHIDisclosure,
)


async def healthcare_analytics(db: AsyncSession, tenant_id: str,
                               charts: bool = True) -> dict:
    # Encounters by status.
    enc_q = await db.execute(
        select(PatientEncounter.status, sqlfunc.count())
        .where(PatientEncounter.tenant_id == tenant_id)
        .group_by(PatientEncounter.status)
    )
    enc_by_status = {s: int(c) for s, c in enc_q.all()}
    total_encounters = sum(enc_by_status.values())
    open_encounters = enc_by_status.get("OPEN", 0) + enc_by_status.get("TRIAGED", 0)

    # Disclosures recorded (only authorized ones are ever persisted).
    disc_count = int((await db.execute(
        select(sqlfunc.count()).select_from(PHIDisclosure)
        .where(PHIDisclosure.tenant_id == tenant_id)
    )).scalar() or 0)
    part2_disc = int((await db.execute(
        select(sqlfunc.count()).select_from(PHIDisclosure)
        .where(PHIDisclosure.tenant_id == tenant_id, PHIDisclosure.part2 == True)  # noqa: E712
    )).scalar() or 0)

    # Active consents (revoked_at IS NULL).
    active_consents = int((await db.execute(
        select(sqlfunc.count()).select_from(ConsentRecord)
        .where(ConsentRecord.tenant_id == tenant_id,
               ConsentRecord.revoked_at.is_(None))
    )).scalar() or 0)

    # Clinical tasks by status.
    task_q = await db.execute(
        select(ClinicalTask.status, sqlfunc.count())
        .where(ClinicalTask.tenant_id == tenant_id)
        .group_by(ClinicalTask.status)
    )
    task_by_status = {s: int(c) for s, c in task_q.all()}
    open_tasks = sum(v for k, v in task_by_status.items() if k not in ("DONE",))

    insights = []
    if open_tasks:
        insights.append({"severity": "info",
                         "message": f"{open_tasks} clinical tasks are open (coding / prior-auth)."})
    if part2_disc:
        insights.append({"severity": "warning",
                         "message": f"{part2_disc} disclosures touched 42 CFR Part 2 substance-use records - consent-gated."})
    if not insights:
        insights.append({"severity": "info", "message": "No clinical operations anomalies detected this cycle."})

    charts_out = [
        {"key": "enc_status", "title": "Encounters by Status", "type": "donut",
         "items": [{"label": k, "value": v} for k, v in enc_by_status.items()]},
        {"key": "task_status", "title": "Clinical Tasks by Status", "type": "bar",
         "items": [{"label": k, "value": v} for k, v in task_by_status.items()]},
    ] if charts else []

    return {
        "domain": "healthcare",
        "kpis": [
            {"key": "encounters", "label": "Total Encounters", "value": total_encounters, "format": "number"},
            {"key": "open_encounters", "label": "Open Encounters", "value": open_encounters, "format": "number"},
            {"key": "disclosures", "label": "PHI Disclosures (authorized)", "value": disc_count, "format": "number"},
            {"key": "active_consents", "label": "Active Consents", "value": active_consents, "format": "number"},
            {"key": "open_tasks", "label": "Open Clinical Tasks", "value": open_tasks, "format": "number"},
            # Honesty contract: we do not observe downstream re-disclosure by the
            # recipient, so a "PHI leakage rate" is genuinely unmeasurable here.
            {"key": "phi_leakage_rate", "label": "Downstream PHI Leakage Rate",
             "value": None, "format": "percent",
             "note": "Not measurable: KAEOS gates disclosures at the boundary but "
                     "cannot observe a recipient's downstream handling."},
        ],
        "charts": charts_out,
        "insights": insights,
    }
