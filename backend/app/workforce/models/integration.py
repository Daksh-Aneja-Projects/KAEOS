"""
KAEOS Workforce Layer — Integration Mapping Models

Maps connected enterprise systems (via existing Connector model) to
department capabilities and data categories. This is how the system
knows "Workday provides employee_records to the HR department's
Employee Records capability."
"""
from sqlalchemy import (
    Column, String, Float, DateTime, Text, JSON, Enum, ForeignKey,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class SyncDirection(str, enum.Enum):
    INBOUND = "INBOUND"             # Data flows from external system into KAEOS
    OUTBOUND = "OUTBOUND"           # Data flows from KAEOS to external system
    BIDIRECTIONAL = "BIDIRECTIONAL"  # Both directions


class IntegrationMapping(Base):
    """
    Maps an external connector to a department capability with specific
    data category and field-level mapping configuration.

    Example: BambooHR connector → HR Department → Employee Records capability
             → data_category: "employee_records"
             → field mapping: {"firstName": "first_name", "lastName": "last_name"}
    """
    __tablename__ = "integration_mappings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # References
    connector_id = Column(String, ForeignKey("connectors.id"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)
    capability_id = Column(String, ForeignKey("capabilities.id"), nullable=True, index=True)

    # What data flows through this mapping
    data_category = Column(String(64), nullable=False)       # "employee_records", "cases", "email"
    data_subcategory = Column(String(64), nullable=True)     # "org_chart", "compensation", "benefits"

    # Direction
    sync_direction = Column(Enum(SyncDirection), default=SyncDirection.INBOUND)

    # Field-level mapping
    field_mapping = Column(JSON, default=dict)
    # Schema: {"source_field": "target_field", "firstName": "first_name", ...}

    # Transform rules
    transform_rules = Column(JSON, default=list)
    # Schema: [{"field": "hire_date", "transform": "parse_date", "format": "YYYY-MM-DD"}]

    # PII handling
    pii_fields = Column(JSON, default=list)                  # Fields identified as PII
    pii_scrub_enabled = Column(String(8), default="true")

    # Sync configuration
    sync_frequency = Column(String(32), default="HOURLY")    # REALTIME, HOURLY, DAILY, WEEKLY, MANUAL
    sync_config = Column(JSON, default=dict)                 # Sync-specific settings

    # Status & metrics
    status = Column(String(16), default="ACTIVE")            # ACTIVE, PAUSED, ERROR, CONFIGURING
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    records_synced = Column(String(16), default="0")         # Total records synced
    last_error = Column(Text, nullable=True)
    error_count = Column(String(8), default="0")

    # AI confidence in this mapping
    ai_confidence = Column(Float, default=0.0)               # 0.0-1.0 — how confident the auto-mapper is
    confirmed_by = Column(String, nullable=True)             # Admin who confirmed the mapping
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IntegrationRequirement(Base):
    """
    Tracks what integrations a department needs and whether they're satisfied.

    When a domain pack is deployed, its required_integrations are expanded
    into IntegrationRequirement records. The deployment studio checks
    these to show which systems still need to be connected.
    """
    __tablename__ = "integration_requirements"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # What's needed
    category = Column(String(64), nullable=False)            # "hris", "ticketing", "email"
    is_required = Column(String(8), default="true")          # "true" or "false"
    examples = Column(JSON, default=list)                    # ["workday", "bamboohr", "ukg"]
    data_provided = Column(JSON, default=list)               # ["employee_records", "org_chart"]

    # What's connected (filled during deployment)
    satisfied_by_connector_id = Column(String, ForeignKey("connectors.id"), nullable=True)
    satisfied_by_name = Column(String(128), nullable=True)

    # Status
    is_satisfied = Column(String(8), default="false")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
