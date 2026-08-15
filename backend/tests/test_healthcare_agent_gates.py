"""
Healthcare agents wired through the gated pipeline and the workflow engine
(previously dead code - never imported or called from any route or test).

Covers: IntakeAgent.triage_encounter, CodingAgent.suggest_codes,
PriorAuthAgent.prepare_prior_auth (all now route status writes through
app.core.workflow.apply_transition instead of a raw field assignment), and
PHIGuardAgent.review_disclosure (the agent path for the PHI-disclosure gate).
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.workflow import WorkflowEvent
from app.healthcare.agents.coding_agent import CodingAgent
from app.healthcare.agents.intake_agent import IntakeAgent
from app.healthcare.agents.phi_guard_agent import PHI_TAGS, PHIGuardAgent
from app.healthcare.agents.prior_auth_agent import PriorAuthAgent
from app.healthcare.models.core import ClinicalTask, PatientEncounter, PHIDisclosure

TENANT = "tenant_hlth_agents"
ACTOR = {"tenant_id": TENANT, "role": "operator", "name": "test_operator"}


@pytest.fixture(autouse=True)
def _stub_hitl_and_fairness(monkeypatch):
    """hitl_manager.request_human_confirmation and FairnessEngine.score_fairness
    each open their OWN session directly against app.core.database's real
    engine, which the in-memory test fixture (test_engine, see conftest.py)
    never creates tables on - only the get_db-overridden session does. Every
    other gate-pipeline test in this repo stubs HITL out for the same reason
    (see tests/test_gate_integrity.py's _FakeHITL); these tests are about the
    healthcare agent/workflow wiring, not the HITL/fairness infrastructure."""
    from app.services.fairness_engine import FairnessEngine
    from app.services.hitl_manager import hitl_manager as _hitl

    async def _fake_confirm(skill, context):
        return {"pending": True, "execution_id": context.get("execution_id", "test-exec")}

    monkeypatch.setattr(_hitl, "request_human_confirmation", _fake_confirm)
    monkeypatch.setattr(FairnessEngine, "requires_fairness_check", lambda self, skill, context: False)


async def _seed_encounter(db, **overrides) -> PatientEncounter:
    kw = {
        "encounter_number": "ENC-A-1", "patient_ref": "pt-anon-1",
        "encounter_type": "office_visit", "status": "OPEN",
        "reason": "chest pain, ruled out ACS",
    }
    kw.update(overrides)
    enc = PatientEncounter(tenant_id=TENANT, **kw)
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc


def test_phi_tags_include_deidentification():
    # The agent-gate tag list must be at least as strict as the deterministic
    # service path (PHI_FRAMEWORKS in phi_disclosure.py), which always ran
    # HIPAA_DEIDENTIFICATION - the agent path must not be weaker.
    assert "HIPAA_DEIDENTIFICATION" in PHI_TAGS
    assert set(PHI_TAGS) == {
        "HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION", "HIPAA_DEIDENTIFICATION", "PART2",
    }


@pytest.mark.asyncio
async def test_triage_transitions_open_to_triaged_via_workflow(db):
    enc = await _seed_encounter(db, reason="chest pain, ruled out ACS")
    result = await IntakeAgent().triage_encounter(db, enc.id, ACTOR)

    assert result["priority"] == "EMERGENT"
    # always_hitl=True on every healthcare skill: a clean run lands on
    # PENDING_HITL, the expected governed outcome.
    assert result["status"] == "PENDING_HITL"

    await db.refresh(enc)
    assert enc.status == "TRIAGED"
    assert enc.priority == "EMERGENT"

    events = (await db.execute(select(WorkflowEvent).where(
        WorkflowEvent.entity_id == enc.id))).scalars().all()
    assert len(events) == 1
    assert events[0].from_state == "OPEN"
    assert events[0].to_state == "TRIAGED"
    assert events[0].domain == "healthcare"


@pytest.mark.asyncio
async def test_retriage_of_an_already_triaged_encounter_is_rejected(db):
    enc = await _seed_encounter(db, encounter_number="ENC-A-2", status="TRIAGED")
    with pytest.raises(HTTPException) as exc:
        await IntakeAgent().triage_encounter(db, enc.id, ACTOR)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_triage_unknown_encounter_raises_value_error(db):
    with pytest.raises(ValueError):
        await IntakeAgent().triage_encounter(db, "does-not-exist", ACTOR)


@pytest.mark.asyncio
async def test_suggest_codes_creates_task_moved_open_to_in_progress(db):
    enc = await _seed_encounter(db, encounter_number="ENC-A-3", reason="ankle sprain")
    result = await CodingAgent().suggest_codes(db, enc.id, ACTOR)

    assert result["task_id"]
    task = (await db.execute(select(ClinicalTask).where(
        ClinicalTask.id == result["task_id"]))).scalar_one()
    assert task.status == "IN_PROGRESS"
    assert task.task_type == "coding"
    assert task.encounter_id == enc.id

    events = (await db.execute(select(WorkflowEvent).where(
        WorkflowEvent.entity_id == task.id))).scalars().all()
    assert len(events) == 1
    assert events[0].from_state == "OPEN"
    assert events[0].to_state == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_prior_auth_creates_task_with_procedure_and_payer(db):
    enc = await _seed_encounter(db, encounter_number="ENC-A-4", reason="chronic low back pain")
    result = await PriorAuthAgent().prepare_prior_auth(
        db, ACTOR, encounter_id=enc.id, procedure="MRI lumbar spine", payer="Aetna",
    )

    task = (await db.execute(select(ClinicalTask).where(
        ClinicalTask.id == result["task_id"]))).scalar_one()
    assert task.status == "IN_PROGRESS"
    assert task.task_type == "prior_auth"
    assert task.detail["procedure"] == "MRI lumbar spine"
    assert task.detail["payer"] == "Aetna"


@pytest.mark.asyncio
async def test_phi_guard_agent_records_a_clean_disclosure(db):
    result = await PHIGuardAgent().review_disclosure(
        db, TENANT, purpose="payment", recipient="Acme Payer",
        fields=["name", "dob", "member_id", "procedure_codes"],
        minimum_necessary_justification="submitting the claim to the payer",
        recorded_by="test_operator",
    )
    assert result["recorded"] is True
    assert result["status"] == "RECORDED"
    disc = (await db.execute(select(PHIDisclosure).where(
        PHIDisclosure.id == result["disclosure_id"]))).scalar_one()
    assert disc.authorized is True


@pytest.mark.asyncio
async def test_phi_guard_agent_blocks_excess_fields_and_records_nothing(db):
    # ssn is beyond the minimum-necessary field set for 'payment' -> the
    # deterministic gate BLOCKs before the governance pipeline even runs.
    result = await PHIGuardAgent().review_disclosure(
        db, TENANT, purpose="payment", recipient="Acme Payer",
        fields=["name", "dob", "member_id", "ssn"],
        minimum_necessary_justification="billing the claim",
    )
    assert result["recorded"] is False
    assert result["status"] == "BLOCKED_COMPLIANCE"

    rows = (await db.execute(select(PHIDisclosure).where(
        PHIDisclosure.tenant_id == TENANT))).scalars().all()
    assert rows == []
