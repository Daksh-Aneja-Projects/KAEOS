"""
KAEOS Engineering Domain — Ops Models (on-call rotations + CI pipeline runs)

On-call rotation gives the incident agent a real "who is paged right now"
signal instead of only the static Engineer.on_call flag. Pipeline runs give
the deploy-risk agent real build/test history to reason over, instead of only
the PR-level ci_passing flag at the moment a single PR was last reviewed.
"""
from sqlalchemy import Column, String, DateTime, Enum, Integer, ForeignKey
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class OnCallRole(str, enum.Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class OnCallRotation(Base):
    """A scheduled on-call shift: one engineer, one squad, one time window."""
    __tablename__ = "eng_oncall_rotations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    engineer_id = Column(String, ForeignKey("eng_engineers.id"), nullable=False, index=True)
    squad = Column(String(64), nullable=False)
    role = Column(Enum(OnCallRole), default=OnCallRole.PRIMARY)

    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PipelineStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class PipelineRun(Base):
    """One CI pipeline execution for a service — the build/test history the
    deploy-risk agent reasons over, not just a single PR's ci_passing flag."""
    __tablename__ = "eng_pipeline_runs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    service_id = Column(String, ForeignKey("eng_services.id"), nullable=True, index=True)
    pull_request_id = Column(String, ForeignKey("eng_pull_requests.id"), nullable=True, index=True)

    pipeline_name = Column(String(64), nullable=False)
    run_number = Column(Integer, nullable=False)
    status = Column(Enum(PipelineStatus), default=PipelineStatus.PENDING)
    trigger = Column(String(16), nullable=True)     # PUSH | PULL_REQUEST | SCHEDULE | MANUAL
    branch = Column(String(128), nullable=True)
    commit_sha = Column(String(40), nullable=True)

    tests_passed = Column(Integer, nullable=True)
    tests_failed = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
