"""
KAEOS E2E Test 13 — Authentication & RBAC
Tests the full auth flow: login with the configured admin credentials, JWT
issuance, /auth/me profile retrieval, admin user management, and rejection paths.
"""
import pytest

from .conftest import admin_email, admin_password


@pytest.mark.asyncio
class TestAuthRBAC:
    """Authentication — login, JWT, user management, RBAC enforcement."""

    _token = None

    async def _login(self, client):
        """Login once and cache the JWT for the class."""
        if TestAuthRBAC._token:
            return TestAuthRBAC._token
        if not admin_password():
            pytest.skip("ADMIN_PASSWORD not set — cannot exercise auth flow")
        r = await client.post("/auth/login", json={
            "email": admin_email(), "password": admin_password(),
        })
        assert r.status_code == 200, f"Login failed → {r.status_code}: {r.text[:200]}"
        data = r.json()
        token = data.get("token") or data.get("access_token")
        assert token, f"Login response missing token. Keys: {list(data.keys())}"
        TestAuthRBAC._token = token
        return token

    async def test_login_demo_user(self, client):
        """Demo admin user can log in and receives a JWT."""
        token = await self._login(client)
        assert isinstance(token, str) and len(token) > 20

    async def test_login_wrong_password_rejected(self, client):
        """Wrong password is rejected with 401."""
        r = await client.post("/auth/login", json={
            "email": admin_email(), "password": "not-the-password",
        })
        assert r.status_code == 401

    async def test_login_missing_fields_rejected(self, client):
        """Missing email/password is rejected with 400."""
        r = await client.post("/auth/login", json={"email": "", "password": ""})
        assert r.status_code == 400

    async def test_me_with_token(self, client):
        """/auth/me returns the authenticated user's profile."""
        token = await self._login(client)
        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        user = r.json()
        assert user.get("email") == admin_email()
        assert user.get("role") == "ADMIN"
        assert user.get("tenant_id") == "tenant_acme"

    async def test_me_without_token_rejected(self, client):
        """/auth/me without a token returns 401."""
        r = await client.get("/auth/me")
        assert r.status_code == 401

    async def test_me_with_garbage_token_rejected(self, client):
        """/auth/me with an invalid token returns 401."""
        r = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert r.status_code == 401

    async def test_list_users_as_admin(self, client):
        """Admin can list users in the tenant."""
        token = await self._login(client)
        r = await client.get("/auth/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        users = r.json()
        users = users.get("users", users) if isinstance(users, dict) else users
        assert isinstance(users, list)
        assert len(users) >= 1, "Expected at least the demo user"

    async def test_create_and_deactivate_user(self, client):
        """Admin can create a user, change their role, then deactivate them."""
        token = await self._login(client)
        headers = {"Authorization": f"Bearer {token}"}

        r = await client.post("/auth/users", headers=headers, json={
            "email": "e2e.viewer@kaeos.ai",
            "display_name": "E2E Viewer",
            "password": "e2e-test-pass-123",
            "role": "VIEWER",
        })
        # 400 = already exists from a previous run — fetch the id from the list
        assert r.status_code in (200, 400), f"{r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            user_id = r.json().get("id") or r.json().get("user", {}).get("id")
        else:
            users = (await client.get("/auth/users", headers=headers)).json()
            users = users.get("users", users) if isinstance(users, dict) else users
            match = [u for u in users if u.get("email") == "e2e.viewer@kaeos.ai"]
            if not match:
                pytest.skip("Could not create or find e2e test user")
            user_id = match[0]["id"]

        assert user_id, "No user id resolved"

        # Promote to ANALYST
        r2 = await client.put(f"/auth/users/{user_id}/role", headers=headers,
                              json={"role": "ANALYST"})
        assert r2.status_code == 200

        # Deactivate
        r3 = await client.delete(f"/auth/users/{user_id}", headers=headers)
        assert r3.status_code == 200

    async def test_saml_sso_not_implemented(self, client):
        """SAML SSO explicitly returns 501 (documented as not in v1)."""
        r = await client.post("/auth/sso/saml", json={})
        assert r.status_code == 501

    async def test_jwt_works_for_tenant_scoped_api(self, client):
        """A JWT from login is accepted by TenantMiddleware on business routes."""
        token = await self._login(client)
        r = await client.get("/rules", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["total"] > 0
