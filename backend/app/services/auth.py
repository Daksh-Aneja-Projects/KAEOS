"""
KAEOS — Authentication Service
JWT token management, password hashing, user CRUD with RBAC enforcement.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import hashlib
import hmac
import secrets
import json
import base64

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User, UserRole

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_HOURS = 24


def _get_secret_key() -> str:
    """Resolve the signing key at call time.

    Read lazily (not at import) so the ephemeral key generated in main.py's
    lifespan for DEV_MODE is picked up; production startup already fails fast
    via Settings.validate_production_security() when SECRET_KEY is missing.
    """
    key = get_settings().SECRET_KEY
    if not key:
        raise RuntimeError("SECRET_KEY must be set via environment variable. See .env.example")
    return key

# bcrypt via passlib — already in requirements.txt, way stronger than SHA-256
try:
    from passlib.context import CryptContext
    _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False
    logger.warning("[Auth] passlib[bcrypt] not installed — falling back to SHA-256 (NOT production-safe)")


def _hash_password(password: str) -> str:
    """Hash password with bcrypt (preferred) or SHA-256 fallback."""
    if _HAS_BCRYPT:
        return _pwd_ctx.hash(password)
    # Legacy fallback
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password: str, hashed: str) -> bool:
    """Verify password — supports bcrypt and legacy SHA-256 hashes."""
    try:
        # bcrypt hashes start with $2b$
        if _HAS_BCRYPT and hashed.startswith("$2"):
            return _pwd_ctx.verify(password, hashed)
        # Legacy SHA-256 format: salt:hash
        salt, stored_hash = hashed.split(":")
        computed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return computed == stored_hash
    except (ValueError, AttributeError):
        return False


# ── JWT (RFC 7519 via PyJWT) ─────────────────────────────────────────────────
# Replaces the previous hand-rolled base64(json)+HMAC token. PyJWT pins the
# accepted `alg` on decode, so a token cannot be down-graded to alg="none", and
# it handles `iss`/`aud`/`exp`/`nbf` with constant-time signature verification.
#
# We use PyJWT rather than python-jose deliberately: python-jose is effectively
# unmaintained and carries a known algorithm-confusion advisory (CVE affecting
# OpenSSH ECDSA key handling). PyJWT is actively maintained.
_JWT_ALG = "HS256"
_JWT_ISS = "kaeos"
_JWT_AUD = "kaeos-api"


def _create_token(user_id: str, email: str, role: str, tenant_id: str) -> str:
    """Mint a signed JWT for an authenticated session."""
    import jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "iss": _JWT_ISS,
        "aud": _JWT_AUD,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_JWT_ALG)


def decode_token(token: str) -> Optional[dict]:
    """Verify a JWT and return its claims, or None if invalid/expired.

    Backwards-compatible: still accepts the legacy `payload.signature` HMAC
    token so sessions issued before the JWT migration keep working until expiry.
    """
    import jwt
    try:
        return jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[_JWT_ALG],
            audience=_JWT_AUD,
            issuer=_JWT_ISS,
        )
    except jwt.PyJWTError:
        pass
    # Legacy fallback: verify the old base64(json)+HMAC format so live sessions
    # are not force-logged-out by the upgrade. Remove after one token lifetime.
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        expected_sig = hmac.new(_get_secret_key().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = datetime.fromisoformat(payload["exp"])
        if datetime.now(timezone.utc) > exp:
            return None
        return payload
    except Exception:
        return None


class AuthService:
    """Authentication and user management service."""

    @staticmethod
    async def seed_admin_user(db: AsyncSession):
        """Provision the root admin account from configuration.

        SECURITY: this replaces the old hardcoded `demo@kaeos.ai / demo123`
        account that was seeded into every deployment. The password now comes
        from ADMIN_PASSWORD (set in .env). Outside DEV_MODE, if no password is
        configured NO admin is seeded — a fresh install never ships with a
        known-public login. Any lingering legacy demo account is neutralised.
        """
        settings = get_settings()
        email = (settings.ADMIN_EMAIL or "").strip().lower()

        # 1. Neutralise the legacy public demo account if it still exists and is
        #    not the configured admin — closes the old "demo123" backdoor on
        #    databases created before this fix.
        legacy = (await db.execute(
            select(User).where(User.email == "demo@kaeos.ai")
        )).scalar_one_or_none()
        if legacy and legacy.email != email:
            if legacy.is_active:
                legacy.is_active = False
                await db.commit()
                logger.warning(
                    "[Auth] Legacy demo account demo@kaeos.ai DISABLED "
                    "(replaced by configured ADMIN_EMAIL)."
                )

        # 2. Resolve the password. In DEV_MODE we generate an ephemeral one and
        #    log it once; in any other environment we require ADMIN_PASSWORD.
        password = settings.ADMIN_PASSWORD or ""
        generated = False
        if not password:
            if settings.DEV_MODE:
                password = secrets.token_urlsafe(12)
                generated = True
            else:
                logger.warning(
                    "[Auth] ADMIN_PASSWORD is not set and DEV_MODE is off — "
                    "NOT seeding an admin account. Set ADMIN_PASSWORD in .env "
                    "and restart to provision %s.", email or "the admin user",
                )
                return

        if not email:
            logger.warning("[Auth] ADMIN_EMAIL is empty — skipping admin seed.")
            return

        # Register the admin's tenant in the tenant registry (source of truth).
        from app.services.tenant_registry import ensure_tenant
        await ensure_tenant(db, settings.ADMIN_TENANT, name=settings.ADMIN_TENANT)

        # 3. Upsert the admin by email.
        existing = (await db.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()
        if existing:
            existing.hashed_password = _hash_password(password)
            existing.role = UserRole.ADMIN
            existing.tenant_id = settings.ADMIN_TENANT
            existing.display_name = settings.ADMIN_DISPLAY_NAME
            existing.is_active = True
            existing.is_demo = False
            await db.commit()
            logger.info("[Auth] Admin account synced from config: %s", email)
        else:
            admin = User(
                email=email,
                display_name=settings.ADMIN_DISPLAY_NAME,
                hashed_password=_hash_password(password),
                role=UserRole.ADMIN,
                tenant_id=settings.ADMIN_TENANT,
                is_active=True,
                is_demo=False,
            )
            db.add(admin)
            await db.commit()
            logger.info("[Auth] Admin account provisioned: %s (tenant: %s)",
                        email, settings.ADMIN_TENANT)
        if generated:
            logger.warning(
                "[Auth] DEV_MODE generated a temporary admin password for %s: %s "
                "(set ADMIN_PASSWORD in .env to make it stable)", email, password,
            )

    @staticmethod
    async def login(db: AsyncSession, email: str, password: str) -> Optional[dict]:
        """Authenticate user and return JWT token."""
        result = await db.execute(
            select(User).where(User.email == email, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user or not _verify_password(password, user.hashed_password):
            return None

        # Update login tracking
        user.login_count = (user.login_count or 0) + 1
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        token = _create_token(user.id, user.email, user.role.value, user.tenant_id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role.value,
                "tenant_id": user.tenant_id,
                "is_demo": user.is_demo,
            }
        }

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[dict]:
        """Get user profile by ID."""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
            "tenant_id": user.tenant_id,
            "is_active": user.is_active,
            "is_demo": user.is_demo,
            "login_count": user.login_count,
            "last_login_at": str(user.last_login_at) if user.last_login_at else None,
            "created_at": str(user.created_at) if user.created_at else None,
        }

    @staticmethod
    async def create_user(
        db: AsyncSession,
        email: str,
        display_name: str,
        password: str,
        role: UserRole,
        created_by: str,
        tenant_id: str,
    ) -> dict:
        """Create a new user (ADMIN only). tenant_id is REQUIRED - no default,
        so a caller that forgets it fails loudly instead of writing a user into
        a bogus "default" tenant."""
        # Check if email exists
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            return {"error": "email_already_exists"}

        user = User(
            email=email,
            display_name=display_name,
            hashed_password=_hash_password(password),
            role=role,
            tenant_id=tenant_id,
            created_by=created_by,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"[Auth] User created: {email} (role={role.value}) by {created_by}")
        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
        }

    @staticmethod
    async def list_users(db: AsyncSession, tenant_id: str) -> list:
        """List all users for a tenant. tenant_id is REQUIRED - no default."""
        result = await db.execute(
            select(User).where(User.tenant_id == tenant_id)
            .order_by(User.created_at.desc())
        )
        users = result.scalars().all()
        return [{
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role.value,
            "is_active": u.is_active,
            "is_demo": u.is_demo,
            "login_count": u.login_count,
            "last_login_at": str(u.last_login_at) if u.last_login_at else None,
            "created_at": str(u.created_at) if u.created_at else None,
        } for u in users]

    # `tenant_id` below is REQUIRED and has no default ON PURPOSE.
    #
    # These two looked the user up by id alone, so ANY tenant's ADMIN could
    # promote a user in ANOTHER tenant to ADMIN, or disable their accounts -
    # a full cross-tenant account takeover from an ordinary admin session.
    #
    # `users` is deliberately exempt from row-level security (login must resolve
    # the tenant FROM the user, so it cannot already know it - see GLOBAL_TABLES
    # in app/core/rls.py). That means these filters are the ONLY thing separating
    # tenants here: there is NO database backstop. A default value would let a
    # caller silently fall back to the wrong tenant, so there isn't one.

    @staticmethod
    async def update_user_role(
        db: AsyncSession, user_id: str, new_role: UserRole, tenant_id: str
    ) -> dict:
        """Update a role for a user WITHIN the caller's tenant."""
        result = await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            # Same answer whether the user is absent or belongs to another
            # tenant: distinguishing them confirms account ids across tenants.
            return {"error": "user_not_found"}
        user.role = new_role
        await db.commit()
        return {"id": user.id, "role": new_role.value}

    @staticmethod
    async def deactivate_user(db: AsyncSession, user_id: str, tenant_id: str) -> dict:
        """Deactivate an account WITHIN the caller's tenant."""
        result = await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return {"error": "user_not_found"}
        # Safety: never allow a tenant to disable its own last active admin —
        # that would lock everyone out. (The old rule blocked disabling demo
        # accounts unconditionally, which is why the public demo login could
        # never be turned off; that account no longer exists.)
        if user.role == UserRole.ADMIN and user.is_active:
            from sqlalchemy import func
            active_admins = (await db.execute(
                select(func.count()).select_from(User).where(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN,
                    User.is_active == True,  # noqa: E712
                )
            )).scalar_one()
            if active_admins <= 1:
                return {"error": "cannot_deactivate_last_admin"}
        user.is_active = False
        await db.commit()
        return {"id": user.id, "is_active": False}
