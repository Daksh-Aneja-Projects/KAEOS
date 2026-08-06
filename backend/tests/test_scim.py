"""SCIM 2.0 user provisioning — create / list / get / patch / delete, tenant-scoped."""
import urllib.parse

import pytest
from fastapi import HTTPException
from fastapi import Response
from starlette.requests import Request

from app.api.routes import scim
from app.models.auth import User
from sqlalchemy import select


T = "tenant_scim"
ADMIN = {"tenant_id": T, "role": "admin", "name": "idp"}


def _req(filter_expr: str | None = None) -> Request:
    qs = f"filter={urllib.parse.quote(filter_expr)}".encode() if filter_expr else b""
    return Request({"type": "http", "method": "GET", "path": "/scim/v2/Users",
                    "query_string": qs, "headers": []})


async def test_create_lists_and_gets_user(db):
    out = await scim.scim_create_user(
        {"userName": "alice@corp.com", "name": {"givenName": "Alice", "familyName": "A"}, "active": True},
        Response(), tenant=ADMIN, db=db)
    assert out["userName"] == "alice@corp.com"
    assert out["active"] is True
    uid = out["id"]

    # Persisted, SSO-only (unusable local password).
    u = (await db.execute(select(User).where(User.id == uid))).scalar_one()
    from app.services.auth import _verify_password
    assert not await _verify_password("", u.hashed_password)

    # List with the userName filter Okta/Azure send.
    lst = await scim.scim_list_users(_req('userName eq "alice@corp.com"'), tenant=ADMIN, db=db)
    assert lst["totalResults"] == 1
    assert lst["Resources"][0]["id"] == uid

    got = await scim.scim_get_user(uid, tenant=ADMIN, db=db)
    assert got["userName"] == "alice@corp.com"


async def test_duplicate_create_conflicts(db):
    await scim.scim_create_user({"userName": "dup@corp.com"}, Response(), tenant=ADMIN, db=db)
    with pytest.raises(HTTPException) as ei:
        await scim.scim_create_user({"userName": "dup@corp.com"}, Response(), tenant=ADMIN, db=db)
    assert ei.value.status_code == 409


async def test_patch_deactivate_and_delete(db):
    out = await scim.scim_create_user({"userName": "bob@corp.com", "active": True},
                                      Response(), tenant=ADMIN, db=db)
    uid = out["id"]

    patched = await scim.scim_patch_user(
        uid, {"schemas": [scim._PATCH_SCHEMA],
              "Operations": [{"op": "replace", "path": "active", "value": False}]},
        tenant=ADMIN, db=db)
    assert patched["active"] is False

    # DELETE is a soft-deactivate.
    await scim.scim_create_user({"userName": "carol@corp.com"}, Response(), tenant=ADMIN, db=db)
    carol = (await db.execute(select(User).where(User.email == "carol@corp.com"))).scalar_one()
    await scim.scim_delete_user(carol.id, tenant=ADMIN, db=db)
    refreshed = (await db.execute(select(User).where(User.id == carol.id))).scalar_one()
    assert refreshed.is_active is False


async def test_scim_is_tenant_scoped(db):
    out = await scim.scim_create_user({"userName": "x@corp.com"}, Response(), tenant=ADMIN, db=db)
    other = {"tenant_id": "tenant_other", "role": "admin", "name": "idp2"}
    with pytest.raises(HTTPException) as ei:
        await scim.scim_get_user(out["id"], tenant=other, db=db)
    assert ei.value.status_code == 404
