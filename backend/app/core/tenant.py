"""
KAEOS — Tenant Resolution Middleware + FastAPI Dependency
Replaces the hardcoded TENANT = "default" across all 15+ route files.

HOW IT WORKS
─────────────
1. TenantMiddleware (Starlette BaseHTTPMiddleware) runs on every request.
   It reads the Authorization: Bearer <kt_xxx> header, resolves the tenant
   via the DB-backed api_keys table (auth.py), and writes the tenant context
   to request.state.tenant.

2. get_tenant() is a FastAPI Depends() function that reads request.state.tenant.
   Any route that previously used TENANT = "default" should inject:
       tenant: dict = Depends(get_tenant)
   and reference tenant["tenant_id"] instead.

3. get_tenant_id() is a convenience shortcut that returns just the string ID.

MIGRATION GUIDE (per route file)
──────────────────────────────────
BEFORE (agent_factory.py, rules.py, etc.):
    TENANT = "default"
    ...
    @router.get("/agents/blueprints")
    async def list_blueprints():
        ...where(AgentBlueprint.tenant_id == TENANT)...

AFTER:
    from app.core.tenant import get_tenant_id
    ...
    @router.get("/agents/blueprints")
    async def list_blueprints(tenant_id: str = Depends(get_tenant_id)):
        ...where(AgentBlueprint.tenant_id == tenant_id)...

MAIN.PY CHANGE
───────────────
Add before the router registrations:
    from app.core.tenant import TenantMiddleware
    app.add_middleware(TenantMiddleware)
"""
import logging

from fastapi import Depends, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Dev-mode default — used when no API keys are registered (local development)
_DEV_TENANT = {
    "tenant_id": "tenant_acme",
    "role": "admin",
    "name": "dev_user",
}

