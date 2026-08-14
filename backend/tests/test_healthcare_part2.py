"""
Healthcare 42 CFR Part 2 consent gate tests (deterministic, no LLM).

Substance-use-disorder records (ICD-10 F10-F19 or a part2 flag) require specific
written consent before disclosure. Without it the disclosure is BLOCKED and not
recorded; with a signed consent an otherwise-clean disclosure is recorded.
"""
import pytest
from sqlalchemy import func, select

from app.healthcare.models.core import PHIDisclosure
from app.healthcare.services.phi_disclosure import (
    PHIDisclosureError, record_disclosure,
)

TENANT = "tenant_test_part2"


async def _count(db) -> int:
    return int((await db.execute(
        select(func.count()).select_from(PHIDisclosure)
        .where(PHIDisclosure.tenant_id == TENANT))).scalar() or 0)


@pytest.mark.asyncio
async def test_part2_sud_without_consent_blocked(db):
    # treatment is min-necessary exempt and TPO (auth N/A), but the SUD diagnosis
    # code triggers PART2, and no consent is on file -> BLOCK.
    with pytest.raises(PHIDisclosureError):
        await record_disclosure(
            db, TENANT, purpose="treatment", recipient="Referral Clinic",
            fields=["name", "diagnosis_codes"],
            minimum_necessary_justification="care coordination",
            diagnosis_codes=["F10.20"],
        )
    assert await _count(db) == 0


@pytest.mark.asyncio
async def test_part2_flag_without_consent_blocked(db):
    with pytest.raises(PHIDisclosureError):
        await record_disclosure(
            db, TENANT, purpose="treatment", recipient="Referral Clinic",
            fields=["name"], minimum_necessary_justification="care coordination",
            part2_records=True,
        )
    assert await _count(db) == 0


@pytest.mark.asyncio
async def test_part2_with_signed_consent_recorded(db):
    disc = await record_disclosure(
        db, TENANT, purpose="treatment", recipient="Referral Clinic",
        fields=["name", "diagnosis_codes"],
        minimum_necessary_justification="care coordination",
        diagnosis_codes=["F10.20"],
        part2_records=True,
        part2_consent={"signed": True},
    )
    assert disc.id and disc.part2 is True
    assert await _count(db) == 1


@pytest.mark.asyncio
async def test_part2_revoked_consent_blocked(db):
    with pytest.raises(PHIDisclosureError):
        await record_disclosure(
            db, TENANT, purpose="treatment", recipient="Referral Clinic",
            fields=["name"], minimum_necessary_justification="care coordination",
            part2_records=True, part2_consent={"signed": True, "revoked": True},
        )
    assert await _count(db) == 0
