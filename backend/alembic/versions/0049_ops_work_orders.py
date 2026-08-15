"""Operations: facility work orders + AI-decision advisory columns.

Adds ops_work_orders (backs the newly-wired FacilityAgent + the
CHANGE_MANAGEMENT/INCIDENT_POSTMORTEM/BACKUP_RETENTION ITGC checkers), and one
nullable ai_* advisory Text column per existing operations agent entity
(Project, ResourceAllocation, VendorContract, PurchaseRequest, Inspection) so
each of the 5 operations agents has a real column to persist its gated-
pipeline decision onto instead of discarding it.

Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all — see backend/alembic/versions/0041_healthcare_tables.py for the
same pattern).

Revision ID: 0049_ops_work_orders
Revises: 0047_hc_compliance
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0049_ops_work_orders"
down_revision = "0048_loan_servicing"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "ops_work_orders" not in tables:
        op.create_table(
            "ops_work_orders",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("facility_name", sa.String(length=256), nullable=False),
            sa.Column("issue_title", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=32), server_default="MAINTENANCE"),
            sa.Column("severity", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=24), server_default="OPEN"),
            sa.Column("reported_by", sa.String(length=128), nullable=True),
            sa.Column("priority", sa.String(length=24), nullable=True),
            sa.Column("assigned_team", sa.String(length=128), nullable=True),
            sa.Column("scheduled_hours", sa.Float(), nullable=True),
            sa.Column("safety_flagged", sa.Boolean(), server_default=sa.false()),
            sa.Column("ai_notes", sa.Text(), nullable=True),
            sa.Column("is_production", sa.Boolean(), nullable=True),
            sa.Column("implementer", sa.String(length=128), nullable=True),
            sa.Column("approver", sa.String(length=128), nullable=True),
            sa.Column("change_ticket", sa.String(length=64), nullable=True),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("action_items", sa.Text(), nullable=True),
            sa.Column("backup_verified", sa.Boolean(), nullable=True),
            sa.Column("record_age_days", sa.Float(), nullable=True),
            sa.Column("retention_days", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        if pg:
            for stmt in rls_enable_statements("ops_work_orders"):
                op.execute(stmt)

    if "ops_projects" in tables and "ai_risk_note" not in _cols(insp, "ops_projects"):
        op.add_column("ops_projects", sa.Column("ai_risk_note", sa.Text(), nullable=True))

    if "ops_resource_allocations" in tables and "ai_rebalance_note" not in _cols(insp, "ops_resource_allocations"):
        op.add_column("ops_resource_allocations", sa.Column("ai_rebalance_note", sa.Text(), nullable=True))

    if "ops_vendor_contracts" in tables and "ai_recommendation" not in _cols(insp, "ops_vendor_contracts"):
        op.add_column("ops_vendor_contracts", sa.Column("ai_recommendation", sa.Text(), nullable=True))

    if "ops_purchase_requests" in tables and "ai_audit_note" not in _cols(insp, "ops_purchase_requests"):
        op.add_column("ops_purchase_requests", sa.Column("ai_audit_note", sa.Text(), nullable=True))

    if "ops_inspections" in tables and "ai_summary" not in _cols(insp, "ops_inspections"):
        op.add_column("ops_inspections", sa.Column("ai_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for table, col in (
        ("ops_inspections", "ai_summary"),
        ("ops_purchase_requests", "ai_audit_note"),
        ("ops_vendor_contracts", "ai_recommendation"),
        ("ops_resource_allocations", "ai_rebalance_note"),
        ("ops_projects", "ai_risk_note"),
    ):
        if table in tables and col in _cols(insp, table):
            op.drop_column(table, col)

    if "ops_work_orders" in tables:
        op.drop_table("ops_work_orders")
