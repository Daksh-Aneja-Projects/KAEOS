"""
KAEOS Engineering Domain — Delivery Models (pull requests + deployments)
"""
from sqlalchemy import Column, String, DateTime, Enum, Text, Integer, Float, Boolean, JSON, ForeignKey
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class PRStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DeployStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class PullRequest(Base):
    """A code change under review — the unit the code-review agent reasons over."""
    __tablename__ = "eng_pull_requests"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    service_id = Column(String, ForeignKey("eng_services.id"), nullable=True, index=True)

    number = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    author_id = Column(String, ForeignKey("eng_engineers.id"), nullable=True)
    branch = Column(String(128), nullable=True)

    status = Column(Enum(PRStatus), default=PRStatus.OPEN)

    # Change surface — drives risk scoring.
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    files_changed = Column(Integer, default=0)
    touches_migrations = Column(Boolean, default=False)
    touches_auth = Column(Boolean, default=False)
    test_coverage_delta = Column(Float, nullable=True)  # percentage points

    ci_passing = Column(Boolean, default=True)
    approvals = Column(Integer, default=0)

    # AI review output (written by the code review agent).
    ai_risk_level = Column(Enum(RiskLevel), nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_findings = Column(JSON, default=list)
    ai_reviewed_at = Column(DateTime(timezone=True), nullable=True)

    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    merged_at = Column(DateTime(timezone=True), nullable=True)


class Deployment(Base):
    """A release to an environment — gated by the deploy-risk agent."""
    __tablename__ = "eng_deployments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    service_id = Column(String, ForeignKey("eng_services.id"), nullable=True, index=True)
    pull_request_id = Column(String, ForeignKey("eng_pull_requests.id"), nullable=True)

    version = Column(String(64), nullable=False)
    environment = Column(String(32), default="production")  # dev | staging | production
    status = Column(Enum(DeployStatus), default=DeployStatus.PENDING_APPROVAL)

    deployed_by = Column(String(128), nullable=True)
    change_count = Column(Integer, default=1)
    is_rollback = Column(Boolean, default=False)

    # AI risk assessment (written by the deploy risk agent).
    ai_risk_level = Column(Enum(RiskLevel), nullable=True)
    ai_risk_score = Column(Float, nullable=True)   # 0-100, higher = riskier
    ai_rationale = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
