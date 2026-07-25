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

from fastapi.routing import APIRoute

from app.main import app

# Reviewed exceptions. Each entry is intentionally NOT role-gated, with a reason.
_ALLOWLIST = {
    # Public authentication endpoints (must be reachable without a session).
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/accept-invite",   # invitee sets their own password (magic-link)
    "/api/v1/auth/sso/saml",
    # Viewer-level self-actions (marking one's own items read — no privilege).
    "/api/v1/agents/activity-feed/mark-read",
    "/api/v1/org/notifications/read",
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


def _is_protected(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
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
    return [
        r for r in app.routes
        if isinstance(r, APIRoute) and (r.methods - _SAFE_METHODS)
    ]


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
