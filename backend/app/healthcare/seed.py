"""
KAEOS Healthcare Domain - Database Seed Script

Comprehensive, realistic demo data for tenant_acme: a mix of encounter types and
acuities, PHI disclosures that exercise the HIPAA minimum-necessary / authorization
/ Part 2 governance (some clean, some deliberately thin so the gate story shows),
consent records (incl. a revoked one and a 42 CFR Part 2 substance-use consent),
and clinical tasks across the coding / prior-auth / referral workflow.

Pseudonymous patient refs only - NO real protected health information.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from app.core.database import AsyncSessionLocal, async_engine
from app.healthcare.models.core import (
    ClinicalTask, ConsentRecord, PatientEncounter, PHIDisclosure,
)
from app.models.domain import Base

TENANT = "tenant_acme"


def _id() -> str:
    return str(uuid.uuid4())


def _ago(days=0, hours=0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # ── Encounters: varied type / acuity / status ────────────────────────
        encounters = [
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0001",
                             patient_ref="pt-anon-4821", encounter_type="office_visit",
                             status="COMPLETED", reason="annual wellness visit",
                             priority="ROUTINE", diagnosis_codes=["Z00.00"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0002",
                             patient_ref="pt-anon-7735", encounter_type="telehealth",
                             status="IN_PROGRESS", reason="medication follow-up, generalized anxiety",
                             priority="ROUTINE", diagnosis_codes=["F41.1"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0003",
                             patient_ref="pt-anon-1190", encounter_type="emergency",
                             status="DISCHARGED", reason="chest pain, ruled out ACS",
                             priority="EMERGENT", diagnosis_codes=["R07.9", "I20.9"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0004",
                             patient_ref="pt-anon-3357", encounter_type="inpatient",
                             status="IN_PROGRESS", reason="community-acquired pneumonia",
                             priority="URGENT", diagnosis_codes=["J18.9"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0005",
                             patient_ref="pt-anon-8842", encounter_type="outpatient_surgery",
                             status="COMPLETED", reason="arthroscopic knee repair",
                             priority="ROUTINE", diagnosis_codes=["M23.51"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0006",
                             patient_ref="pt-anon-5501", encounter_type="behavioral_health",
                             status="OPEN", reason="substance-use disorder intake",
                             priority="URGENT", diagnosis_codes=["F10.20"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0007",
                             patient_ref="pt-anon-6620", encounter_type="imaging",
                             status="TRIAGED", reason="MRI lumbar spine, chronic low back pain",
                             priority="ROUTINE", diagnosis_codes=["M54.5"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-2026-0008",
                             patient_ref="pt-anon-9014", encounter_type="telehealth",
                             status="COMPLETED", reason="hypertension management",
                             priority="ROUTINE", diagnosis_codes=["I10"]),
        ]
        db.add_all(encounters)
        await db.flush()
        by_ref = {e.patient_ref: e for e in encounters}

        # ── PHI disclosures: TPO (clean) + non-TPO (needs authorization) + Part 2
        disclosures = [
            PHIDisclosure(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-4821"].id,
                          purpose="treatment", recipient="Dr. Alvarez, Cardiology (referral)",
                          fields=["problem_list", "medications", "recent_labs"],
                          minimum_necessary_justification=(
                              "Referral for cardiology consult; only the problem list, active "
                              "medications and the most recent lipid panel are shared - the "
                              "minimum needed for the consulting physician to assess risk."),
                          part2=False, authorized=True, recorded_by="intake_agent"),
            PHIDisclosure(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-8842"].id,
                          purpose="payment", recipient="Blue Shield claims processing",
                          fields=["procedure_codes", "date_of_service", "provider_npi"],
                          minimum_necessary_justification=(
                              "Claim adjudication for the knee procedure; only the CPT codes, "
                              "date of service and rendering provider are disclosed."),
                          part2=False, authorized=True, recorded_by="coding_agent"),
            PHIDisclosure(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-1190"].id,
                          purpose="operations", recipient="Internal quality review (ED throughput)",
                          fields=["encounter_timestamps", "disposition"],
                          minimum_necessary_justification=(
                              "Operational ED-throughput audit; timestamps and disposition only, "
                              "no clinical detail or identifiers beyond the encounter key."),
                          part2=False, authorized=True, recorded_by="phi_guard_agent"),
            # Non-TPO: research - requires patient authorization (recorded here as authorized)
            PHIDisclosure(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-3357"].id,
                          purpose="research", recipient="Pneumonia outcomes registry (IRB-2026-114)",
                          fields=["diagnosis_codes", "age_band", "outcome"],
                          minimum_necessary_justification=(
                              "De-identified-adjacent research submission under signed patient "
                              "authorization and IRB approval; age is banded, no direct identifiers."),
                          part2=False, authorized=True, recorded_by="phi_guard_agent"),
            # Part 2 substance-use disclosure - gated by 42 CFR Part 2 consent
            PHIDisclosure(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-5501"].id,
                          purpose="treatment", recipient="County recovery program (care coordination)",
                          fields=["treatment_plan", "medications"],
                          minimum_necessary_justification=(
                              "Care-coordination handoff to the recovery program; treatment plan "
                              "and MAT medications only, under the patient's Part 2 consent."),
                          part2=True, authorized=True, recorded_by="phi_guard_agent"),
        ]
        db.add_all(disclosures)

        # ── Consents (incl. a Part 2 grant and a revoked one) ────────────────
        consents = [
            ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-4821",
                          scope="treatment_payment_operations", part2=False, granted_at=_ago(days=400)),
            ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-5501",
                          scope="part2_substance_use_disclosure", part2=True, granted_at=_ago(days=6)),
            ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-3357",
                          scope="research_participation", part2=False, granted_at=_ago(days=30)),
            ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-7735",
                          scope="telehealth", part2=False, granted_at=_ago(days=90)),
            # Revoked marketing consent - the read path must treat this as no-consent.
            ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-9014",
                          scope="marketing_outreach", part2=False,
                          granted_at=_ago(days=120), revoked_at=_ago(days=10)),
        ]
        db.add_all(consents)

        # ── Clinical tasks across coding / prior-auth / referral ─────────────
        tasks = [
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-8842"].id,
                         task_type="coding", status="COMPLETED", assignee="coding_agent",
                         detail={"codes": ["29881"], "reviewed": True}),
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-6620"].id,
                         task_type="prior_auth", status="IN_PROGRESS", assignee="prior_auth_agent",
                         detail={"payer": "Aetna", "service": "MRI lumbar", "status": "submitted"}),
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-4821"].id,
                         task_type="referral", status="OPEN", assignee="intake_agent",
                         detail={"to": "Cardiology", "reason": "abnormal lipid panel"}),
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-3357"].id,
                         task_type="coding", status="OPEN", assignee="coding_agent",
                         detail={"pending": "await discharge summary"}),
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-7735"].id,
                         task_type="follow_up", status="OPEN", assignee="intake_agent",
                         detail={"interval_weeks": 4}),
            ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=by_ref["pt-anon-5501"].id,
                         task_type="prior_auth", status="BLOCKED", assignee="prior_auth_agent",
                         detail={"payer": "Medicaid", "service": "MAT", "blocker": "awaiting Part 2 consent verification"}),
        ]
        db.add_all(tasks)

        await db.commit()
        print("[SUCCESS] Seeded Healthcare database:")
        print(f"   - {len(encounters)} encounters, {len(disclosures)} PHI disclosures, "
              f"{len(consents)} consents, {len(tasks)} clinical tasks")


if __name__ == "__main__":
    asyncio.run(seed())
