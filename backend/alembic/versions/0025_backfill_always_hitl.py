"""Backfill skills.always_hitl on existing rows.

0024 added the column with a False default but did not backfill, so on any
database that predates it the explicit flag protected nothing and every
high-consequence skill still depended on tag/name inference alone. That is the
exact fragility the flag exists to remove: rename `vendor_payment_approval` to
`treasury_settle` on such a database and it silently becomes autonomous.

This sets the flag on every existing skill that the shared consequence helper
would classify as high-consequence, so the explicit marker becomes authoritative
on old and new data alike. Escalate-only by construction: it never clears a flag
that is already set.

Revision ID: 0025_backfill_always_hitl
Revises: 0024_skill_always_hitl
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_backfill_always_hitl"
down_revision = "0024_skill_always_hitl"
branch_labels = None
depends_on = None


def _tags() -> list[str]:
    """The same vocabulary Gate 3 uses. Read from settings so this can never
    drift from the runtime check; falls back to the shipped default list if the
    app package is not importable in the migration environment."""
    try:
        from app.core.config import get_settings
        tags = list(get_settings().HIGH_CONSEQUENCE_TAGS or [])
        if tags:
            return tags
    except Exception:
        pass
    return [
        "payment", "payout", "wire_transfer", "termination", "offboarding",
        "contract_execution", "external_send", "data_deletion", "irreversible",
    ]


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("skills")]
    if "always_hitl" not in cols:
        return  # 0024 did not run; nothing to backfill

    # Match the helper's blob: compliance_tags + department + skill_id, lowercased.
    # COALESCE keeps NULL columns from voiding the whole concatenation.
    blob = (
        "lower(coalesce(cast(compliance_tags as text), '') || ' ' || "
        "coalesce(department, '') || ' ' || coalesce(skill_id, ''))"
    )
    clauses = " OR ".join(f"{blob} LIKE :t{i}" for i, _ in enumerate(_tags()))
    params = {f"t{i}": f"%{t.lower()}%" for i, t in enumerate(_tags())}

    # Escalate only: never unset an explicitly flagged skill.
    # Boolean literals (true/false), not 1/0: Postgres rejects `boolean = integer`
    # (SQLite tolerates it). Both dialects accept the true/false keywords.
    bind.execute(
        sa.text(
            f"UPDATE skills SET always_hitl = true "
            f"WHERE (always_hitl = false OR always_hitl IS NULL) AND ({clauses})"
        ),
        params,
    )


def downgrade() -> None:
    # Deliberately a no-op. We cannot distinguish a flag this migration set from
    # one an operator set deliberately, and clearing a high-consequence marker is
    # the one direction that is never safe to guess at.
    pass
