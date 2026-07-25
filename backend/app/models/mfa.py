"""KAEOS — per-user MFA (TOTP second factor).

One row per user holding the Fernet-encrypted TOTP shared secret and whether MFA
is confirmed/enabled. Tenant-scoped (RLS on Postgres); the login-time verify runs
on the owner session because a second factor is checked before any tenant context
exists — the same pre-auth carve-out as the user/api-key lookups.
"""
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UserMFA(Base):
    __tablename__ = "user_mfa"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False, unique=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)

    secret_encrypted = Column(String, nullable=False)   # Fernet(base32 TOTP secret)
    enabled = Column(Boolean, nullable=False, default=False)  # True only after a code is confirmed

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
