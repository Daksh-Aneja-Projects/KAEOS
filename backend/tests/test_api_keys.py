"""DB-backed API keys — generation, lookup, and cross-worker revocation.

The old store was a per-process JSON dict, so revocation didn't propagate. These
tests drive the real DB path (owner engine) to prove a generated key resolves and
a revoked key is immediately rejected by a fresh lookup (i.e. any other worker).
"""
import pytest

from app.core import auth as auth_mod
from app.core.database import engine as app_engine
from app.models.api_key import ApiKey



@pytest.fixture(autouse=True)
async def _api_keys_table():
    async with app_engine.begin() as conn:
        await conn.run_sync(ApiKey.__table__.create, checkfirst=True)
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM api_keys"))
    yield
    async with app_engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM api_keys"))


async def test_generate_then_lookup_resolves_tenant():
    issued = await auth_mod.generate_api_key("tenant_x", "ci-key", role="operator")
    assert issued["api_key"].startswith("kt_")

    meta = await auth_mod.get_api_key_by_hash(auth_mod.hash_key(issued["api_key"]))
    assert meta is not None
    assert meta["tenant_id"] == "tenant_x"
    assert meta["role"] == "operator"
    assert meta["active"] is True


async def test_revocation_propagates_via_db():
    issued = await auth_mod.generate_api_key("tenant_x", "revoke-me")
    key_id = issued["key_id"]

    # A "different worker" (fresh lookup) sees it active...
    assert (await auth_mod.get_api_key_by_hash(auth_mod.hash_key(issued["api_key"])))["active"] is True

    # ...revoke, and the very next lookup (any worker) sees it inactive.
    assert await auth_mod.revoke_api_key(key_id) is True
    meta = await auth_mod.get_api_key_by_hash(auth_mod.hash_key(issued["api_key"]))
    assert meta is not None and meta["active"] is False

    # Revoking an unknown prefix is a no-op.
    assert await auth_mod.revoke_api_key("deadbeefdead") is False


async def test_unknown_key_returns_none():
    assert await auth_mod.get_api_key_by_hash(auth_mod.hash_key("kt_nonexistent")) is None


async def test_list_keys_is_tenant_scoped():
    await auth_mod.generate_api_key("tenant_a", "a1", role="operator")
    await auth_mod.generate_api_key("tenant_a", "a2", role="admin")
    await auth_mod.generate_api_key("tenant_b", "b1", role="viewer")

    a_keys = await auth_mod.list_api_keys("tenant_a")
    assert {k["name"] for k in a_keys} == {"a1", "a2"}
    assert all("api_key" not in k for k in a_keys)   # raw key never returned by list

    b_keys = await auth_mod.list_api_keys("tenant_b")
    assert {k["name"] for k in b_keys} == {"b1"}


async def test_scoped_revoke_cannot_touch_another_tenant():
    issued = await auth_mod.generate_api_key("tenant_a", "mine")
    key_id = issued["key_id"]

    # A tenant_b admin cannot revoke tenant_a's key even with the right prefix.
    assert await auth_mod.revoke_api_key(key_id, tenant_id="tenant_b") is False
    assert (await auth_mod.get_api_key_by_hash(auth_mod.hash_key(issued["api_key"])))["active"] is True

    # The owning tenant can.
    assert await auth_mod.revoke_api_key(key_id, tenant_id="tenant_a") is True
    assert (await auth_mod.get_api_key_by_hash(auth_mod.hash_key(issued["api_key"])))["active"] is False
