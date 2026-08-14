"""
KAEOS Healthcare Domain — Database Seed Script

Seeds a couple of demo encounters, a consent, and a clinical task for
tenant_acme. Pseudonymous refs only - NO real protected health information.
"""
import asyncio
import uuid

from app.core.database import AsyncSessionLocal, async_engine
from app.healthcare.models.core import (
    ClinicalTask, ConsentRecord, PatientEncounter,
)
from app.models.domain import Base

TENANT = "tenant_acme"


def _id() -> str:
    return str(uuid.uuid4())


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        encounters = [
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-DEMO-001",
                             patient_ref="pt-anon-4821", encounter_type="office_visit",
                             status="TRIAGED", reason="annual wellness visit",
                             priority="ROUTINE", diagnosis_codes=["Z00.00"]),
            PatientEncounter(id=_id(), tenant_id=TENANT, encounter_number="ENC-DEMO-002",
                             patient_ref="pt-anon-7735", encounter_type="telehealth",
                             status="OPEN", reason="medication follow-up",
                             priority="ROUTINE", diagnosis_codes=["F41.1"]),
        ]
        db.add_all(encounters)
        await db.flush()

        db.add(ConsentRecord(id=_id(), tenant_id=TENANT, patient_ref="pt-anon-4821",
                             scope="treatment", part2=False))
        db.add(ClinicalTask(id=_id(), tenant_id=TENANT, encounter_id=encounters[0].id,
                            task_type="coding", status="OPEN"))

        await db.commit()
        print("[SUCCESS] Seeded Healthcare database:")
        print(f"   - {len(encounters)} encounters, 1 consent, 1 clinical task")


if __name__ == "__main__":
    asyncio.run(seed())
