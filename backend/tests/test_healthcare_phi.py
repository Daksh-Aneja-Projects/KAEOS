"""
Healthcare PHI disclosure gate — fail-closed control tests (deterministic, no LLM).

A disclosure that violates the HIPAA minimum-necessary or authorization rule is
BLOCKED and never recorded; a clean disclosure is recorded and authorized.
"""
import pytest
from sqlalchemy import func, select

from app.healthcare.models.core import PHIDisclosure
from app.healthcare.services.phi_disclosure import (
    PHIDisclosureError, evaluate_disclosure, record_disclosure, build_context,
)

TENANT = "tenant_test_hlth"


async def _disclosure_count(db) -> int:
    return int((await db.execute(
        select(func.count()).select_from(PHIDisclosure)
        .where(PHIDisclosure.tenant_id == TENANT))).scalar() or 0)


@pytest.mark.asyncio
async def test_minimum_necessary_violation_blocked_and_not_recorded(db):
    # payment is TPO (no auth needed) but 'ssn' is beyond the minimum-necessary
    # field set for payment -> HIPAA_MINIMUM_NECESSARY BLOCK.
    with pytest.raises(PHIDisclosureError) as exc:
        await record_disclosure(
            db, TENANT, purpose="payment", recipient="Acme Payer",
            fields=["name", "dob", "member_id", "ssn"],
            minimum_necessary_justification="billing the claim",
        )
    assert exc.value.blocking, "should carry the blocking findings"
    assert await _disclosure_count(db) == 0, "blocked disclosure must not be persisted"


@pytest.mark.asyncio
async def test_non_tpo_without_authorization_blocked(db):
    # marketing is neither TPO nor a 164.512 permitted purpose -> needs a signed
    # authorization. None on file -> HIPAA_AUTHORIZATION BLOCK.
    with pytest.raises(PHIDisclosureError):
        await record_disclosure(
            db, TENANT, purpose="marketing", recipient="AdCo",
            fields=["name"], minimum_necessary_justification="promo",
        )
    assert await _disclosure_count(db) == 0


@pytest.mark.asyncio
async def test_clean_payment_disclosure_recorded(db):
    disc = await record_disclosure(
        db, TENANT, purpose="payment", recipient="Acme Payer",
        fields=["name", "dob", "member_id", "procedure_codes"],
        minimum_necessary_justification="submitting the claim to the payer",
    )
    assert disc.id and disc.authorized is True
    assert await _disclosure_count(db) == 1


@pytest.mark.asyncio
async def test_missing_justification_refused_before_gate(db):
    with pytest.raises(PHIDisclosureError):
        await record_disclosure(
            db, TENANT, purpose="payment", recipient="Acme Payer",
            fields=["name"], minimum_necessary_justification="   ",
        )
    assert await _disclosure_count(db) == 0


def test_evaluate_disclosure_is_pure_and_verifies_clean():
    ctx = build_context(purpose="payment", fields=["name", "member_id"])
    verdict = evaluate_disclosure(ctx)
    assert verdict["verified"] is True and not verdict["blocking"]
