"""
KAEOS HR Vertical — Learning & Development
Function 7: Learning & Development
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Enum, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CourseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"

class Course(Base):
    """A training or development course."""
    __tablename__ = "hr_learning_courses"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    provider = Column(String(128), nullable=True) # Internal, Coursera, Udemy
    
    is_required_for_compliance = Column(Boolean, default=False)
    estimated_minutes = Column(Integer, default=60)
    
    status = Column(Enum(CourseStatus), default=CourseStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class EnrollmentStatus(str, enum.Enum):
    ENROLLED = "ENROLLED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"

class CourseEnrollment(Base):
    __tablename__ = "hr_learning_enrollments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False)
    course_id = Column(String, ForeignKey("hr_learning_courses.id"), nullable=False)
    
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED)
    progress_pct = Column(Float, default=0.0)
    
    assigned_by_id = Column(String, ForeignKey("hr_employees.id"), nullable=True) # Who assigned this
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
