"""Engineering & IT Ops: service catalog, delivery, incidents, on-call, CI.

Backs the app/engineering package (SOC2/ISO27001/change-management governed).
Additive + inspector-guarded; RLS is Postgres-only (SQLite dev builds via
create_all). Mirrors 0041_healthcare_tables.py exactly: production schema is
Alembic-only (app/core/database.py refuses create_all outside dev), so these
8 tables previously did not exist on any real `alembic upgrade head` deploy
and every /api/v1/engineering/* endpoint 500'd.

Revision ID: 0045_engineering_tables
Revises: 0044_tenant_branding
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0045_engineering_tables"
down_revision = "0044_tenant_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = set(insp.get_table_names())

    if "eng_engineers" not in tables:
        op.create_table(
            "eng_engineers",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("hr_employee_id", sa.String(), nullable=True, index=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("email", sa.String(length=128), nullable=False),
            sa.Column("github_handle", sa.String(length=64), nullable=True),
            sa.Column("squad", sa.String(length=64), nullable=True),
            sa.Column("seniority", sa.String(length=32), nullable=True),
            sa.Column("on_call", sa.Boolean(), server_default=sa.false()),
            sa.Column("review_load", sa.Integer(), server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "eng_services" not in tables:
        op.create_table(
            "eng_services",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("repo_url", sa.String(length=256), nullable=True),
            sa.Column("tier", sa.String(length=16), server_default="TIER_2"),
            sa.Column("health", sa.String(length=16), server_default="HEALTHY"),
            sa.Column("owning_squad", sa.String(length=64), nullable=True),
            sa.Column("owner_engineer_id", sa.String(), nullable=True, index=True),
            sa.Column("slo_availability_target", sa.Float(), server_default=sa.text("99.9")),
            sa.Column("slo_availability_actual", sa.Float(), nullable=True),
            sa.Column("error_budget_remaining_pct", sa.Float(), nullable=True),
            sa.Column("deploys_last_30d", sa.Integer(), server_default=sa.text("0")),
            sa.Column("open_incidents", sa.Integer(), server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "eng_pull_requests" not in tables:
        op.create_table(
            "eng_pull_requests",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("service_id", sa.String(), sa.ForeignKey("eng_services.id"), nullable=True, index=True),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("author_id", sa.String(), sa.ForeignKey("eng_engineers.id"), nullable=True),
            sa.Column("branch", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=24), server_default="OPEN"),
            sa.Column("additions", sa.Integer(), server_default=sa.text("0")),
            sa.Column("deletions", sa.Integer(), server_default=sa.text("0")),
            sa.Column("files_changed", sa.Integer(), server_default=sa.text("0")),
            sa.Column("touches_migrations", sa.Boolean(), server_default=sa.false()),
            sa.Column("touches_auth", sa.Boolean(), server_default=sa.false()),
            sa.Column("test_coverage_delta", sa.Float(), nullable=True),
            sa.Column("ci_passing", sa.Boolean(), server_default=sa.true()),
            sa.Column("approvals", sa.Integer(), server_default=sa.text("0")),
            sa.Column("ai_risk_level", sa.String(length=16), nullable=True),
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("ai_findings", sa.JSON(), nullable=True),
            sa.Column("ai_reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "eng_deployments" not in tables:
        op.create_table(
            "eng_deployments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("service_id", sa.String(), sa.ForeignKey("eng_services.id"), nullable=True, index=True),
            sa.Column("pull_request_id", sa.String(), sa.ForeignKey("eng_pull_requests.id"), nullable=True),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("environment", sa.String(length=32), server_default="production"),
            sa.Column("status", sa.String(length=24), server_default="PENDING_APPROVAL"),
            sa.Column("deployed_by", sa.String(length=128), nullable=True),
            sa.Column("change_count", sa.Integer(), server_default=sa.text("1")),
            sa.Column("is_rollback", sa.Boolean(), server_default=sa.false()),
            sa.Column("ai_risk_level", sa.String(length=16), nullable=True),
            sa.Column("ai_risk_score", sa.Float(), nullable=True),
            sa.Column("ai_rationale", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
        )

    if "eng_incidents" not in tables:
        op.create_table(
            "eng_incidents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("service_id", sa.String(), sa.ForeignKey("eng_services.id"), nullable=True, index=True),
            sa.Column("incident_number", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("severity", sa.String(length=8), server_default="SEV3"),
            sa.Column("status", sa.String(length=24), server_default="DETECTED"),
            sa.Column("commander_id", sa.String(), sa.ForeignKey("eng_engineers.id"), nullable=True),
            sa.Column("detected_by", sa.String(length=64), nullable=True),
            sa.Column("customer_impacting", sa.Boolean(), server_default=sa.false()),
            sa.Column("affected_users", sa.Integer(), nullable=True),
            sa.Column("suspected_deployment_id", sa.String(), sa.ForeignKey("eng_deployments.id"), nullable=True),
            sa.Column("ai_severity_assessment", sa.String(length=16), nullable=True),
            sa.Column("ai_probable_cause", sa.Text(), nullable=True),
            sa.Column("ai_recommended_action", sa.Text(), nullable=True),
            sa.Column("ai_triaged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("time_to_acknowledge_mins", sa.Integer(), nullable=True),
            sa.Column("time_to_resolve_mins", sa.Integer(), nullable=True),
        )

    if "eng_postmortems" not in tables:
        op.create_table(
            "eng_postmortems",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("incident_id", sa.String(), sa.ForeignKey("eng_incidents.id"), nullable=False, index=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("contributing_factors", sa.JSON(), nullable=True),
            sa.Column("action_items", sa.JSON(), nullable=True),
            sa.Column("published", sa.Boolean(), server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "eng_oncall_rotations" not in tables:
        op.create_table(
            "eng_oncall_rotations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("engineer_id", sa.String(), sa.ForeignKey("eng_engineers.id"), nullable=False, index=True),
            sa.Column("squad", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=16), server_default="PRIMARY"),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "eng_pipeline_runs" not in tables:
        op.create_table(
            "eng_pipeline_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("service_id", sa.String(), sa.ForeignKey("eng_services.id"), nullable=True, index=True),
            sa.Column("pull_request_id", sa.String(), sa.ForeignKey("eng_pull_requests.id"), nullable=True, index=True),
            sa.Column("pipeline_name", sa.String(length=64), nullable=False),
            sa.Column("run_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="PENDING"),
            sa.Column("trigger", sa.String(length=16), nullable=True),
            sa.Column("branch", sa.String(length=128), nullable=True),
            sa.Column("commit_sha", sa.String(length=40), nullable=True),
            sa.Column("tests_passed", sa.Integer(), nullable=True),
            sa.Column("tests_failed", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if pg:
        for t in ("eng_engineers", "eng_services", "eng_pull_requests", "eng_deployments",
                  "eng_incidents", "eng_postmortems", "eng_oncall_rotations", "eng_pipeline_runs"):
            for stmt in rls_enable_statements(t):
                op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for t in ("eng_pipeline_runs", "eng_oncall_rotations", "eng_postmortems", "eng_incidents",
              "eng_deployments", "eng_pull_requests", "eng_services", "eng_engineers"):
        if t in tables:
            op.drop_table(t)
