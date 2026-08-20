"""Every mutating route carries a server-side gate. Ratchet, not a snapshot.

An OpenAPI diff CANNOT see this: dependencies are not part of the schema, so a
router refactor can drop `Depends(require_role(...))` while the published
surface stays byte-identical. M2.1 moved 78 HR routes into 18 sub-routers on
exactly that evidence, which is the kind of change this test exists to backstop.

Found during the pre-launch audit; the HR split passed it (0 ungated HR mutating
routes), and every route in the allowlist below was read individually and has an
authenticator that is not a role dependency.
"""
import pytest

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: Dependency callables that constitute a gate.
GATE_NAMES = (
    "require_role", "require_superadmin", "require_service_or_role",
    "require_department", "require_entitlement", "require_execution_allowance",
    "verify_admin_secret", "admin_secret",
)

#: The second signal: require_role() returns a closure, and the required role
#: rides in one of its cells. Hoisted so the positive control below can blind
#: BOTH signals - neutering only one leaves the detector fully working.
GATE_ROLES = ("viewer", "operator", "admin")

#: Mutating routes with NO role dependency, each authenticated another way.
#: Adding a line here is a deliberate security decision - say which authenticator
#: replaces the role check, or do not add it.
ALLOWED_WITHOUT_ROLE = {
    # Public by necessity: you cannot hold a session before you have one.
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/logout",
    # Authenticated by a single-use invite token in the body.
    "POST /api/v1/auth/accept-invite",
    # Authenticated by the signed SAML assertion itself.
    "POST /api/v1/auth/sso/saml/acs",
    # Depends(get_current_user) and act only on the CALLER'S own account;
    # /mfa/disable additionally re-authenticates (fresh TOTP or password).
    "POST /api/v1/auth/mfa/enroll",
    "POST /api/v1/auth/mfa/confirm",
    "POST /api/v1/auth/mfa/disable",
    # HMAC over the raw body (X-Kaeos-Signature); a webhook carries no JWT.
    "POST /api/v1/integrations/ingest/{connector_id}",
    "POST /api/v1/integrations/ingest/{connector_id}/security",
    # Stripe signature over the raw body; the tenant is resolved from OUR records
    # by stripe_customer_id, never from the payload.
    "POST /api/v1/billing/webhook",
    # verify_admin_secret(x_admin_secret) called in the handler body (the header
    # is a plain parameter, so it is not visible in the dependency tree).
    "POST /api/v1/infrastructure/onboarding/{tenant_id}/bootstrap-admin",
    "POST /admin/security/api-keys",
    "DELETE /admin/security/api-keys/{key_prefix}",
    # Authenticated + tenant-scoped, and the write only ever touches the caller's
    # own tenant rows. Marking your own notifications read is a viewer action.
    "POST /api/v1/agents/activity-feed/mark-read",
    "POST /api/v1/org/notifications/read",
    # Tenant-scoped compute: POST carries a body, but nothing is persisted for
    # another tenant. Same class as the simulation endpoints.
    "POST /api/v1/skills/{skill_id}/explain",
    "POST /api/v1/compliance/check",
    "POST /api/v1/chat/stream",
}


def _is_gated(route) -> bool:
    dep = getattr(route, "dependant", None)
    if dep is None:
        return False
    seen, stack = set(), [dep]
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        call = getattr(d, "call", None)
        names = (getattr(call, "__name__", "") or "") + "|" + (getattr(call, "__qualname__", "") or "")
        if any(g in names for g in GATE_NAMES):
            return True
        # require_role returns a closure; the required role rides in a cell.
        for cell in getattr(call, "__closure__", None) or ():
            try:
                val = cell.cell_contents
            except ValueError:
                continue
            if isinstance(val, str) and val in GATE_ROLES:
                return True
        stack.extend(getattr(d, "dependencies", []) or [])
    return False


def _ungated() -> set[str]:
    from app.main import app
    out = set()
    for route in app.routes:
        for method in (getattr(route, "methods", None) or set()) & MUTATING:
            if not _is_gated(route):
                out.add(f"{method} {getattr(route, 'path', '')}")
    return out


def test_no_mutating_route_is_left_without_a_gate():
    new = sorted(_ungated() - ALLOWED_WITHOUT_ROLE)
    assert not new, (
        "These mutating endpoints have no role/admin gate and are not in the "
        "reviewed allowlist. Add the gate, or add the route to "
        "ALLOWED_WITHOUT_ROLE with the authenticator that replaces it:\n  "
        + "\n  ".join(new))


def test_the_allowlist_does_not_rot():
    """Every exemption must still name a real, currently-ungated route.

    A stale entry silently pre-authorizes a path that may come back gated -
    or worse, one that was renamed and re-added without a gate."""
    stale = sorted(ALLOWED_WITHOUT_ROLE - _ungated())
    assert not stale, (
        "These allowlist entries no longer match an ungated route (renamed, "
        "removed, or now gated) - drop them:\n  " + "\n  ".join(stale))


def test_the_gate_detector_actually_detects(monkeypatch):
    """Positive control: the check must fail when a gate really is missing.

    Without this, a detector that silently matched everything would make the
    two tests above pass forever while proving nothing."""
    import tests.test_authz_coverage as mod
    before = len(_ungated())
    monkeypatch.setattr(mod, "GATE_NAMES", ("a-name-no-dependency-has",))
    monkeypatch.setattr(mod, "GATE_ROLES", ("a-role-nobody-requires",))
    blinded = len(_ungated())
    # Blinded, nearly every mutating route must look ungated; sighted, only the
    # reviewed handful does. A detector that cannot tell the two apart proves
    # nothing when it reports zero.
    assert blinded > before + 200, (
        f"detector is not actually reading dependencies: {before} ungated "
        f"sighted vs {blinded} blinded")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
