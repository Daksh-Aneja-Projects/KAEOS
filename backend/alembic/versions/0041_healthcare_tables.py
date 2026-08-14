"""Healthcare department: encounters, PHI disclosures, consent, clinical tasks.

Backs the app/healthcare package (HIPAA/Part 2 governed). Additive +
inspector-guarded; RLS is Postgres-only (SQLite dev builds via create_all).

Revision ID: 0041_healthcare_tables
Revises: 0040_fin_fx_rates
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0041_healthcare_tables"
down_revision = "0040_fin_fx_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "hlth_encounters" not in tables:
        op.create_table(
            "hlth_encounters",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("encounter_number", sa.String(length=32), nullable=False),
            sa.Column("patient_ref", sa.String(length=64), nullable=False),
            sa.Column("encounter_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="OPEN"),
            sa.Column("reason", sa.String(length=256), nullable=True),
            sa.Column("diagnosis_codes", sa.JSON(), nullable=True),
            sa.Column("priority", sa.String(length=16), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "encounter_number", name="uq_hlth_encounter_tenant_number"),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_encounters"):
                op.execute(stmt)

    if "hlth_phi_disclosures" not in tables:
        op.create_table(
            "hlth_phi_disclosures",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("encounter_id", sa.String(), sa.ForeignKey("hlth_encounters.id"), nullable=True, index=True),
            sa.Column("purpose", sa.String(length=48), nullable=False),
            sa.Column("recipient", sa.String(length=128), nullable=False),
            sa.Column("fields", sa.JSON(), nullable=True),
            sa.Column("minimum_necessary_justification", sa.Text(), nullable=False),
            sa.Column("part2", sa.Boolean(), server_default=sa.false()),
            sa.Column("authorized", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("recorded_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_phi_disclosures"):
                op.execute(stmt)

    if "hlth_consent_records" not in tables:
        op.create_table(
            "hlth_consent_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("patient_ref", sa.String(length=64), nullable=False),
            sa.Column("scope", sa.String(length=64), nullable=False),
            sa.Column("part2", sa.Boolean(), server_default=sa.false()),
            sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_consent_records"):
                op.execute(stmt)

    if "hlth_clinical_tasks" not in tables:
        op.create_table(
            "hlth_clinical_tasks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("encounter_id", sa.String(), sa.ForeignKey("hlth_encounters.id"), nullable=True, index=True),
            sa.Column("task_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="OPEN"),
            sa.Column("assignee", sa.String(length=64), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        if pg:
            for stmt in rls_enable_statements("hlth_clinical_tasks"):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("hlth_clinical_tasks", "hlth_phi_disclosures", "hlth_consent_records", "hlth_encounters"):
        if t in tables:
            op.drop_table(t)
