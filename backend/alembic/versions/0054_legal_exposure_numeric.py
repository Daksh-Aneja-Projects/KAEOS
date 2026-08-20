"""Legal estimated exposure: free Text -> exact Numeric(18,2), matching finance.

`leg_matters.estimated_exposure` is money — the amount a matter could cost the
company. Stored as Text it cannot be summed into a portfolio exposure, compared
against a reserve, or ordered by size: "$2.5M", "2500000" and "about 2.5m" are
three unrelated strings. Converted to NUMERIC(18,2) like every other money
column (finance, and HR as of 0053).

LOSSY BY DESIGN: legacy free-text values are salvaged only when they are a plain
decimal number once currency symbols, thousands commas and whitespace are
stripped. Anything else ("TBD", "~2.5M", "unknown") becomes NULL rather than
failing the migration — NULL is the honest answer for a figure nobody can read
as money. The shipped seed never populates this column, so on a KAEOS-seeded
database there is nothing to lose.

Postgres-scoped: SQLite builds these tables from the models via create_all, so it
already gets Numeric, and SQLite cannot ALTER COLUMN TYPE anyway.

Revision ID: 0054_legal_exposure_numeric
Revises: 0053_hr_money_numeric
"""
from alembic import op
import sqlalchemy as sa

revision = "0054_legal_exposure_numeric"
down_revision = "0053_hr_money_numeric"
branch_labels = None
depends_on = None

_TABLE = "leg_matters"
_COL = "estimated_exposure"

# Strip $ , and whitespace, keep it only if what remains is a plain decimal.
_CLEANED = r"regexp_replace(estimated_exposure, '[$,\s]', '', 'g')"
_UPGRADE_USING = (
    f"CASE WHEN {_CLEANED} ~ '^-?[0-9]+(\\.[0-9]+)?$' "
    f"THEN {_CLEANED}::numeric(18,2) ELSE NULL END"
)


def _alter(to_type: str, using: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite gets the model type via create_all; no ALTER COLUMN TYPE
    insp = sa.inspect(bind)
    if _TABLE not in set(insp.get_table_names()):
        return
    if _COL not in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN {_COL} TYPE {to_type} USING ({using})")


def upgrade() -> None:
    _alter("NUMERIC(18,2)", _UPGRADE_USING)


def downgrade() -> None:
    _alter("TEXT", f"{_COL}::text")
