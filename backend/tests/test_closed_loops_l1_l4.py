"""Closed loops L1 (outcome -> execution learning) and L4 (event-mesh -> outcome)."""
import uuid


from app.models.domain import Skill, SkillExecution
from app.models.event_mesh import ExternalSignal
from app.models.intelligence_metrics import OutcomeRecord
from app.models.missions import Mission
from app.services.missions.engine import _writeback_signal_on_finish
from app.api.routes.outcomes import record_outcome, OutcomeIn


T = "tenant_loops"


# ── L1: recording an outcome nudges confidence and leaves the lifecycle alone ──

async def test_record_outcome_learns_without_clobbering_lifecycle(db):
    """A measured outcome moves the skill's confidence, and does NOT overwrite the
    execution's lifecycle outcome_type - that field belongs to the SUCCESS_CLEAN /
    SUCCESS_WITH_EDIT / HUMAN_OVERRIDDEN vocabulary the metrics read."""
    ex = SkillExecution(id=str(uuid.uuid4()), tenant_id=T, skill_id_name="ops_x",
                        status="HUMAN_OVERRIDDEN", outcome_type="HUMAN_OVERRIDDEN",
                        hitl_required=False)
    db.add(ex)
    db.add(Skill(id=str(uuid.uuid4()), skill_id="ops_x", tenant_id=T,
                 department="operations", status="ACTIVE", confidence=0.5))
    await db.commit()

    tenant = {"tenant_id": T, "role": "operator", "name": "op"}
    out = await record_outcome(ex.id, OutcomeIn(outcome="GOOD"), tenant=tenant, db=db)
    assert out["outcome"] == "GOOD"
    assert out["new_confidence"] == 0.52          # L1: reality moved the confidence

    from sqlalchemy import select
    refreshed = (await db.execute(select(SkillExecution).where(SkillExecution.id == ex.id))).scalar_one()
    assert refreshed.outcome_type == "HUMAN_OVERRIDDEN"   # not erased by "GOOD"
    rec = (await db.execute(
        select(OutcomeRecord).where(OutcomeRecord.execution_id == ex.id))).scalar_one()
    assert rec.outcome == "GOOD"                  # the measured verdict has its own home


# ── L4: an event-mesh mission finishing closes the signal + writes an outcome ──

def _signal(mission_id):
    return ExternalSignal(id=str(uuid.uuid4()), tenant_id=T, kind="VENDOR",
                          title="vendor outage", response_kind="MISSION",
                          response_ref=mission_id, status="RESPONDED")


async def test_event_mesh_mission_writeback_closes_signal_and_records_outcome(db):
    m = Mission(id=str(uuid.uuid4()), tenant_id=T, goal="mitigate outage",
                status="COMPLETED", created_by="event-mesh")
    db.add(m)
    db.add(_signal(m.id))
    await db.commit()

    await _writeback_signal_on_finish(db, m)
    await db.commit()

    from sqlalchemy import select
    sig = (await db.execute(select(ExternalSignal).where(ExternalSignal.response_ref == m.id))).scalar_one()
    assert sig.status == "RESOLVED"
    rec = (await db.execute(select(OutcomeRecord).where(OutcomeRecord.execution_id == m.id))).scalar_one()
    assert rec.outcome == "GOOD" and rec.autonomous is True


async def test_writeback_is_idempotent_and_scoped_to_event_mesh(db):
    # A non-event-mesh mission must NOT touch signals.
    m_manual = Mission(id=str(uuid.uuid4()), tenant_id=T, goal="g", status="COMPLETED", created_by="user")
    db.add(m_manual)
    db.add(_signal(m_manual.id))
    await db.commit()
    await _writeback_signal_on_finish(db, m_manual)
    await db.commit()
    from sqlalchemy import select, func
    sig = (await db.execute(select(ExternalSignal).where(ExternalSignal.response_ref == m_manual.id))).scalar_one()
    assert sig.status == "RESPONDED"   # untouched

    # An event-mesh mission: second call adds no duplicate outcome.
    m = Mission(id=str(uuid.uuid4()), tenant_id=T, goal="g2", status="FAILED", created_by="event-mesh")
    db.add(m)
    db.add(_signal(m.id))
    await db.commit()
    await _writeback_signal_on_finish(db, m)
    await db.commit()
    await _writeback_signal_on_finish(db, m)   # idempotent
    await db.commit()
    n = (await db.execute(select(func.count()).select_from(OutcomeRecord)
                          .where(OutcomeRecord.execution_id == m.id))).scalar_one()
    assert n == 1
    rec = (await db.execute(select(OutcomeRecord).where(OutcomeRecord.execution_id == m.id))).scalar_one()
    assert rec.outcome == "BAD"   # FAILED mission -> BAD outcome
