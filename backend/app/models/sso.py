"""KAEOS — SSO / OIDC connection registry (enterprise single sign-on).

One row per tenant per protocol configures how that tenant's users authenticate
against an external Identity Provider (Azure AD, Okta, Google, Auth0, ...). The
client secret is stored Fernet-encrypted at rest (never in plaintext, never
returned by the API). Tenant-scoped: placed under RLS on Postgres like every
other tenant table.
"""
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class SSOConnection(Base):
    """An IdP connection for one tenant."""
    __tablename__ = "sso_connections"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    protocol = Column(String(16), nullable=False, default="OIDC")   # OIDC | SAML
    provider_label = Column(String(128), nullable=False, default="")  # "Azure AD", "Okta"

    # OIDC issuer URL — its /.well-known/openid-configuration is fetched for the
    # authorization/token/JWKS endpoints. e.g. https://login.microsoftonline.com/<tid>/v2.0
    issuer = Column(String(512), nullable=False, default="")
    client_id = Column(String(256), nullable=False, default="")
    # Fernet-encrypted client secret (write-only; never serialized back out).
    client_secret_encrypted = Column(String, nullable=True)

    # Domain-based routing: a user whose email domain matches is sent here.
    email_domain = Column(String(256), nullable=True, index=True)
    # Role granted to a just-in-time provisioned user on first SSO login.
    default_role = Column(String(16), nullable=False, default="VIEWER")

    is_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
