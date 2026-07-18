"""KAEOS — Pydantic Schemas: Elicitation"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class QuestionResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: str
    department: str
    question_text: str
    question_type: str
    context_ref: Optional[str] = None
    priority: str
    status: str
    delivery_channel: str
    specificity: float
    groundedness: float
    answerability: float
    created_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnswerSubmit(BaseModel):
    question_id: str
    answer_text: str
    answerer_hash: str = "anonymous"


class EmployeeContribution(BaseModel):
    employee_id: str
    display_name: str
    department: str
    role: str
    total_contributions: int
    confirmed_contributions: int
    reputation_score: float
    response_rate: float
    badge: Optional[str] = None  # "Knowledge Expert", etc.


class ElicitationDashboardResponse(BaseModel):
    pending_questions: List[QuestionResponse]
    recent_answers: List[QuestionResponse]
    contributors: List[EmployeeContribution]
    stats: Dict[str, Any]
