"""
KAEOS Operations Domain — Projects Models
"""
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Float, Date
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ProjectStatus(str, enum.Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class Project(Base):
    """Corporate programs and strategic projects."""
    __tablename__ = "ops_projects"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(256), nullable=False)
    description = Column(String(512), nullable=True)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.PLANNING)
    
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    
    project_manager_id = Column(String, ForeignKey("ops_team_members.id"), nullable=True)
    completion_percentage = Column(Float, default=0.00) # 0 to 100

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Milestone(Base):
    """Key deliverables/dates composing projects."""
    __tablename__ = "ops_project_milestones"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("ops_projects.id"), nullable=False, index=True)

    name = Column(String(128), nullable=False)
    target_date = Column(Date, nullable=False)
    is_reached = Column(Enum(ProjectStatus), nullable=True) # Used for checking or ignored
    status = Column(String(32), default="PENDING") # PENDING, ACHIEVED

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Task(Base):
    """Granular project tasks assigned to team members."""
    __tablename__ = "ops_project_tasks"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, ForeignKey("ops_projects.id"), nullable=False, index=True)

    task_name = Column(String(256), nullable=False)
    assigned_to = Column(String(128), nullable=True)
    
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="TODO") # TODO, IN_PROGRESS, DONE
    
    ai_risk_assessment = Column(String(512), nullable=True) # AI warning flag if critical path is blocked

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TaskDependency(Base):
    """Pre-requisites mapping task execution sequences."""
    __tablename__ = "ops_task_dependencies"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    task_id = Column(String, ForeignKey("ops_project_tasks.id"), nullable=False, index=True)
    depends_on_task_id = Column(String, ForeignKey("ops_project_tasks.id"), nullable=False)
