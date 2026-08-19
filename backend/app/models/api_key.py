"""KAEOS — platform API keys (DB-backed, revocation-propagating).

The old store was a module-global JSON dict loaded once at import, so a key
generated or revoked in one gunicorn worker / replica was invisible to the others
until a restart — runtime revocation did not actually take effect fleet-wide.
This table is the shared source of truth: every request resolves and revokes
against the database, so revocation is immediate everywhere.

Only the SHA-256 hash of the key is stored (never the raw ``kt_...`` value).
Tenant-scoped with RLS on Postgres; the pre-auth lookup (which must resolve the
tenant FROM the key, before any tenant context exists) uses the owner session —
the same necessary carve-out as email->tenant login.
"""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, JSON
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # SHA-256 of the raw key; unique so a lookup is a single indexed hit.
    hashed_key = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(128), nullable=False, default="")
    role = Column(String(16), nullable=False, default="operator")  # viewer|operator|admin

    active = Column(Boolean, nullable=False, default=True)
    rate_limit = Column(Integer, nullable=False, default=1000)      # requests/hour (advisory)

    # Optional per-key network scoping (empty = unrestricted).
    allowed_ips = Column(JSON, nullable=True)
    allowed_origins = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