# Role hierarchy — used by require_role() dependency
ROLE_HIERARCHY = {"viewer": 0, "operator": 1, "admin": 2}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that resolves the tenant for every request.

    Flow:
      1. No Authorization header  → dev mode tenant (DEV_MODE)
                                  → 401 in production
      2. Authorization: Bearer <key>  → hash key → lookup in the api_keys table
                                      → 401 if not found / inactive
      3. On success: writes tenant context to request.state.tenant

    The middleware never raises exceptions directly — it returns JSON 401/403
    responses so FastAPI's exception handlers process them correctly.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Publish the tenant into the ambient context as soon as it is known,
        # so DB sessions opened deep in the service layer (which never see
        # `request`) can bind themselves for row-level security, and the LLM
        # router knows whose usage to meter. Wrapping call_next means every
        # resolution path below is covered by one hook instead of four.
        original_call_next = call_next

        async def call_next(req: Request):  # noqa: F811 - deliberate shadow
            from app.core.context import current_actor, current_tenant_id
            tenant = getattr(req.state, "tenant", None)
            if isinstance(tenant, dict) and tenant.get("tenant_id"):
                current_tenant_id.set(tenant["tenant_id"])
                # Same hook publishes who is acting. Requests carry a person;
                # background jobs never pass through here, so they stay None.
                actor = tenant.get("user_id") or tenant.get("name")
                if actor:
                    current_actor.set(str(actor))
            return await original_call_next(req)

        # Health checks, docs, and auth routes don't need auth.
        # SECURITY: gate on the raw ASGI scope path, NOT request.url.path.
        # request.url is reconstructed from the (attacker-controlled) Host header,
        # so a malformed `Host: victim/health?x=` makes request.url.path read
        # "/health" while the router still dispatches the real protected route from
        # scope["path"] — an auth bypass (GHSA-86qp, unpatched in Starlette <1.0.1,
        # which no FastAPI supports). scope["path"] is the path the router actually
        # matched and cannot be poisoned this way.
        req_path = request.scope["path"]
        public_paths = ("/health", "/health/live", "/docs", "/openapi.json", "/redoc", "/metrics")
        # Inbound sync ingest is PUBLIC BY DESIGN: external systems (Workday,
        # Salesforce, relays) cannot hold KAEOS JWTs. Each request is instead
        # authenticated by an HMAC-SHA256 signature over the raw body using the
        # connector's webhook secret (see app/services/sync_engine.ingest_webhook)
        # - the unguessable connector id alone grants nothing.
        if req_path.startswith("/api/v1/integrations/ingest/"):
            request.state.tenant = None
            return await call_next(request)
        # Pre-auth auth routes. SSO login/callback/discovery MUST be reachable
        # without a session (that is the whole point); the SSO *config* endpoints
        # (/auth/sso/connections) are deliberately NOT here — they require ADMIN.
        auth_paths = (
            # Approval-by-link: the approver has no KAEOS session by design; the
            # signed single-purpose token IS the authentication (see approvals.py).
            "/api/v1/approvals/decide",
            "/api/v1/auth/login",
            "/api/v1/auth/accept-invite",   # invitee sets their password pre-session
            "/api/v1/auth/sso/saml",
            "/api/v1/auth/sso/oidc",
            "/api/v1/auth/sso/discover",
        )
        if req_path in public_paths or any(req_path.startswith(p) for p in auth_paths):
            request.state.tenant = _DEV_TENANT
            return await call_next(request)

        from app.core.auth import get_api_key_by_hash, hash_key
        from app.core.config import get_settings
        settings = get_settings()

        # Dev bypass — respect DEV_MODE flag. An explicit X-Tenant-ID header
        # still selects the tenant so multi-tenant scenarios (e.g. onboarding a
        # second company, RealCo) are viewable locally without full auth. Absent
        # the header, default to the dev tenant.
        if settings.DEV_MODE:
            override = request.headers.get("X-Tenant-ID")
            if override:
                request.state.tenant = {**_DEV_TENANT, "tenant_id": override}
                logger.debug(f"[Tenant] Dev bypass — X-Tenant-ID override: {override}")
            else:
                request.state.tenant = _DEV_TENANT
                logger.debug("[Tenant] Dev bypass — DEV_MODE is True")
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(f"[Tenant] Missing bearer token: {req_path}")
            return _unauthorized("Missing Authorization: Bearer <token> header")

        raw_key = auth_header.removeprefix("Bearer ").strip()

        # JWT session token (issued by /auth/login) — two-part "payload.signature"
        if not raw_key.startswith("kt_"):
            from app.services.auth import decode_token
            payload = decode_token(raw_key)
            if not payload:
                return _unauthorized("Invalid or expired token")
            # Map user RBAC roles (ADMIN/ANALYST/VIEWER) onto tenant roles
            jwt_role_map = {"ADMIN": "admin", "ANALYST": "operator", "VIEWER": "viewer"}
            # department claim: None/absent = org-wide user
            request.state.tenant = {
                "tenant_id": payload.get("tenant_id", "default"),
                "role": jwt_role_map.get(payload.get("role", ""), "viewer"),
                "name": payload.get("email", "user"),
                "user_id": payload.get("user_id"),
                "department": payload.get("department"),
            }
            logger.debug(
                f"[Tenant] JWT resolved: tenant_id={request.state.tenant['tenant_id']} "
                f"role={request.state.tenant['role']} path={req_path}"
            )
            return await call_next(request)

        # API key path (starts with "kt_")
        if len(raw_key) < 20:
            return _unauthorized("Invalid token format (must be 'kt_xxx' API key or 'xxx.yyy' JWT)")

        hashed = hash_key(raw_key)
        key_meta = await get_api_key_by_hash(hashed)

        if not key_meta:
            logger.warning(f"[Tenant] Unknown API key presented: {raw_key[:12]}…")
            return _unauthorized("API key not recognised")

        if not key_meta.get("active", True):
            logger.warning(f"[Tenant] Revoked key used: {raw_key[:12]}…")
            return _unauthorized("API key has been revoked")

        # Check IP Allowlisting (L-07)
        allowed_ips = key_meta.get("allowed_ips", [])
        client_ip = request.client.host if request.client else None
        if allowed_ips and client_ip and client_ip not in allowed_ips:
            logger.warning(f"[Tenant] IP {client_ip} not allowed for tenant {key_meta['tenant_id']}")
            return _unauthorized("IP address not allowed for this tenant")

        # Check CORS Origin (L-06)
        allowed_origins = key_meta.get("allowed_origins", [])
        origin = request.headers.get("origin")
        if origin and allowed_origins and origin not in allowed_origins:
            logger.warning(f"[Tenant] Origin {origin} not allowed for tenant {key_meta['tenant_id']}")
            return _unauthorized("Origin not allowed for this tenant")

        request.state.tenant = {
            "tenant_id": key_meta["tenant_id"],
            "role": key_meta.get("role", "operator"),
            "name": key_meta.get("name", "unknown"),
        }

        logger.debug(
            f"[Tenant] API key resolved: tenant_id={key_meta['tenant_id']} "
            f"role={key_meta.get('role')} path={req_path}"
        )

        return await call_next(request)


# ── FastAPI dependency functions ─────────────────────────────────────────────

def get_tenant(request: Request) -> dict:
    """
    FastAPI Depends() — returns the full tenant context dict.

    Usage:
        @router.get("/something")
        async def handler(tenant: dict = Depends(get_tenant)):
            tenant_id = tenant["tenant_id"]
            role = tenant["role"]
    """
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        # Middleware should have set this — if missing, it's a config error
        raise HTTPException(
            status_code=500,
            detail="Tenant context not resolved. Ensure TenantMiddleware is registered.",
        )
    return tenant


