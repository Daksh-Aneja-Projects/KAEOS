"""Add missions + mission_steps + mission_events (Cross-Domain Missions) + RLS.

Goal-level orchestration: a mission decomposes into a governed DAG of steps with a
mission ledger. All three tables are tenant-scoped (RLS on Postgres). Idempotent.

Revision ID: 0010_missions
Revises: 0009_actuation
Create Date: 2026-07-24
"""
from alembic import op

from app.models.missions import Mission, MissionStep, MissionEvent
from app.core.rls import rls_enable_statements

revision = "0010_missions"
down_revision = "0009_actuation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Mission.__table__.create(bind=bind, checkfirst=True)
    MissionStep.__table__.create(bind=bind, checkfirst=True)
    MissionEvent.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for table in ("missions", "mission_steps", "mission_events"):
            for stmt in rls_enable_statements(table):
                bind.execute(text(stmt))


def downgrade() -> None:
    MissionEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)
    MissionStep.__table__.drop(bind=op.get_bind(), checkfirst=True)
    Mission.__table__.drop(bind=op.get_bind(), checkfirst=True)
