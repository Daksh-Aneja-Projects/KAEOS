"""KAEOS — White-label tenant branding.

One row per tenant. Absent = the app themes with KAEOS defaults (see the API's
DEFAULTS), so an unset tenant is a valid, fully-themed state, never an error.
Brand assets only: no secrets here, so GET is readable by any authed tenant user
(the SPA needs it to paint the shell); PUT is admin-only.

NOT seed-populated on purpose: this is a tenant's own opt-in choice (set via
PUT /branding), not derivable data. Seeding a fake brand for the demo tenant
would misrepresent an unconfigured tenant as one that had actively white-labeled
itself. An absent row is the honest, fully-functional default state (see above).
"""
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class TenantBranding(Base):
    __tablename__ = "brand_tenant_branding"

    id = Column(String, primary_key=True, default=_uuid)
    # Unique so the upsert can never create a second row for a tenant, even under
    # a race — the tenant is the identity here, one brand per tenant.
    tenant_id = Column(String, nullable=False, index=True, unique=True)
    product_name = Column(String(80), nullable=False, default="KAEOS")
    primary_color = Column(String(7), nullable=False, default="#6366f1")
    accent_color = Column(String(7), nullable=False, default="#22d3ee")
    logo_url = Column(String(512), nullable=True)
    login_subtitle = Column(String(200), nullable=True)
    updated_by = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
