"""
KAEOS — Auth API Routes
Login, registration, user management with RBAC enforcement.
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.services.auth import AuthService, decode_token, revoke_token
from app.models.auth import UserRole

router = APIRouter(prefix="/auth", tags=["Authentication & RBAC"])


class LoginRequest(BaseModel):
    """Typed login body. Rejects wrong-typed fields with a 422 instead of the
    handler crashing on `.strip()` of a non-string (which used to 500)."""
    email: str
    password: str


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Extract and validate user from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await AuthService.get_user_by_id(db, payload["user_id"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_role(*roles: str):
    """Dependency that enforces role-based access."""
    async def checker(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {', '.join(roles)}, Current: {user['role']}"
            )
        return user
    return checker


@router.post("/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Authenticate with email/password, returns JWT token."""
    email = (data.email or "").strip().lower()
    password = data.password or ""

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    ip = request.client.host if request.client else None
    result = await AuthService.login(db, email, password, ip_address=ip)
    if not result:
        # Same message for bad credentials and lockout — don't reveal which.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return result


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """Revoke the caller's current token (adds its jti to the denylist)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    revoked = revoke_token(token)
    return {"revoked": revoked}

@router.post("/sso/saml")
async def saml_sso(data: dict):
    """Enterprise SAML/SSO authentication endpoint — not implemented in v1."""
    raise HTTPException(
        status_code=501,
        detail="SAML SSO is not implemented in v1. Please use email/password login or contact support."
    )
@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user profile."""
    return user


@router.post("/users")
async def create_user(
    data: dict,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """Create a new user (ADMIN only)."""
    role_map = {"ADMIN": UserRole.ADMIN, "ANALYST": UserRole.ANALYST, "VIEWER": UserRole.VIEWER}
    role = role_map.get(data.get("role", "VIEWER"), UserRole.VIEWER)

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Authenticated user has no tenant context")

    result = await AuthService.create_user(
        db,
        email=data.get("email", "").strip().lower(),
        display_name=data.get("display_name", ""),
        password=data.get("password", ""),
        role=role,
        created_by=user["id"],
        tenant_id=tenant_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/users")
async def list_users(
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """List all users (ADMIN only)."""
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Authenticated user has no tenant context")
    return await AuthService.list_users(db, tenant_id)


@router.put("/users/{user_id}/role")
async def update_role(
    user_id: str,
    data: dict,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """Update a user's role — ADMIN, and only within your own tenant."""
    role_map = {"ADMIN": UserRole.ADMIN, "ANALYST": UserRole.ANALYST, "VIEWER": UserRole.VIEWER}
    new_role = role_map.get(data.get("role"), None)
    if not new_role:
        raise HTTPException(status_code=400, detail="Invalid role")
    # Tenant comes from the caller's verified token, never from the request.
    result = await AuthService.update_user_role(
        db, user_id, new_role, tenant_id=user["tenant_id"]
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a user — ADMIN, and only within your own tenant."""
    result = await AuthService.deactivate_user(db, user_id, tenant_id=user["tenant_id"])
    if "error" in result:
        # user_not_found covers "belongs to another tenant" — a 404, not a 400.
        status = 404 if result["error"] == "user_not_found" else 400
        raise HTTPException(status_code=status, detail=result["error"])
    return result
