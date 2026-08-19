"""hot-path read indexes (composite tenant+time / tenant+flag, plus 8 hot FK columns)

Pure additive DDL. No column, constraint or data change - only indexes for query
shapes that already exist in the code:

  * ``provenance_ledger (tenant_id, timestamp)`` - hottest append-only table; 10
    call sites read it as "tenant_id = ? ORDER BY timestamp" or "timestamp >= ?".
    The existing indexes lead with tenant_id alone or (tenant_id, chain_scope),
    so neither could serve the sort/range.
  * ``security_audit_logs (tenant_id, timestamp)`` - audit feed (DESC LIMIT) and
    the checkpoint window scan in app/core/audit.py.
  * ``signals (tenant_id, created_at)`` - every signal feed; uq_signals_natural
    leads with source_type so it cannot serve these.
  * ``rules (tenant_id, is_archived)`` - ~37 call sites are exactly
    "tenant_id = ? AND is_archived = false".
  * eight FK columns in the hr_* cluster that are filtered with an equality in
    router/service code but carried no index. Single-column (matching the
    ``index=True`` siblings already on these tables) so the same index also
    covers Postgres' FK check when the parent row is deleted - purge_tenant runs
    248 DELETEs with zero ondelete= cascades, and an unindexed child FK column
    turns each of those checks into a sequential scan.

Inspector-guarded: DEV_MODE runs Base.metadata.create_all(), which pre-builds
every one of these from the model __table_args__ / index=True, so each branch
no-ops on that path.

Revision ID: 0052_hot_path_indexes
Revises: 0051_outbound_uniq_rule_drop

(revision id kept <=32 chars - alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0052_hot_path_indexes"
down_revision = "0051_outbound_uniq_rule_drop"
branch_labels = None
depends_on = None

# (index name, table, columns) - names mirror Base.metadata exactly, so the ORM
# and this migration never drift into two differently-named copies.
_INDEXES = [
    ("ix_prov_tenant_ts", "provenance_ledger", ["tenant_id", "timestamp"]),
    ("ix_seclog_tenant_ts", "security_audit_logs", ["tenant_id", "timestamp"]),
    ("ix_signals_tenant_created", "signals", ["tenant_id", "created_at"]),
    ("ix_rules_tenant_archived", "rules", ["tenant_id", "is_archived"]),
    ("ix_hr_boarding_tasks_plan_id", "hr_boarding_tasks", ["plan_id"]),
    ("ix_hr_payslips_run_id", "hr_payslips", ["run_id"]),
    ("ix_hr_payslips_employee_id", "hr_payslips", ["employee_id"]),
    ("ix_hr_candidates_requisition_id", "hr_candidates", ["requisition_id"]),
    ("ix_hr_interviews_candidate_id", "hr_interviews", ["candidate_id"]),
    ("ix_hr_benefit_enrollments_employee_id", "hr_benefit_enrollments", ["employee_id"]),
    ("ix_hr_learning_enrollments_employee_id", "hr_learning_enrollments", ["employee_id"]),
    ("ix_hr_timesheets_employee_id", "hr_timesheets", ["employee_id"]),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols in _INDEXES:
        if table not in tables:
            continue
        if name in {i["name"] for i in insp.get_indexes(table)}:
            continue
        op.create_index(name, table, cols)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, _cols in reversed(_INDEXES):
        if table not in tables:
            continue
        if name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
