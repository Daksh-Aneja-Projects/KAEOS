"""KAEOS — Elicitation API (L5 Active Elicitation + HITL)"""
from app.core.tenant import get_tenant_id, require_role
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone, timedelta
import uuid

from app.core.database import get_db
from app.models.domain import (
    ElicitationQuestion, Employee,
)
from app.schemas.elicitation import (
    QuestionResponse, AnswerSubmit, EmployeeContribution,
    ElicitationDashboardResponse,
)
from app.services.confidence import ConfidenceEngine

router = APIRouter(prefix="/elicitation", tags=["Elicitation — L5 HITL"])
confidence_engine = ConfidenceEngine()


@router.get("/dashboard", response_model=ElicitationDashboardResponse)
async def elicitation_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Full elicitation dashboard: pending questions, recent answers, contributors."""
    # Pending questions with employee info
    pending_q = await db.execute(
        select(ElicitationQuestion, Employee)
        .join(Employee, ElicitationQuestion.employee_id == Employee.id)
        .where(ElicitationQuestion.tenant_id == tenant_id, ElicitationQuestion.status == "PENDING")
        .order_by(ElicitationQuestion.created_at.desc())
    )
    pending = []
    for eq, emp in pending_q.all():
        pending.append(QuestionResponse(
            id=eq.id,
            employee_id=eq.employee_id,
            employee_name=emp.display_name or "Unknown",
            department=emp.department or "Unknown",
            question_text=eq.question_text,
            question_type=eq.question_type or "GAP_FILL",
            context_ref=eq.context_ref,
            priority=eq.priority or "NORMAL",
            status=eq.status,
            delivery_channel=eq.delivery_channel or "slack",
            specificity=eq.specificity or 0.0,
            groundedness=eq.groundedness or 0.0,
            answerability=eq.answerability or 0.0,
            created_at=eq.created_at,
            answered_at=eq.answered_at,
        ))

    # Recent answers
    answered_q = await db.execute(
        select(ElicitationQuestion, Employee)
        .join(Employee, ElicitationQuestion.employee_id == Employee.id)
        .where(ElicitationQuestion.tenant_id == tenant_id, ElicitationQuestion.status == "ANSWERED")
        .order_by(ElicitationQuestion.answered_at.desc())
        .limit(20)
    )
    recent = []
    for eq, emp in answered_q.all():
        recent.append(QuestionResponse(
            id=eq.id,
            employee_id=eq.employee_id,
            employee_name=emp.display_name or "Unknown",
            department=emp.department or "Unknown",
            question_text=eq.question_text,
            question_type=eq.question_type or "GAP_FILL",
            context_ref=eq.context_ref,
            priority=eq.priority or "NORMAL",
            status=eq.status,
            delivery_channel=eq.delivery_channel or "slack",
            specificity=eq.specificity or 0.0,
            groundedness=eq.groundedness or 0.0,
            answerability=eq.answerability or 0.0,
            created_at=eq.created_at,
            answered_at=eq.answered_at,
        ))

    # Top contributors
    contribs_q = await db.execute(
        select(Employee)
        .where(Employee.tenant_id == tenant_id, Employee.total_contributions > 0)
        .order_by(Employee.reputation_score.desc())
        .limit(10)
    )
    contributors = []
    for e in contribs_q.scalars().all():
        badge = None
        if e.reputation_score >= 0.85:
            badge = "Knowledge Expert"
        elif e.reputation_score >= 0.7:
            badge = "Active Contributor"
        contributors.append(EmployeeContribution(
            employee_id=e.id,
            display_name=e.display_name or "Unknown",
            department=e.department or "Unknown",
            role=e.role or "IC",
            total_contributions=e.total_contributions,
            confirmed_contributions=e.confirmed_contributions,
            reputation_score=round(e.reputation_score, 3),
            response_rate=round(e.response_rate, 3),
            badge=badge,
        ))

    # Stats
    now = datetime.now(timezone.utc)
    now - timedelta(days=7)
    total_q = await db.execute(select(sqlfunc.count(ElicitationQuestion.id)))
    total_sent = total_q.scalar() or 0
    total_answered = await db.execute(
        select(sqlfunc.count(ElicitationQuestion.id)).where(
            ElicitationQuestion.tenant_id == tenant_id,
            ElicitationQuestion.status == "ANSWERED",
        )
    )
    answered_count = total_answered.scalar() or 0

    # Compute avg quality score from answered questions' quality dimensions
    avg_quality_q = await db.execute(
        select(
            sqlfunc.avg(ElicitationQuestion.specificity),
            sqlfunc.avg(ElicitationQuestion.groundedness),
            sqlfunc.avg(ElicitationQuestion.answerability),
        ).where(ElicitationQuestion.tenant_id == tenant_id, ElicitationQuestion.status == "ANSWERED")
    )
    avg_spec, avg_ground, avg_answer = avg_quality_q.one()
    avg_quality_score = round(
        ((avg_spec or 0) + (avg_ground or 0) + (avg_answer or 0)) / 3, 3
    ) if any([avg_spec, avg_ground, avg_answer]) else 0.0

    return ElicitationDashboardResponse(
        pending_questions=pending,
        recent_answers=recent,
        contributors=contributors,
        stats={
            "total_questions": total_sent,
            "total_answered": answered_count,
            "response_rate": round(answered_count / max(total_sent, 1), 3),
            "avg_quality_score": avg_quality_score,
            "questions_this_week": len(pending),
        },
    )


@router.post("/answer")
async def submit_answer(body: AnswerSubmit, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Process an elicitation answer — L5 Answer Processing Pipeline. Requires operator role (persists an answer + updates employee reputation)."""
    tenant_id = tenant["tenant_id"]
    result = await db.execute(
        select(ElicitationQuestion).where(ElicitationQuestion.id == body.question_id, ElicitationQuestion.tenant_id == tenant_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(404, "Question not found")
    if question.status == "ANSWERED":
        raise HTTPException(400, "Question already answered")

    # 1. Update question
    question.status = "ANSWERED"
    question.answer_text = body.answer_text
    question.answered_at = datetime.now(timezone.utc)

    # 2. Update employee contributions
    emp_result = await db.execute(
        select(Employee).where(Employee.id == question.employee_id, Employee.tenant_id == tenant_id)
    )
    employee = emp_result.scalar_one_or_none()
    if employee:
        employee.total_contributions += 1
        employee.confirmed_contributions += 1
        total = employee.total_contributions
        confirmed = employee.confirmed_contributions
        rejected = employee.rejected_contributions
        accuracy = confirmed / max(confirmed + rejected, 1)
        import math
        volume = math.log(1 + total) / math.log(100)
        employee.reputation_score = round(0.7 * accuracy + 0.3 * volume, 3)

    await db.commit()

    return {
        "status": "PROCESSED",
        "question_id": body.question_id,
        "answer_received": True,
        "employee_reputation_updated": employee is not None,
    }


class GenerateQuestionRequest(BaseModel):
    employee_id: str
    domain: str | None = None



@router.post("/generate")
async def generate_question(body: GenerateQuestionRequest, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """L5 — Use ElicitationEngine to generate an LLM-powered micro-survey question. Requires operator role (persists a question + incurs LLM cost)."""
    tenant_id = tenant["tenant_id"]
    from app.services.elicitation import ElicitationEngine

    emp_result = await db.execute(select(Employee).where(Employee.id == body.employee_id, Employee.tenant_id == tenant_id))
    employee = emp_result.scalar_one_or_none()
    if not employee:
        raise HTTPException(404, "Employee not found")

    if (employee.questions_this_week or 0) >= 3:
        return {"status": "SKIPPED_RATE_LIMIT", "message": "Max 3 questions/week reached"}

    # Find KB gaps as candidates
    gap_q = await db.execute(
        select(ElicitationQuestion)
        .where(
            ElicitationQuestion.tenant_id == tenant_id,
            ElicitationQuestion.employee_id == employee.id,
            ElicitationQuestion.status == "PENDING",
        )
        .limit(3)
    )
    candidates = [
        {"context_ref": q.context_ref, "action": q.question_type}
        for q in gap_q.scalars().all()
    ]

    engine = ElicitationEngine()
    result = await engine.generate_question(
        {"id": employee.id, "first_name": employee.display_name, "questions_this_week": employee.questions_this_week},
        candidates or [{"context_ref": "general_gap", "action": "knowledge_capture"}]
    )

    if result.get("status") == "GENERATED":
        # Persist the HEURISTIC quality scores computed by the engine from the
        # generated text (see services/elicitation.score_question_quality), not
        # hardcoded literals. These feed the dashboard's avg_quality_score, so
        # they must reflect the actual question rather than fabricated constants.
        quality = result.get("quality", {})
        eq = ElicitationQuestion(
            id=str(uuid.uuid4()),
            tenant_id=employee.tenant_id,
            employee_id=employee.id,
            question_text=result["question"],
            question_type="LLM_GENERATED",
            context_ref=body.domain or "general",
            priority="NORMAL",
            delivery_channel="slack",
            specificity=quality.get("specificity", 0.0),
            groundedness=quality.get("groundedness", 0.0),
            answerability=quality.get("answerability", 0.0),
        )
        db.add(eq)
        employee.questions_this_week = (employee.questions_this_week or 0) + 1
        await db.commit()
        return {"status": "GENERATED", "question_id": eq.id, "question": result["question"]}

    return result
