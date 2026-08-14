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
    mfa_code: Optional[str] = None   # required only when the account has MFA enabled


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

    from app.services.auth import is_jti_revoked
    if await is_jti_revoked(payload.get("jti")):
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

    from app.core.net import client_ip
    ip = client_ip(request)
    result = await AuthService.login(db, email, password, ip_address=ip, mfa_code=data.mfa_code)
    if not result:
        # Same message for bad credentials and lockout — don't reveal which.
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if result.get("mfa_required"):
        # Password was correct; a valid TOTP code is still required. 401 with a
        # machine-readable flag so the client prompts for the code and retries.
        raise HTTPException(status_code=401, detail={"mfa_required": True,
                                                     "message": "Multi-factor code required"})

    return result


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """Revoke the caller's current token (adds its jti to the denylist)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    revoked = await revoke_token(token)
    return {"revoked": revoked}

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


@router.get("/users/export.csv")
async def export_access_review(
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """Access-review export (SOC2 CC6.x evidence): every account with role,
    department scope, status and last activity, as auditor-ready CSV."""
    from app.core.csv_export import csv_response
    users = await AuthService.list_users(db, user["tenant_id"])
    rows = [{
        "email": r["email"], "display_name": r["display_name"], "role": r["role"],
        "department": r.get("department") or "org-wide",
        "status": "active" if r["is_active"] else "deactivated",
        "login_count": r["login_count"],
        "last_login_at": r["last_login_at"] or "never",
        "created_at": r["created_at"],
    } for r in users]
    return csv_response(rows, "access_review",
                        ["email", "display_name", "role", "department", "status",
                         "login_count", "last_login_at", "created_at"])


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


@router.put("/users/{user_id}/department")
async def update_department(
    user_id: str,
    data: dict,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """Set or clear a user's department scope - ADMIN, within your own tenant.

    Body: {"department": "hr"} confines the user to the HR surface;
    {"department": null} restores org-wide access. Takes effect on the user's
    NEXT login (the scope rides in the JWT).
    """
    from app.models.auth import User as UserModel
    from sqlalchemy import select as _select
    dept = data.get("department")
    valid = {"hr", "finance", "legal", "sales", "support", "operations", "engineering"}
    if dept is not None and dept not in valid:
        raise HTTPException(status_code=400,
                            detail=f"department must be one of {sorted(valid)} or null")
    target = (await db.execute(_select(UserModel).where(
        UserModel.id == user_id, UserModel.tenant_id == user["tenant_id"]
    ))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    target.department = dept
    db.add(target)
    await db.commit()
    return {"id": target.id, "email": target.email, "department": target.department,
            "note": "Scope applies from the user's next login."}


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


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Re-enable a deactivated user — ADMIN, within your own tenant."""
    result = await AuthService.reactivate_user(db, user_id, tenant_id=user["tenant_id"])
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/users/invite")
async def invite_user(
    data: dict,
    user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user via a magic-link token instead of the admin typing a password."""
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Authenticated user has no tenant context")
    role_map = {"ADMIN": UserRole.ADMIN, "ANALYST": UserRole.ANALYST, "VIEWER": UserRole.VIEWER}
    role = role_map.get(data.get("role", "VIEWER"), UserRole.VIEWER)
    dept = data.get("department") or None
    _valid_depts = {"hr", "finance", "legal", "sales", "support", "operations", "engineering"}
    if dept is not None and dept not in _valid_depts:
        raise HTTPException(status_code=400,
                            detail=f"department must be one of {sorted(_valid_depts)} or null")
    result = await AuthService.invite_user(
        db, email=data.get("email", ""), display_name=data.get("display_name", ""),
        role=role, created_by=user["id"], tenant_id=tenant_id, department=dept,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Email the magic link to the invitee when an SMTP channel is configured -
    # otherwise the admin still gets the link in the response to share manually.
    from app.core.config import get_settings
    _base = (get_settings().FRONTEND_BASE_URL or "http://localhost:5174").rstrip("/")
    invite_link = f"{_base}/accept-invite?token={result['invite_token']}" \
        if result.get("invite_token") else None
    if invite_link:
        result["invite_link"] = invite_link
    invitee = data.get("email", "")
    if invite_link and invitee:
        from app.services.notifier import notify_fire_and_forget
        notify_fire_and_forget(
            tenant_id, "user.invited",
            subject="You have been invited to KAEOS",
            body=(f"Hello{' ' + data.get('display_name', '') if data.get('display_name') else ''},\n\n"
                  f"You have been invited to join KAEOS. Open the link below to set "
                  f"your password and activate your account:\n\n{invite_link}\n\n"
                  f"If you did not expect this invitation, you can ignore this email."),
            data={"email": invitee},
            to_override=[invitee],
        )
    return result


class AcceptInviteRequest(BaseModel):
    token: str
    password: str


@router.post("/accept-invite")
async def accept_invite(data: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """Complete an invite (public): set the password and activate the account."""
    result = await AuthService.accept_invite(db, data.token, data.password)
    if "error" in result:
        status = 404 if result["error"] == "user_not_found" else 400
        raise HTTPException(status_code=status, detail=result["error"])
    return result


# ── MFA (TOTP) — enroll / confirm / disable / status ──────────────────────────

class MFACodeRequest(BaseModel):
    code: str


@router.get("/mfa/status")
async def mfa_status(user: dict = Depends(get_current_user)):
    """Whether the caller has MFA enrolled/enabled."""
    from app.services import mfa as mfa_svc
    return await mfa_svc.status(user["id"])


@router.post("/mfa/enroll")
async def mfa_enroll(user: dict = Depends(get_current_user)):
    """Start MFA enrollment: returns a TOTP secret + otpauth URI (shown once).

    Call `/mfa/confirm` with a code from the authenticator to actually enable it.
    """
    from app.services import mfa as mfa_svc
    return await mfa_svc.begin_enrollment(user["id"], user["tenant_id"], account=user["email"])


@router.post("/mfa/confirm")
async def mfa_confirm(data: MFACodeRequest, user: dict = Depends(get_current_user)):
    """Confirm enrollment with a code from the authenticator, enabling MFA."""
    from app.services import mfa as mfa_svc
    result = await mfa_svc.confirm_enrollment(user["id"], data.code)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/mfa/disable")
async def mfa_disable(user: dict = Depends(get_current_user)):
    """Disable MFA for the caller's own account."""
    from app.services import mfa as mfa_svc
    return await mfa_svc.disable(user["id"])
