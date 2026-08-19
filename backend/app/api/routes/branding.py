"""White-label tenant theming.

GET  /branding  — any authed tenant user; returns the tenant's brand or KAEOS
                  defaults so the SPA always has a full theme to apply.
PUT  /branding  — admin only; fail-closed validation on hex colors and logo URL.
"""
import re
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role, approver_identity
from app.core.audit import record_security_event
from app.models.branding import TenantBranding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/branding", tags=["Branding"])

# Sane KAEOS defaults returned when a tenant has never set a brand. Kept here (not
# only as column defaults) so an unset tenant gets a full themed response without
# a row existing.
DEFAULTS = {
    "product_name": "KAEOS",
    "primary_color": "#6366f1",
    "accent_color": "#22d3ee",
    "logo_url": None,
    "login_subtitle": None,
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid_hex(v: str) -> bool:
    return bool(_HEX.match(v or ""))


def _valid_logo_url(v: str) -> bool:
    """http(s) absolute URL with a host. Rejects data:/javascript:/relative, so a
    logo_url can never smuggle a script or inline payload into the login shell."""
    try:
        p = urlparse(v)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


class BrandingOut(BaseModel):
    product_name: str
    primary_color: str
    accent_color: str
    logo_url: str | None = None
    login_subtitle: str | None = None
    is_default: bool = True


class BrandingIn(BaseModel):
    product_name: str = "KAEOS"
    primary_color: str = DEFAULTS["primary_color"]
    accent_color: str = DEFAULTS["accent_color"]
    logo_url: str | None = None
    login_subtitle: str | None = None


def _to_out(row: TenantBranding) -> BrandingOut:
    return BrandingOut(
        product_name=row.product_name,
        primary_color=row.primary_color,
        accent_color=row.accent_color,
        logo_url=row.logo_url,
        login_subtitle=row.login_subtitle,
        is_default=False,
    )


@router.get("", response_model=BrandingOut)
async def get_branding(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """This tenant's brand, or KAEOS defaults when unset. Available to any authed
    tenant user so the app can theme itself."""
    row = (await db.execute(
        select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if row is None:
        return BrandingOut(**DEFAULTS, is_default=True)
    return _to_out(row)


@router.put("", response_model=BrandingOut)
async def put_branding(
    item: BrandingIn,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert this tenant's brand (admin only). Colors must be #RRGGBB; a logo URL,
    if given, must be an http(s) URL — data:/javascript:/relative are rejected."""
    tenant_id = tenant["tenant_id"]

    name = (item.product_name or "").strip()
    if not name:
        raise HTTPException(400, detail="product_name must not be empty")
    if not _valid_hex(item.primary_color):
        raise HTTPException(400, detail="primary_color must be a #RRGGBB hex string")
    if not _valid_hex(item.accent_color):
        raise HTTPException(400, detail="accent_color must be a #RRGGBB hex string")
    logo = (item.logo_url or "").strip() or None
    if logo is not None and not _valid_logo_url(logo):
        raise HTTPException(400, detail="logo_url must be an http(s) URL")
    subtitle = (item.login_subtitle or "").strip() or None

    row = (await db.execute(
        select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if row is None:
        row = TenantBranding(tenant_id=tenant_id)
        db.add(row)

    row.product_name = name
    row.primary_color = item.primary_color.lower()
    row.accent_color = item.accent_color.lower()
    row.logo_url = logo
    row.login_subtitle = subtitle
    row.updated_by = approver_identity(tenant)

    await db.commit()
    await db.refresh(row)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="branding", resource_id=tenant_id,
    )
    return _to_out(row)
