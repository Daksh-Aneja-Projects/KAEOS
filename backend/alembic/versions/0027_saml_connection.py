"""SAML fields on sso_connections (idp_sso_url, idp_x509_cert).

Adds the IdP half of a SAML 2.0 trust to the existing SSO connection registry.
The certificate is public by definition, so both columns are plaintext (unlike
the OIDC client_secret, which stays Fernet-encrypted). Idempotent add-columns.

Revision ID: 0027_saml_connection
Revises: 0026_deletion_journal
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0027_saml_connection"
down_revision = "0026_deletion_journal"
branch_labels = None
depends_on = None

_TABLE = "sso_connections"


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "idp_sso_url" not in cols:
        op.add_column(_TABLE, sa.Column("idp_sso_url", sa.String(512), nullable=True))
    if "idp_x509_cert" not in cols:
        op.add_column(_TABLE, sa.Column("idp_x509_cert", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(_TABLE)]
    if "idp_x509_cert" in cols:
        op.drop_column(_TABLE, "idp_x509_cert")
    if "idp_sso_url" in cols:
        op.drop_column(_TABLE, "idp_sso_url")
