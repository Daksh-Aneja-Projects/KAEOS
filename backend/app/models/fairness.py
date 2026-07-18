"""KAEOS — Fairness & Ethical AI Models (AEOS P3)
EU AI Act Article 13 + GDPR Article 22 compliant audit trail.
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, ForeignKey,
    Text, JSON,
)
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class FairnessAuditLog(Base):
    """Records every fairness assessment for HCM-touching agent actions.
    
    Every action that touches Employee/HCM data is scored against
    minimum 5 protected attributes. This log satisfies:
    - GDPR Article 22: Right to meaningful information about automated decisions
    - EU AI Act Article 13: Transparency for high-risk AI systems
    """
    __tablename__ = 'fairness_audit_logs'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Correlation id, NOT a foreign key: the fairness gate (Gate 2) writes its
    # audit row BEFORE any SkillExecution exists (Gate 3/5 create it), and a
    # blocked action never creates one. Postgres enforced the old FK and threw
    # ForeignKeyViolationError on every gated HR screen; SQLite had masked it.
    execution_id = Column(String, nullable=True, index=True)
    blueprint_id = Column(String, ForeignKey('agent_blueprints.id'), nullable=True)

    # Assessment result
    fairness_score = Column(Float, nullable=False)  # 0.0–1.0
    threshold_used = Column(Float, default=0.85)
    passed = Column(Boolean, nullable=False)

    # Protected attributes assessed
    protected_attributes_assessed = Column(JSON, default=lambda: [
        "gender", "ethnicity", "age", "disability", "nationality"
    ])
    
    # Detailed per-attribute scores
    attribute_scores = Column(JSON, default=dict)
    # Schema: { "gender": { score: 0.92, flag: false }, "age": { score: 0.71, flag: true }, ... }

    # Flagged attributes that showed potential bias
    flagged_attributes = Column(JSON, default=list)

    # LLM-generated rationale (plain language for regulators)
    rationale = Column(Text, nullable=False)

    # What was being assessed
    action_description = Column(Text, nullable=True)
    affected_entity_type = Column(String(32))  # Employee, Compensation, Schedule, Performance
    affected_entity_count = Column(Integer, default=0)

    # Override (if human overrode a block)
    was_overridden = Column(Boolean, default=False)
    override_by = Column(String, nullable=True)
    override_justification = Column(Text, nullable=True)
    override_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class FairnessConfig(Base):
    """Tenant-level fairness configuration.
    
    Controls which protected attributes are assessed, threshold values,
    and override policies per department.
    """
    __tablename__ = 'fairness_config'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department = Column(String(64), nullable=True)  # null = org-wide default

    # Threshold configuration
    fairness_threshold = Column(Float, default=0.85)
    
    # Protected attributes to assess
    protected_attributes = Column(JSON, default=lambda: [
        "gender", "ethnicity", "age", "disability", "nationality"
    ])

    # Override policy
    allow_override = Column(Boolean, default=True)
    override_requires_justification = Column(Boolean, default=True)
    override_requires_role = Column(String(32), default="department_head")

    # Which entity types trigger fairness checks
    monitored_entity_types = Column(JSON, default=lambda: [
        "Employee", "Compensation", "Schedule", "Performance",
        "Hiring", "Promotion", "Termination"
    ])

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
