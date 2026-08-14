"""KAEOS — per-tenant data-encryption keys (envelope encryption).

One row per tenant holds a random Fernet DATA key, itself Fernet-wrapped by the
process-wide master KEK (see live_connectors._fernet). At-rest secrets (MFA TOTP
secrets, SSO client secrets, connector credentials) are encrypted under the
tenant's own data key, so a single key leak no longer decrypts every tenant, and
deleting a tenant's row crypto-shreds that tenant's secrets.

Platform-global (NOT tenant-scoped / NOT under RLS): the key must be readable on
the owner/maintenance session BEFORE any tenant context exists (pre-auth MFA and
SSO decrypt happen there). Registered in app/core/rls.py GLOBAL_TABLES.
"""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func

from app.models.domain import Base


class TenantDataKey(Base):
    __tablename__ = "tenant_data_keys"

    tenant_id = Column(String, primary_key=True)
    wrapped_key = Column(Text, nullable=False)   # master-Fernet(base64 data key)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
