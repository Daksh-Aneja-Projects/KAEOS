"""
Phase 2A — router-level default-deny enforcement.

Every state-changing route (POST/PUT/PATCH/DELETE) must be protected by an
authorization gate — either ``require_role(...)`` or the out-of-band
``verify_admin_secret`` (ADMIN_SECRET header). The only exceptions are an
explicit, reviewed allowlist of routes that are intentionally public, viewer-
level self-actions, or internal service/agent-mesh calls.

This test fails if a NEW ungated mutation appears, forcing every mutation to be a
conscious authorization decision (default-deny) rather than accidentally open.
"""
import inspect

import pytest

from app.main import app
from tests.route_introspection import mutating_routes

# Reviewed exceptions. Each entry is intentionally NOT role-gated, with a reason.
_ALLOWLIST = {
    # Public authentication endpoints (must be reachable without a session).
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/accept-invite",   # invitee sets their own password (magic-link)
    "/api/v1/auth/sso/saml",
    # Realtime sync + security-event ingest: external systems (Workday,
    # Salesforce, SIEM relays) cannot hold KAEOS JWTs, so these are public BY
    # DESIGN and authenticated by an HMAC-SHA256 signature over the raw body
    # with the connector's webhook secret (see app/services/sync_engine.py:
    # verify_signature; bad/missing signature -> 401; unguessable connector id
    # alone grants nothing). Covered by tests/test_sync_engine.py and
    # tests/test_security_response.py.
    "/api/v1/integrations/ingest/{connector_id}",
    "/api/v1/integrations/ingest/{connector_id}/security",
    # Viewer-level self-actions (marking one's own items read — no privilege).
    "/api/v1/agents/activity-feed/mark-read",
    "/api/v1/org/notifications/read",
    # MFA self-service: a user manages their OWN second factor. Gated by
    # get_current_user (identity), not a role — enrolling/disabling your own 2FA
    # needs no elevated privilege.
    "/api/v1/auth/mfa/enroll",
    "/api/v1/auth/mfa/confirm",
    "/api/v1/auth/mfa/disable",
    # Read-like: explains an existing skill, produces no state change.
    "/api/v1/skills/{skill_id}/explain",
    # Conversational Q&A copilot — read-only, answers questions, never mutates
    # state; must be reachable by every authenticated user (incl. viewers).
    "/api/v1/chat/stream",
    # NOTE: the agent-mesh / cost / model-routing mutations
    # (/infrastructure/agents/*, /cost/check|record, /models/route,
    # /schema-mappings/propose) are NO LONGER exempted — they are now gated by
    # require_service_or_role("operator") (service token OR operator role), so the
    # generic detector below recognizes them and they need no allowlist entry.
}

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_protected(route) -> bool:
    # Router-level gates: include_router(..., dependencies=[Depends(require_role(...))]).
    for dep in route.router_dependencies:
        call = getattr(dep, "dependency", dep)
        qn = getattr(call, "__qualname__", "") or ""
        if "require_role" in qn or "require_service_or_role" in qn:
            return True

    stack = list(getattr(route.dependant, "dependencies", []) or [])
    seen = 0
    while stack:
        dep = stack.pop()
        seen += 1
        if seen > 500:
            break
        qn = getattr(getattr(dep, "call", None), "__qualname__", "") or ""
        if "require_role" in qn or "require_service_or_role" in qn:
            return True
        stack.extend(dep.dependencies)
    try:
        if "verify_admin_secret" in inspect.getsource(route.endpoint):
            return True
    except (OSError, TypeError):
        pass
    return False


def _mutating_routes():
    return mutating_routes(app, safe_methods=_SAFE_METHODS)


def test_route_enumeration_is_not_vacuous():
    """Guard the guard: if the walker stops finding routes, this lint passes
    vacuously and every ungated mutation sails through. FastAPI changed its
    include_router layout once already (flat APIRoute -> _IncludedRouter); this
    fails loudly if that happens again instead of silently losing coverage."""
    routes = _mutating_routes()
    assert len(routes) > 200, (
        f"only {len(routes)} mutating routes discovered — the route walker in "
        "tests/route_introspection.py is likely blind to a new FastAPI/Starlette "
        "routing layout. Fix the walker; do NOT lower this threshold."
    )


def test_no_ungated_mutation_outside_allowlist():
    unprotected = sorted({
        r.path for r in _mutating_routes() if not _is_protected(r)
    })
    leaked = [p for p in unprotected if p not in _ALLOWLIST]
    assert not leaked, (
        "Ungated state-changing route(s) found outside the reviewed allowlist "
        f"(default-deny violation): {leaked}. Add require_role(...) to the route, "
        "or, if it is intentionally public/viewer/internal, add it to _ALLOWLIST "
        "in this test with a documented reason."
    )


@pytest.mark.parametrize("path", [
    "/api/v1/reality/shock",
    "/api/v1/reality/simulate",
    "/api/v1/extraction/detect-conflict",
    "/api/v1/predictive/discover-patterns",
    "/api/v1/intelligence/proactive-alert",
    "/api/v1/intelligence/correlate",
    "/api/v1/simulation/what-if",
])
def test_sensitive_mutations_are_gated(path):
    routes = [r for r in _mutating_routes() if r.path == path]
    assert routes, f"expected a mutating route at {path}"
    assert all(_is_protected(r) for r in routes), f"{path} must be role-gated"
