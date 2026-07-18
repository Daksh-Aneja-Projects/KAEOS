"""Tenant-scope the platform configs; encrypt MCP keys

Revision ID: d9e3f7a4c521
Revises: c8d2e5f6b312
Create Date: 2026-07-17

Three config tables keyed their natural identifier GLOBALLY unique
(config_mcp_tools.tool_id, config_ontology.department, config_federated.department)
while also carrying a tenant_id. The consequences were not theoretical:

  * Only ONE tenant could ever hold a row for a given tool/department - the
    second tenant's insert hit a unique violation.
  * Upserts looked the row up by that natural key ALONE, so a tenant writing
    its own config silently overwrote whichever tenant's row existed first.
    For config_federated that meant flipping another tenant's PRIVACY CONSENT
    for data sharing.
  * config_mcp_tools.api_key was stored in PLAINTEXT and served from a GET with
    no tenant scope at all, so every tenant could read every other tenant's
    tool credentials.

The identical bug was already found and fixed for model keys (see the
TenantLLMConfig docstring in app/models/settings.py); this migration applies
that same shape to its three siblings.

The plaintext api_key column is DROPPED, not migrated into the encrypted one:
every value in it was readable by every tenant, so those keys must be treated
as compromised and re-entered, never carried forward. Ontology and federated
rows are preserved - they are configuration, not credentials.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd9e3f7a4c521'
down_revision: Union[str, Sequence[str], None] = 'c8d2e5f6b312'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _mcp_old() -> sa.Table:
    """The pre-migration table, minus the column-level UNIQUE on tool_id.

    SQLite cannot ALTER a constraint away; batch mode rebuilds the table from
    this definition instead. Omitting `unique=True` here is how the old
    constraint gets dropped in the rebuild.
    """
    return sa.Table(
        'config_mcp_tools', sa.MetaData(),
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=False, index=True),
        sa.Column('tool_id', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('rate_limit_per_hour', sa.Integer(), default=1000),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )


def _dept_old(table: str, extra: sa.Column) -> sa.Table:
    return sa.Table(
        table, sa.MetaData(),
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=False, index=True),
        sa.Column('department', sa.String(), nullable=False),
        extra,
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name == "postgresql":
        # Postgres names a column-level UNIQUE "<table>_<column>_key".
        op.execute('ALTER TABLE config_mcp_tools DROP CONSTRAINT IF EXISTS config_mcp_tools_tool_id_key')
        op.execute('ALTER TABLE config_ontology DROP CONSTRAINT IF EXISTS config_ontology_department_key')
        op.execute('ALTER TABLE config_federated DROP CONSTRAINT IF EXISTS config_federated_department_key')

        op.add_column('config_mcp_tools', sa.Column('api_key_encrypted', sa.String(), nullable=True))
        op.drop_column('config_mcp_tools', 'api_key')

        # Duplicate (tenant, key) rows cannot exist: the OLD global constraint
        # made the natural key unique table-wide, which is strictly stronger.
        op.create_unique_constraint('uq_mcp_tenant_tool', 'config_mcp_tools', ['tenant_id', 'tool_id'])
        op.create_unique_constraint('uq_ontology_tenant_dept', 'config_ontology', ['tenant_id', 'department'])
        op.create_unique_constraint('uq_federated_tenant_dept', 'config_federated', ['tenant_id', 'department'])
    else:
        # SQLite cannot ALTER constraints at all - every change here has to
        # happen inside the table rebuild that batch mode performs.
        with op.batch_alter_table('config_mcp_tools', recreate='always',
                                  copy_from=_mcp_old()) as batch:
            batch.add_column(sa.Column('api_key_encrypted', sa.String(), nullable=True))
            batch.drop_column('api_key')
            batch.create_unique_constraint('uq_mcp_tenant_tool', ['tenant_id', 'tool_id'])

        for table, extra, name in (
            ('config_ontology', sa.Column('default_half_life_days', sa.Integer(), default=90),
             'uq_ontology_tenant_dept'),
            ('config_federated', sa.Column('opt_in', sa.Boolean(), default=False),
             'uq_federated_tenant_dept'),
        ):
            with op.batch_alter_table(table, recreate='always',
                                      copy_from=_dept_old(table, extra)) as batch:
                batch.create_unique_constraint(name, ['tenant_id', 'department'])


def downgrade() -> None:
    # Deliberately one-way for the credential column: restoring a plaintext
    # api_key column would recreate the vulnerability, and the values are gone.
    op.drop_constraint('uq_mcp_tenant_tool', 'config_mcp_tools', type_='unique')
    op.drop_constraint('uq_ontology_tenant_dept', 'config_ontology', type_='unique')
    op.drop_constraint('uq_federated_tenant_dept', 'config_federated', type_='unique')
