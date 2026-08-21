"""
KAEOS — Authentication Service
JWT token management, password hashing, user CRUD with RBAC enforcement.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import hashlib
import secrets

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


async def _hash_password(password: str) -> str:
    """Hash password with bcrypt (preferred) or SHA-256 fallback.

    bcrypt is deliberately expensive (~220 ms here), and it is pure CPU. Run on
    the event loop it stalls every other in-flight request in the process --
    gate pipelines, WebSocket pings, LLM calls -- so concurrent logins serialize.
    Offloaded to a worker thread per the project rule: never block the loop.
    """
    if _HAS_BCRYPT:
        return await asyncio.to_thread(_pwd_ctx.hash, password)
    # Legacy fallback
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


async def _verify_password(password: str, hashed: str) -> bool:
    """Verify password — supports bcrypt and legacy SHA-256 hashes.

    Offloaded for the same reason as _hash_password: bcrypt verify measured
    ~207 ms of blocking CPU.
    """
    try:
        # bcrypt hashes start with $2b$
        if _HAS_BCRYPT and hashed.startswith("$2"):
            return await asyncio.to_thread(_pwd_ctx.verify, password, hashed)
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

# Shared session/lockout state. Redis is the source of truth so a logout or a
# lockout is seen by EVERY worker (start-prod.sh runs 4). When Redis is
# unreachable these in-process structures are the fallback, so single-instance
# dev/demo works with no extra infra (the per-process caveat then applies again).
# jti -> token exp (epoch). Expiry-keyed so the fallback denylist can evict
# entries once the token they revoke could no longer be presented anyway —
# a plain set grew by one entry per logout until process restart.
_revoked_jti: dict[str, float] = {}
_failed_logins: dict[str, list[float]] = {}   # email -> [failure epoch seconds]
_FALLBACK_TOKEN_LIFETIME = 86400 * 8   # eviction horizon when a token has no exp

_JTI_KEY = "jwt:revoked:{jti}"
_FAIL_KEY = "login:fail:{email}"


async def _redis():
    try:
        from app.core.redis import get_redis
        return await get_redis()
    except Exception:
        return None


async def revoke_token(token: str) -> bool:
    """Add a token's jti to the shared denylist (logout). Returns True if revoked.

    Writes to Redis (seen by all workers) AND the local set (dev fallback). The
    Redis key expires when the token would have expired anyway, so the denylist
    cannot grow without bound.
    """
    payload = decode_token(token)
    if not (payload and payload.get("jti")):
        return False
    jti = payload["jti"]
    import time
    now = time.time()
    _revoked_jti[jti] = float(payload.get("exp") or (now + _FALLBACK_TOKEN_LIFETIME))
    # Amortized eviction: logouts are rare, so an O(n) prune per revoke keeps
    # the fallback denylist bounded by the number of still-live revocations.
    for stale in [j for j, exp in _revoked_jti.items() if exp < now]:
        _revoked_jti.pop(stale, None)
    r = await _redis()
    if r is not None:
        ttl = int((payload.get("exp") or 0) - time.time())
        try:
            await r.set(_JTI_KEY.format(jti=jti), "1", ex=max(ttl, 1))
        except Exception:
            pass  # fallback set already holds it on this worker
    return True


async def is_jti_revoked(jti: str) -> bool:
    """True if this token's jti has been revoked (checked at the async boundaries)."""
    if not jti:
        return False
    if jti in _revoked_jti:
        return True
    r = await _redis()
    if r is not None:
        try:
            return bool(await r.exists(_JTI_KEY.format(jti=jti)))
        except Exception:
            return False
    return False


def _create_token(user_id: str, email: str, role: str, tenant_id: str,
                  department: Optional[str] = None) -> str:
    """Mint a signed JWT for an authenticated session.

    ``department`` carries the user's department scope (None = org-wide) so
    per-request enforcement never needs a DB lookup.
    """
    import jwt
    import uuid
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "department": department,
        "jti": uuid.uuid4().hex,   # per-session id, enables revocation (logout)
        "iss": _JWT_ISS,
        "aud": _JWT_AUD,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_JWT_ALG)


