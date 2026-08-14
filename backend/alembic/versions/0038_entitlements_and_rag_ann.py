"""Wave 3: entitlement/billing tables + RAG ANN (HNSW) indexes.

Billing tables matter only in managed-cloud mode; a self-host install never
needs them. The HNSW indexes turn the pgvector similarity scans from sequential
into approximate-nearest-neighbour. Additive + inspector-guarded; RLS and HNSW
are Postgres-only (the SQLite unit lane no-ops them).

Revision ID: 0038_entitlements_and_rag_ann
Revises: 0037_writeback_reliability
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0038_entitlements_and_rag_ann"
down_revision = "0037_writeback_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "billing_accounts" not in tables:
        op.create_table(
            "billing_accounts",
            sa.Column("tenant_id", sa.String(), primary_key=True),
            sa.Column("seats", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("stripe_customer_id", sa.String(), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(), nullable=True),
            sa.Column("stripe_meter_item_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "usage_meter_reports" not in tables:
        op.create_table(
            "usage_meter_reports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("metered_executions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("included_allowance", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("overage_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stripe_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("stripe_usage_record_id", sa.String(), nullable=True),
            sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "period_start", name="uq_usage_report_period"),
        )
        op.create_index("ix_usage_report_tenant_period", "usage_meter_reports",
                        ["tenant_id", "period_start"])
        op.create_index("ix_usage_meter_reports_tenant_id", "usage_meter_reports", ["tenant_id"])

    if "skill_value_baselines" not in tables:
        op.create_table(
            "skill_value_baselines",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("skill_id_name", sa.String(), nullable=False),
            sa.Column("baseline_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("loaded_hourly_rate_usd", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "skill_id_name", name="uq_skill_baseline"),
        )
        op.create_index("ix_skill_value_baselines_tenant_id", "skill_value_baselines", ["tenant_id"])

    # GLOBAL (no tenant_id): Stripe events are not tenant-scoped and the webhook
    # has no tenant session; event_id (evt_...) makes a redelivery a no-op.
    if "stripe_webhook_events" not in tables:
        op.create_table(
            "stripe_webhook_events",
            sa.Column("event_id", sa.String(), primary_key=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if pg:
        # Tenant isolation on the three tenant-scoped billing tables.
        for t in ("billing_accounts", "usage_meter_reports", "skill_value_baselines"):
            for stmt in rls_enable_statements(t):
                op.execute(stmt)
        # RAG ANN: HNSW cosine indexes so <=> similarity is not a sequential scan.
        # Guarded IF NOT EXISTS; skip tables that do not exist yet (polystore_vectors
        # is created at runtime by PgVectorStore.initialize).
        pg_tables = set(insp.get_table_names())
        for t in ("rule_embeddings", "skill_embeddings", "polystore_vectors"):
            if t in pg_tables:
                op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_hnsw ON {t} "
                           f"USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    # Additive; safe to leave in place.
    pass
