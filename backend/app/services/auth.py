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


def _create_token(user_id: str, email: str, role: str, tenant_id: str) -> str:
    """Create a simple signed token (base64 encoded JSON + HMAC signature)."""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat(),
        "iat": datetime.now(timezone.utc).isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(_get_secret_key().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a token. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        expected_sig = hmac.new(_get_secret_key().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        # Check expiry
        exp = datetime.fromisoformat(payload["exp"])
        if datetime.now(timezone.utc) > exp:
            return None
        return payload
    except Exception:
        return None


class AuthService:
    """Authentication and user management service."""

    @staticmethod
    async def seed_demo_user(db: AsyncSession):
        """Create the default demo admin account if it doesn't exist."""
        result = await db.execute(
            select(User).where(User.email == "demo@kaeos.ai")
        )
        existing = result.scalar_one_or_none()
        if existing:
            dirty = False
            # Self-heal: older seeds created the demo user under tenant "default",
            # which orphans it from the seeded demo data (tenant_acme).
            if existing.tenant_id != "tenant_acme":
                existing.tenant_id = "tenant_acme"
                dirty = True
            # Self-heal the display name (was "Demo Admin") so existing DBs update
            # without a reseed.
            if existing.display_name != "Daksh Aneja":
                existing.display_name = "Daksh Aneja"
                dirty = True
            if dirty:
                await db.commit()
                logger.info("[Auth] Demo admin account updated (tenant/name)")
            return

        demo = User(
            email="demo@kaeos.ai",
            display_name="Daksh Aneja",
            hashed_password=_hash_password("demo123"),
            role=UserRole.ADMIN,
            tenant_id="tenant_acme",
            is_active=True,
            is_demo=True,
        )
        db.add(demo)
        await db.commit()
        logger.info("[Auth] Demo admin account created: demo@kaeos.ai / demo123 (tenant: tenant_acme)")

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
        if user.is_demo:
            return {"error": "cannot_deactivate_demo"}
        user.is_active = False
        await db.commit()
        return {"id": user.id, "is_active": False}
