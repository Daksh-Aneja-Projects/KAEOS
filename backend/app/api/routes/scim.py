"""KAEOS — SCIM 2.0 user provisioning (RFC 7644 core, Users resource).

Lets an IdP (Okta, Azure AD, OneLogin) create / update / deactivate KAEOS users
automatically. The IdP authenticates with a KAEOS admin API key as its SCIM
bearer token, so these routes go through the normal tenant middleware and are
gated to ADMIN; the tenant is derived from the key. SCIM-provisioned accounts
have an unusable local password (they authenticate via SSO), matching the OIDC
JIT-provisioning path.

Scope: the Users resource with the operations Okta/Azure use for lifecycle —
create, get, list (userName filter), replace (PUT), patch active, and deactivate
(DELETE). Groups/entitlements are intentionally out of scope for this iteration.
"""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import require_role
from app.core.entitlements import require_entitlement
from app.models.auth import User, UserRole

logger = logging.getLogger(__name__)

# SCIM provisioning is a managed/enterprise feature: gate the whole surface on
# the plan entitlement (no-op for self-host). Every endpoint already resolves a
# tenant via require_role, so the entitlement check has tenant context.
router = APIRouter(
    prefix="/scim/v2", tags=["SCIM 2.0 Provisioning"],
    dependencies=[Depends(require_entitlement("scim"))],
)

_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_SCIM_MEDIA = "application/scim+json"


def _scim_user(u: User) -> dict:
    return {
        "schemas": [_USER_SCHEMA],
        "id": u.id,
        "userName": u.email,
        "name": {"formatted": u.display_name},
        "displayName": u.display_name,
        "emails": [{"value": u.email, "primary": True}],
        "active": bool(u.is_active),
        "meta": {"resourceType": "User"},
    }


def _scim_error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status,
                        detail={"schemas": [_ERROR_SCHEMA], "status": str(status), "detail": detail})


def _email_of(body: dict) -> Optional[str]:
    un = (body.get("userName") or "").strip().lower()
    if un:
        return un
    for e in body.get("emails") or []:
        if isinstance(e, dict) and e.get("value"):
            return str(e["value"]).strip().lower()
    return None


def _display_of(body: dict, fallback: str) -> str:
    if body.get("displayName"):
        return str(body["displayName"])
    name = body.get("name") or {}
    if name.get("formatted"):
        return str(name["formatted"])
    given, family = name.get("givenName", ""), name.get("familyName", "")
    return (f"{given} {family}".strip()) or fallback


@router.post("/Users", status_code=201)
async def scim_create_user(body: dict, response: Response,
                           tenant: dict = Depends(require_role("admin")),
                           db: AsyncSession = Depends(get_db)):
    email = _email_of(body)
    if not email:
        raise _scim_error(400, "userName (or an email) is required")
    tenant_id = tenant["tenant_id"]

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise _scim_error(409, "User already exists")

    from app.services.auth import _hash_password
    user = User(
        email=email, display_name=_display_of(body, email),
        hashed_password=await _hash_password(secrets.token_urlsafe(32)),  # SSO-only, unusable local pw
        role=UserRole.VIEWER, tenant_id=tenant_id,
        is_active=bool(body.get("active", True)),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("[SCIM] provisioned %s for tenant=%s", email, tenant_id)
    response.media_type = _SCIM_MEDIA
    return _scim_user(user)


@router.get("/Users")
async def scim_list_users(request: Request,
                          tenant: dict = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    q = select(User).where(User.tenant_id == tenant_id)

    # Minimal SCIM filter support: `userName eq "x"` (what Okta/Azure send to
    # de-dupe before create).
    flt = request.query_params.get("filter")
    if flt and "eq" in flt:
        try:
            value = flt.split("eq", 1)[1].strip().strip('"').lower()
            q = q.where(func.lower(User.email) == value)
        except Exception:
            # An unparseable SCIM filter degrades to "no filter", which returns
            # this tenant's users (the query is already tenant-scoped above).
            # SCIM clients treat an over-broad list as valid; erroring would
            # break Okta/Azure provisioning on a malformed filter string.
            pass

    users = (await db.execute(q.limit(200))).scalars().all()
    return {
        "schemas": [_LIST_SCHEMA],
        "totalResults": len(users),
        "startIndex": 1,
        "itemsPerPage": len(users),
        "Resources": [_scim_user(u) for u in users],
    }


async def _get_scoped(db, user_id: str, tenant_id: str) -> User:
    u = (await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
    if u is None:
        raise _scim_error(404, "User not found")
    return u


@router.get("/Users/{user_id}")
async def scim_get_user(user_id: str,
                        tenant: dict = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    return _scim_user(await _get_scoped(db, user_id, tenant["tenant_id"]))


@router.put("/Users/{user_id}")
async def scim_replace_user(user_id: str, body: dict,
                            tenant: dict = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    u = await _get_scoped(db, user_id, tenant["tenant_id"])
    u.display_name = _display_of(body, u.display_name)
    if "active" in body:
        u.is_active = bool(body["active"])
    await db.commit()
    await db.refresh(u)
    return _scim_user(u)


@router.patch("/Users/{user_id}")
async def scim_patch_user(user_id: str, body: dict,
                          tenant: dict = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    """PatchOp — the common Okta/Azure deactivate is replace active=false."""
    u = await _get_scoped(db, user_id, tenant["tenant_id"])
    for op in body.get("Operations", []):
        if not isinstance(op, dict):
            continue
        action = (op.get("op") or "").lower()
        path = (op.get("path") or "").lower()
        value = op.get("value")
        if action in ("replace", "add"):
            if path == "active":
                u.is_active = _as_bool(value)
            elif path == "displayname":
                u.display_name = str(value)
            elif not path and isinstance(value, dict) and "active" in value:
                u.is_active = _as_bool(value["active"])
    await db.commit()
    await db.refresh(u)
    return _scim_user(u)


@router.delete("/Users/{user_id}", status_code=204)
async def scim_delete_user(user_id: str,
                           tenant: dict = Depends(require_role("admin")),
                           db: AsyncSession = Depends(get_db)):
    """SCIM delete = deactivate (soft), so the audit trail and history survive."""
    u = await _get_scoped(db, user_id, tenant["tenant_id"])
    u.is_active = False
    await db.commit()
    return Response(status_code=204)


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")
