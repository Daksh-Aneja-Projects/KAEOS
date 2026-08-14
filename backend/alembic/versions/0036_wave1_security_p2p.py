"""Wave 1 schema: security (TOTP replay counter, per-tenant data keys, SSO
domain verification) + P2P deterministic 3-way match (unified vendor identity,
PO line items, invoice->PO->receipt FK chain).

All additive + inspector-guarded (SQLite dev uses create_all; this runs on
Postgres prod). RLS + backfills are Postgres-only.

Revision ID: 0036_wave1_security_p2p
Revises: 0035_fiscal_period_lock
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

from app.core.rls import rls_enable_statements

revision = "0036_wave1_security_p2p"
down_revision = "0035_fiscal_period_lock"
branch_labels = None
depends_on = None


def _tables(insp):
    return set(insp.get_table_names())


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    pg = bind.dialect.name == "postgresql"
    tables = _tables(insp)

    # ── Security: TOTP replay counter ─────────────────────────────────────────
    if "user_mfa" in tables and "last_used_step" not in _cols(insp, "user_mfa"):
        op.add_column("user_mfa", sa.Column("last_used_step", sa.BigInteger(), nullable=True))

    # ── Security: per-tenant data-encryption keys (global table, NOT under RLS) ─
    if "tenant_data_keys" not in tables:
        op.create_table(
            "tenant_data_keys",
            sa.Column("tenant_id", sa.String(), primary_key=True),
            sa.Column("wrapped_key", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── Security: SSO domain-ownership verification ───────────────────────────
    if "sso_connections" in tables:
        sso_cols = _cols(insp, "sso_connections")
        if "domain_verified" not in sso_cols:
            op.add_column("sso_connections", sa.Column(
                "domain_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "domain_verification_token" not in sso_cols:
            op.add_column("sso_connections", sa.Column(
                "domain_verification_token", sa.String(64), nullable=True))
        if pg:
            # At most ONE verified connection per domain (unverified claims may
            # collide harmlessly; only a verified domain routes logins).
            op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_sso_verified_domain "
                       "ON sso_connections (email_domain) WHERE domain_verified")

    # ── P2P: unify ops vendor identity onto the single fin_vendors master ──────
    if "ops_purchase_orders" in tables and "vendor_id" not in _cols(insp, "ops_purchase_orders"):
        op.add_column("ops_purchase_orders",
                      sa.Column("vendor_id", sa.String(), sa.ForeignKey("fin_vendors.id"), nullable=True))
        op.create_index("ix_ops_purchase_orders_vendor_id", "ops_purchase_orders", ["vendor_id"])
    if "ops_vendor_contracts" in tables and "vendor_id" not in _cols(insp, "ops_vendor_contracts"):
        op.add_column("ops_vendor_contracts",
                      sa.Column("vendor_id", sa.String(), sa.ForeignKey("fin_vendors.id"), nullable=True))
        op.create_index("ix_ops_vendor_contracts_vendor_id", "ops_vendor_contracts", ["vendor_id"])

    # ── P2P: PO line items (the missing qty/price leg of the match) ────────────
    if "ops_po_line_items" not in tables:
        op.create_table(
            "ops_po_line_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("purchase_order_id", sa.String(),
                      sa.ForeignKey("ops_purchase_orders.id"), nullable=False),
            sa.Column("line_number", sa.Integer(), server_default="1"),
            sa.Column("description", sa.String(256)),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ops_po_line_items_purchase_order_id",
                        "ops_po_line_items", ["purchase_order_id"])
        if pg:
            for stmt in rls_enable_statements("ops_po_line_items"):
                op.execute(stmt)

    # ── P2P: close the FK chain invoice -> PO -> receipt line ─────────────────
    if "fin_invoices" in tables and "purchase_order_id" not in _cols(insp, "fin_invoices"):
        op.add_column("fin_invoices",
                      sa.Column("purchase_order_id", sa.String(),
                                sa.ForeignKey("ops_purchase_orders.id"), nullable=True))
        op.create_index("ix_fin_invoices_purchase_order_id", "fin_invoices", ["purchase_order_id"])
    if "ops_goods_receipts" in tables and "po_line_item_id" not in _cols(insp, "ops_goods_receipts"):
        op.add_column("ops_goods_receipts",
                      sa.Column("po_line_item_id", sa.String(),
                                sa.ForeignKey("ops_po_line_items.id"), nullable=True))

    # ── P2P backfills (Postgres; per-tenant, unmatched rows stay NULL) ────────
    if pg:
        op.execute("""UPDATE ops_purchase_orders po SET vendor_id = v.id FROM fin_vendors v
                      WHERE po.vendor_id IS NULL AND v.tenant_id = po.tenant_id
                        AND lower(btrim(v.name)) = lower(btrim(po.vendor_name))""")
        op.execute("""UPDATE fin_invoices i SET purchase_order_id = po.id FROM ops_purchase_orders po
                      WHERE i.purchase_order_id IS NULL AND i.po_number IS NOT NULL
                        AND po.tenant_id = i.tenant_id AND po.po_number = i.po_number""")


def downgrade() -> None:
    # Additive migration; leaving the columns/tables in place is safe.
    pass
