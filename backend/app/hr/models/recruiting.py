"""
KAEOS HR Vertical — Recruiting Models
Function 2: Talent Acquisition
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ReqStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"

class JobRequisition(Base):
    __tablename__ = "hr_job_requisitions"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    title = Column(String(128), nullable=False)
    department = Column(String(128), nullable=False)
    hiring_manager_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    
    status = Column(Enum(ReqStatus), default=ReqStatus.DRAFT)
    headcount = Column(Integer, default=1)
    
    # Compensation Target
    target_salary_min = Column(Integer, nullable=True)
    target_salary_max = Column(Integer, nullable=True)
    currency = Column(String(3), default="USD")
    
    # Description
    job_description = Column(Text, nullable=False)
    requirements = Column(JSON, default=list) # Required skills, exp
    
    # AI Config
    ai_screening_enabled = Column(Boolean, default=True)
    ai_screening_criteria = Column(JSON, default=dict)
    
    opened_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CandidateStage(str, enum.Enum):
    APPLIED = "APPLIED"
    AI_SCREENING = "AI_SCREENING"
    RECRUITER_SCREEN = "RECRUITER_SCREEN"
    HM_INTERVIEW = "HM_INTERVIEW"
    PANEL_INTERVIEW = "PANEL_INTERVIEW"
    OFFER_PREP = "OFFER_PREP"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"

class Candidate(Base):
    __tablename__ = "hr_candidates"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    requisition_id = Column(String, ForeignKey("hr_job_requisitions.id"), nullable=False)
    
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    email = Column(String(128), nullable=False)
    phone = Column(String(32), nullable=True)
    resume_path = Column(String(512), nullable=True)
    
    stage = Column(Enum(CandidateStage), default=CandidateStage.APPLIED)
    
    # AI Evaluation
    ai_score = Column(Float, nullable=True) # 0-100 match score
    ai_summary = Column(Text, nullable=True)
    ai_red_flags = Column(JSON, default=list)
    ai_culture_add_score = Column(Float, nullable=True)
    
    # Compliance
    eeoc_data = Column(JSON, nullable=True) # Stored encrypted or isolated
    
    applied_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Interview(Base):
    __tablename__ = "hr_interviews"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    candidate_id = Column(String, ForeignKey("hr_candidates.id"), nullable=False)
    interviewer_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    duration_mins = Column(Integer, default=60)
    interview_type = Column(String(64), nullable=False) # e.g., "Technical", "Behavioral"
    
    # AI Assistance
    ai_generated_questions = Column(JSON, default=list)
    
    # Feedback
    feedback_submitted = Column(Boolean, default=False)
    score = Column(Integer, nullable=True) # 1-5
    notes = Column(Text, nullable=True)
    recommendation = Column(String(32), nullable=True) # STRONG_HIRE, HIRE, NO_HIRE
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