def decode_token(token: str) -> Optional[dict]:
    """Verify a JWT and return its claims, or None if invalid/expired."""
    import jwt
    try:
        # Revocation is enforced at the async auth boundaries (get_current_user,
        # TenantMiddleware's JWT branch, the WS handshake) via is_jti_revoked(),
        # not here: decode_token is synchronous and the shared denylist lives in
        # Redis (an async client). Keeping the check out of this hot sync path also
        # avoids a Redis round-trip on every token parse.
        return jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[_JWT_ALG],
            audience=_JWT_AUD,
            issuer=_JWT_ISS,
        )
    except jwt.PyJWTError:
        # Malformed, mis-signed, or expired token -> unauthenticated.
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
            existing.hashed_password = await _hash_password(password)
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
                hashed_password=await _hash_password(password),
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
    async def _is_locked_out(email: str) -> bool:
        """True if this email has too many recent failures (brute-force guard).

        Redis-backed so the counter is shared across workers; falls back to the
        in-process window when Redis is down.
        """
        s = get_settings()
        r = await _redis()
        if r is not None:
            try:
                val = await r.get(_FAIL_KEY.format(email=email))
                return int(val or 0) >= s.LOGIN_MAX_FAILURES
            except Exception:
                pass
        import time
        window_start = time.time() - s.LOGIN_LOCKOUT_SECONDS
        recent = [t for t in _failed_logins.get(email, []) if t >= window_start]
        if recent:
            _failed_logins[email] = recent  # prune the window
        else:
            # Drop the key entirely: attempted emails are attacker-controlled,
            # so an empty-list writeback grew the dict one key per probe forever.
            _failed_logins.pop(email, None)
        return len(recent) >= s.LOGIN_MAX_FAILURES

    @staticmethod
    async def _record_failure(email: str) -> None:
        s = get_settings()
        r = await _redis()
        if r is not None:
            try:
                key = _FAIL_KEY.format(email=email)
                n = await r.incr(key)
                if n == 1:
                    await r.expire(key, s.LOGIN_LOCKOUT_SECONDS)
                return
            except Exception:
                pass
        import time
        _failed_logins.setdefault(email, []).append(time.time())

    @staticmethod
    async def _clear_failures(email: str) -> None:
        _failed_logins.pop(email, None)
        r = await _redis()
        if r is not None:
            try:
                await r.delete(_FAIL_KEY.format(email=email))
            except Exception:
                pass

    @staticmethod
    async def login(db: AsyncSession, email: str, password: str,
                    ip_address: str | None = None, mfa_code: str | None = None) -> Optional[dict]:
        """Authenticate user and return JWT token.

        Brute-force protection: after LOGIN_MAX_FAILURES failures within
        LOGIN_LOCKOUT_SECONDS the email is locked out. Every attempt (success,
        failure, lockout) is written to the security audit log.
        """
        from app.core.audit import record_security_event
        _tenant_for_audit = get_settings().ADMIN_TENANT  # best-effort tenant for pre-auth events

        if await AuthService._is_locked_out(email):
            await record_security_event(
                tenant_id=_tenant_for_audit, event_type="AUTH_FAILURE", action="LOGIN",
                result="BLOCKED", actor=email, ip_address=ip_address,
                details={"reason": "locked_out"})
            return None

        result = await db.execute(
            select(User).where(User.email == email, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user or not await _verify_password(password, user.hashed_password):
            await AuthService._record_failure(email)
            await record_security_event(
                tenant_id=(user.tenant_id if user else _tenant_for_audit),
                event_type="AUTH_FAILURE", action="LOGIN", result="BLOCKED",
                actor=email, ip_address=ip_address, details={"reason": "bad_credentials"})
            return None

        # Success — clear the failure counter (shared + local).
        await AuthService._clear_failures(email)

        # Second factor: if MFA is enabled for this user, a valid TOTP code is
        # required before a session is issued. Missing/invalid code returns a
        # challenge (not a token) so the client can prompt for the code.
        from app.services import mfa as mfa_svc
        if await mfa_svc.is_enabled(user.id):
            if not mfa_code or not await mfa_svc.verify_login_code(user.id, mfa_code):
                # A WRONG code (not merely a missing one) is a second-factor guess:
                # count it toward the lockout so the 6-digit TOTP cannot be
                # brute-forced by an attacker who already has the password.
                if mfa_code:
                    await AuthService._record_failure(email)
                await record_security_event(
                    tenant_id=user.tenant_id, event_type="AUTH_MFA", action="LOGIN",
                    result="BLOCKED", actor=user.email, ip_address=ip_address,
                    details={"reason": "mfa_required" if not mfa_code else "mfa_invalid"})
                return {"mfa_required": True}

        # Update login tracking
        user.login_count = (user.login_count or 0) + 1
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        await record_security_event(
            tenant_id=user.tenant_id, event_type="AUTH_SUCCESS", action="LOGIN",
            result="ALLOWED", actor=user.email, actor_role=user.role.value,
            ip_address=ip_address)

        token = _create_token(user.id, user.email, user.role.value, user.tenant_id,
                              department=getattr(user, "department", None))
        return {
            "token": token,
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role.value,
                "tenant_id": user.tenant_id,
                "department": getattr(user, "department", None),
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
        # Password policy — the primary user-creation path used to accept any
        # string (including empty). Enforce a minimum length here.
        min_len = get_settings().MIN_PASSWORD_LENGTH
        if not password or len(password) < min_len:
            return {"error": "weak_password",
                    "detail": f"Password must be at least {min_len} characters."}
        # Check if email exists
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            return {"error": "email_already_exists"}

        user = User(
            email=email,
            display_name=display_name,
            hashed_password=await _hash_password(password),
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
            "department": getattr(u, "department", None),
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

    @staticmethod
    async def reactivate_user(db: AsyncSession, user_id: str, tenant_id: str) -> dict:
        """Re-enable a previously deactivated account WITHIN the caller's tenant."""
        user = (await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not user:
            return {"error": "user_not_found"}
        user.is_active = True
        await db.commit()
        return {"id": user.id, "is_active": True}

    @staticmethod
    async def invite_user(db: AsyncSession, email: str, display_name: str, role: UserRole,
                          created_by: str, tenant_id: str,
                          department: Optional[str] = None) -> dict:
        """Invite a user WITHOUT the admin typing their password.

        Creates an INACTIVE account with an unusable random password and returns a
        signed, short-lived invite token. The invitee sets their own password via
        ``accept_invite`` (a magic-link flow), so no plaintext password is ever
        handled by the admin. Email delivery of the link is a deployment concern.
        """
        import jwt
        email = (email or "").strip().lower()
        if not email:
            return {"error": "email_required"}
        if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
            return {"error": "email_already_exists"}

        # Seat cap: managed cloud only, so self-host stays unlimited and
        # byte-identical. An invite consumes a seat, so refuse once active users
        # already fill the purchased seats. ponytail: counts active users only, so
        # pending invites are not yet charged against seats; enforce at
        # accept_invite too if strict provisioning matters. Fail-closed: an
        # unknown/absent seat count defaults to 1.
        from app.core.entitlements import _managed_cloud
        if _managed_cloud():
            from sqlalchemy import func
            from app.models.billing import BillingAccount
            acct = await db.get(BillingAccount, tenant_id)
            seats = max(1, int(acct.seats or 1)) if acct is not None else 1
            active_users = (await db.execute(
                select(func.count()).select_from(User).where(
                    User.tenant_id == tenant_id,
                    User.is_active == True,  # noqa: E712
                )
            )).scalar_one()
            if active_users >= seats:
                return {"error": "seat_limit_reached"}

        user = User(
            email=email, display_name=display_name or email,
            hashed_password=await _hash_password(secrets.token_urlsafe(32)),  # unusable until accepted
            role=role, tenant_id=tenant_id, created_by=created_by, is_active=False,
            department=department,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"purpose": "invite", "user_id": user.id, "tenant_id": tenant_id,
             "aud": "kaeos-invite", "iat": now, "exp": now + timedelta(days=7)},
            _get_secret_key(), algorithm="HS256",
        )
        logger.info(f"[Auth] Invited {email} (role={role.value}) by {created_by}")
        return {"id": user.id, "email": email, "role": role.value,
                "invite_token": token, "expires_in_days": 7, "is_active": False}

    @staticmethod
    async def accept_invite(db: AsyncSession, token: str, password: str) -> dict:
        """Complete an invite: validate the token, set the password, activate."""
        import jwt
        min_len = get_settings().MIN_PASSWORD_LENGTH
        if not password or len(password) < min_len:
            return {"error": "weak_password",
                    "detail": f"Password must be at least {min_len} characters."}
        try:
            claims = jwt.decode(token, _get_secret_key(), algorithms=["HS256"], audience="kaeos-invite")
        except jwt.PyJWTError:
            return {"error": "invalid_or_expired_invite"}
        if claims.get("purpose") != "invite":
            return {"error": "invalid_or_expired_invite"}

        user = (await db.execute(select(User).where(User.id == claims["user_id"]))).scalar_one_or_none()
        if not user:
            return {"error": "user_not_found"}
        user.hashed_password = await _hash_password(password)
        user.is_active = True
        await db.commit()
        logger.info(f"[Auth] Invite accepted: {user.email}")
        return {"id": user.id, "email": user.email, "is_active": True}