def get_tenant_id(tenant: dict = Depends(get_tenant)) -> str:
    """
    FastAPI Depends() — returns just the tenant_id string.

    Usage (replaces TENANT = "default"):
        @router.get("/agents/blueprints")
        async def list_blueprints(tenant_id: str = Depends(get_tenant_id)):
            ...where(AgentBlueprint.tenant_id == tenant_id)...
    """
    return tenant["tenant_id"]


def require_role(required_role: str):
    """
    FastAPI Depends() factory — gates a route behind a minimum role.

    Roles in order of privilege: viewer < operator < admin
    Usage:
        @router.post("/agents/blueprint/{id}/deploy")
        async def deploy(
            tenant: dict = Depends(require_role("admin")),
        ):
            ...

    Returns the full tenant dict so the route can still use tenant_id.
    """
    def _checker(tenant: dict = Depends(get_tenant)) -> dict:
        caller_level = ROLE_HIERARCHY.get(tenant.get("role", "viewer"), 0)
        required_level = ROLE_HIERARCHY.get(required_role, 99)
        if caller_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required_role}' required. Caller has '{tenant.get('role')}'.",
            )
        return tenant

    return _checker


def require_department(department: str):
    """FastAPI Depends() factory - confines a surface to one department.

    Department-scoped RBAC: a user whose JWT carries department='hr' may only
    use the HR operational surface (data, agents, missions, approvals). Users
    with no department claim (org-wide users, API keys, dev mode) pass every
    department gate - scoping is opt-in per user.

    Deliberately NOT applied to cross-domain aggregates (org pulse, the twin,
    analytics) - correlating signal across departments is the product's IP and
    stays readable for every authenticated user. What a scoped user loses is
    other departments' RECORDS and ACTIONS, not the org-level insight.

    Usage (single point, on the router mount):
        app.include_router(hr_router, prefix=PREFIX,
                           dependencies=[Depends(require_department("hr"))])
    """
    def _checker(tenant: dict = Depends(get_tenant)) -> dict:
        scope = tenant.get("department")
        if scope and scope != department:
            raise HTTPException(
                status_code=403,
                detail=f"Department scope '{scope}' cannot access the "
                       f"'{department}' surface.",
            )
        return tenant

    return _checker


def check_department_scope(tenant: dict, department: str | None) -> None:
    """Imperative variant of require_department for per-row checks.

    Raises 403 when a scoped caller touches a row belonging to another
    department. ``department`` None/empty counts as unscoped data (allowed).
    """
    scope = tenant.get("department")
    if scope and department and scope != department:
        raise HTTPException(
            status_code=403,
            detail=f"Department scope '{scope}' cannot act on '{department}' items.",
        )


def require_service_or_role(required_role: str):
    """Gate for internal service / agent-mesh mutations.

    Passes when the caller presents a valid ``X-Service-Token`` (machine-to-machine)
    OR holds at least ``required_role``. Closes the prior hole where the agent-mesh
    / cost / model-routing endpoints were reachable by ANY authenticated viewer.
    DEV_MODE bypasses (consistent with the rest of the app), so local/e2e runs are
    unaffected; production enforces the token-or-role requirement.
    """
    import hmac

    def _checker(request: Request, tenant: dict = Depends(get_tenant)) -> dict:
        from app.core.config import get_settings
        s = get_settings()
        if s.DEV_MODE:
            return tenant
        token = request.headers.get("X-Service-Token")
        if s.SERVICE_AUTH_TOKEN and token and hmac.compare_digest(token, s.SERVICE_AUTH_TOKEN):
            return {**(tenant or {}), "role": "service"}
        caller_level = ROLE_HIERARCHY.get(tenant.get("role", "viewer"), 0)
        required_level = ROLE_HIERARCHY.get(required_role, 99)
        if caller_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Requires a valid X-Service-Token or role '{required_role}'.",
            )
        return tenant

    return _checker


def approver_identity(tenant: dict) -> str:
    """Attributable approver derived from the AUTHENTICATED principal.

    An approval is only worth anything if the ledger can say WHO clicked it, so
    the recorded approver MUST come from the authenticated tenant principal —
    never from a client-supplied field (which is trivially spoofable). Used by
    every HITL decision path so non-repudiation is uniform.
    """
    return (
        tenant.get("email")
        or tenant.get("user_id")
        or tenant.get("name")
        or f"{tenant.get('tenant_id', 'unknown')}:{tenant.get('role', 'unknown')}"
    )


# ── Internal helpers ─────────────────────────────────────────────────────────

def _unauthorized(detail: str) -> Response:
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )
