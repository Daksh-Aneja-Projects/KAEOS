"""KAEOS — SSO / OIDC connection registry (enterprise single sign-on).

One row per tenant per protocol configures how that tenant's users authenticate
against an external Identity Provider (Azure AD, Okta, Google, Auth0, ...). The
client secret is stored Fernet-encrypted at rest (never in plaintext, never
returned by the API). Tenant-scoped: placed under RLS on Postgres like every
other tenant table.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text, Index, text
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class SSOConnection(Base):
    """An IdP connection for one tenant."""
    __tablename__ = "sso_connections"
    # At most one VERIFIED owner per email domain (partial unique), so a second
    # tenant cannot verify a domain another tenant already proved it controls.
    # Unverified duplicate claims are allowed - that is what the DNS-TXT
    # challenge arbitrates. Declared on BOTH dialects (SQLite supports partial
    # indexes) so the drift gate matches migration 0036 and the test schema
    # keeps the same semantics. NOTE: alembic's autogenerate does not diff the
    # partial WHERE predicate, so keep it matching 0036 by hand.
    __table_args__ = (
        Index("uq_sso_verified_domain", "email_domain", unique=True,
              postgresql_where=text("domain_verified"),
              sqlite_where=text("domain_verified")),
    )

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

    # SAML 2.0 only. `issuer` above doubles as the IdP EntityID; these two carry
    # the rest of the IdP half of the trust: where to send the AuthnRequest, and
    # the certificate whose public key must have signed the assertion. The cert
    # is public by definition, so it is stored in the clear (unlike the OIDC
    # client secret above).
    idp_sso_url = Column(String(512), nullable=True)
    idp_x509_cert = Column(Text, nullable=True)

    # Domain-based routing: a user whose email domain matches is sent here - but
    # ONLY once the tenant has proven it controls the domain (a DNS TXT challenge),
    # so one tenant cannot claim another's domain to hijack its SSO discovery.
    email_domain = Column(String(256), nullable=True, index=True)
    domain_verified = Column(Boolean, nullable=False, default=False)
    domain_verification_token = Column(String(64), nullable=True)
    # Role granted to a just-in-time provisioned user on first SSO login.
    default_role = Column(String(16), nullable=False, default="VIEWER")

    is_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
