"""HR transactional money: Float -> exact Numeric(18,2), matching finance.

Payroll totals, payslip pay, compensation base and benefit-plan costs are money a
paycheck must be exact to the cent; binary Float drifts. Converted to
NUMERIC(18,2) like the finance tables. Postgres-scoped: SQLite builds these tables
from the models via create_all, so it already gets Numeric and there is nothing to
alter (SQLite also cannot ALTER COLUMN TYPE). No SET DEFAULT — these carry a
Python-side default only, like the finance money columns, so adding a server
default would drift from the model.

Revision ID: 0053_hr_money_numeric
Revises: 0052_hot_path_indexes
"""
from alembic import op
import sqlalchemy as sa

revision = "0053_hr_money_numeric"
down_revision = "0052_hot_path_indexes"
branch_labels = None
depends_on = None

# table -> money columns converted
_COLS = {
    "hr_payroll_runs": ["total_gross", "total_net", "total_taxes", "total_deductions"],
    "hr_payslips": ["gross_pay", "net_pay"],
    "hr_compensation": ["base_amount"],
    "hr_benefit_plans": ["employee_cost_individual", "employee_cost_family", "employer_contribution"],
}


def _alter(to_type: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite gets the model type via create_all; no ALTER COLUMN TYPE
    tables = set(sa.inspect(bind).get_table_names())
    for tbl, columns in _COLS.items():
        if tbl not in tables:
            continue
        existing = {c["name"] for c in sa.inspect(bind).get_columns(tbl)}
        for c in columns:
            if c in existing:
                op.execute(f"ALTER TABLE {tbl} ALTER COLUMN {c} TYPE {to_type}")


def upgrade() -> None:
    _alter("NUMERIC(18,2)")


def downgrade() -> None:
    _alter("DOUBLE PRECISION")
