"""SSO gateway audience — machine-to-machine OAuth2.1 token acceptance

Adds sso_connections.gateway_audience: the expected `aud` claim on an
ACCESS token an external agent presents directly (client-credentials
grant against the SAME IdP already configured for human SSO login),
distinct from client_id (the id_token audience for the browser flow).
Null = gateway token acceptance stays inactive for that connection.

Additive, inspector-guarded, idempotent. DEV_MODE's create_all pre-builds
it from the model, so this no-ops there.

Revision ID: 0058_sso_gateway_audience
Revises: 0057_brain_proposals

(revision id kept <=32 chars - alembic_version is VARCHAR(32).)
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_sso_gateway_audience"
down_revision = "0057_brain_proposals"
branch_labels = None
depends_on = None

_TABLE = "sso_connections"
_COL = "gateway_audience"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.add_column(_TABLE, sa.Column(_COL, sa.String(256), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COL)
