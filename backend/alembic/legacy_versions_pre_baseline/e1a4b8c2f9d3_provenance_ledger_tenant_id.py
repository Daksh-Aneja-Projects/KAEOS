"""Give the provenance ledger a tenant_id

Revision ID: e1a4b8c2f9d3
Revises: d9e3f7a4c521
Create Date: 2026-07-17

The immutable audit trail the platform sells had NO tenant_id column: its
subject was inferred from the polymorphic rule_id (which holds rule ids for
rule events and skill ids for agent executions). Consequence: /provenance
endpoints could not be tenant-scoped, and row-level security had no column to
filter on, so one tenant's audit reasoning was readable by another.

This adds the column, backfills existing rows from their rule's tenant where
that can be resolved (rule-event rows only; agent-execution rows keyed by skill
id are left NULL and are simply not returned to any tenant), and - on Postgres -
puts the table under the same tenant_isolation policy as every other tenant
table. New writes populate tenant_id directly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e1a4b8c2f9d3'
down_revision: Union[str, Sequence[str], None] = 'd9e3f7a4c521'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    inspector = sa.inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("provenance_ledger")]
    if "tenant_id" not in cols:
        op.add_column("provenance_ledger", sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index("ix_provenance_ledger_tenant_id", "provenance_ledger", ["tenant_id"])

    # Backfill rule-event rows from the owning rule. rule_id is polymorphic, so
    # this only resolves entries whose subject is actually a rule; skill-keyed
    # rows stay NULL (correct - they are not returned to any tenant).
    op.execute("""
        UPDATE provenance_ledger
        SET tenant_id = (
            SELECT r.tenant_id FROM rules r WHERE r.id = provenance_ledger.rule_id
        )
        WHERE tenant_id IS NULL
    """)

    if conn.dialect.name == "postgresql":
        op.execute('ALTER TABLE provenance_ledger ENABLE ROW LEVEL SECURITY')
        op.execute('DROP POLICY IF EXISTS tenant_isolation ON provenance_ledger')
        # NULL tenant_id (legacy skill-keyed rows) matches nothing, which is the
        # intended fail-closed behaviour - they belong to no tenant's view.
        op.execute("""
            CREATE POLICY tenant_isolation ON provenance_ledger
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute('DROP POLICY IF EXISTS tenant_isolation ON provenance_ledger')
        op.execute('ALTER TABLE provenance_ledger DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_provenance_ledger_tenant_id", table_name="provenance_ledger")
    op.drop_column("provenance_ledger", "tenant_id")
