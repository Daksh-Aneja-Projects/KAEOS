"""Enterprise SSO / OIDC — real Authorization Code flow.

Covers the parts that don't need a live IdP: stateless signed state (CSRF),
client-secret encryption at rest, real RS256 id_token verification via a JWKS
(with a locally-generated RSA key), JIT user provisioning + session mint, and the
admin config surface (secret never leaked, ADMIN-gated, validation).
"""
import time

import jwt
import pytest

from app.services import sso as sso_svc
from app.models.auth import User
from app.api.routes import sso as sso_routes


T = "tenant_sso"


# ── stateless state (CSRF) ────────────────────────────────────────────────────

def test_state_roundtrip_and_tamper():
    s = sso_svc.sign_state(T, "nonce123", "https://app/cb")
    claims = sso_svc.verify_state(s)
    assert claims["tid"] == T and claims["nonce"] == "nonce123" and claims["rt"] == "https://app/cb"
    with pytest.raises(sso_svc.SSOError):
        sso_svc.verify_state(s + "x")           # tampered
    with pytest.raises(sso_svc.SSOError):
        sso_svc.verify_state("not-a-jwt")


def test_client_secret_encrypted_at_rest():
    token = sso_svc.encrypt_client_secret("super-secret-value")
    assert "super-secret-value" not in token         # ciphertext, not plaintext
    assert sso_svc.decrypt_client_secret(token) == "super-secret-value"
    assert sso_svc.decrypt_client_secret(None) is None


# ── real RS256 id_token verification ──────────────────────────────────────────

def _rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


class _FakeConn:
    client_id = "client-abc"


def _make_id_token(priv, *, iss, aud, nonce, email="alice@corp.com", name="Alice", exp_delta=300):
    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "aud": aud, "sub": "idp-user-1", "email": email, "name": name,
         "nonce": nonce, "iat": now, "exp": now + exp_delta},
        priv, algorithm="RS256",
    )


def _patch_jwks(monkeypatch, pub):
    class _FakeSigningKey:
        key = pub

    class _FakeJWKClient:
        def __init__(self, *a, **k): ...
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey()

    monkeypatch.setattr(sso_svc.jwt, "PyJWKClient", _FakeJWKClient)


def test_verify_id_token_happy_path(monkeypatch):
    priv, pub = _rsa_keypair()
    _patch_jwks(monkeypatch, pub)
    disc = {"issuer": "https://idp.example", "jwks_uri": "https://idp.example/jwks"}
    tok = _make_id_token(priv, iss=disc["issuer"], aud=_FakeConn.client_id, nonce="n1")
    claims = sso_svc.verify_id_token(tok, disc, _FakeConn(), "n1")
    assert claims["email"] == "alice@corp.com"


def test_verify_id_token_nonce_mismatch(monkeypatch):
    priv, pub = _rsa_keypair()
    _patch_jwks(monkeypatch, pub)
    disc = {"issuer": "https://idp.example", "jwks_uri": "https://idp.example/jwks"}
    tok = _make_id_token(priv, iss=disc["issuer"], aud=_FakeConn.client_id, nonce="attacker")
    with pytest.raises(sso_svc.SSOError):
        sso_svc.verify_id_token(tok, disc, _FakeConn(), "expected")


def test_verify_id_token_wrong_audience(monkeypatch):
    priv, pub = _rsa_keypair()
    _patch_jwks(monkeypatch, pub)
    disc = {"issuer": "https://idp.example", "jwks_uri": "https://idp.example/jwks"}
    tok = _make_id_token(priv, iss=disc["issuer"], aud="some-other-client", nonce="n1")
    with pytest.raises(sso_svc.SSOError):
        sso_svc.verify_id_token(tok, disc, _FakeConn(), "n1")


# ── JIT provisioning + session mint ───────────────────────────────────────────

async def test_provision_creates_user_and_mints_session(db):
    from app.services.auth import decode_token
    claims = {"email": "newhire@corp.com", "name": "New Hire"}
    result = await sso_svc.provision_and_login(db, T, claims, "ANALYST")

    assert result["token_type"] == "bearer"
    assert result["user"]["email"] == "newhire@corp.com"
    assert result["user"]["role"] == "ANALYST"
    assert result["user"]["tenant_id"] == T
    # The minted token is a real, decodable KAEOS session.
    payload = decode_token(result["access_token"])
    assert payload and payload["tenant_id"] == T

    # The provisioned account cannot be used for password login (unusable hash).
    from sqlalchemy import select
    user = (await db.execute(select(User).where(User.email == "newhire@corp.com"))).scalar_one()
    from app.services.auth import _verify_password
    assert not await _verify_password("", user.hashed_password)


async def test_provision_reuses_existing_user(db):
    from sqlalchemy import select
    claims = {"email": "repeat@corp.com", "name": "Repeat"}
    await sso_svc.provision_and_login(db, T, claims, "VIEWER")
    await sso_svc.provision_and_login(db, T, claims, "VIEWER")
    rows = (await db.execute(select(User).where(User.email == "repeat@corp.com"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].login_count == 2


async def test_deactivated_user_cannot_sso(db):
    from sqlalchemy import select
    claims = {"email": "gone@corp.com", "name": "Gone"}
    await sso_svc.provision_and_login(db, T, claims, "VIEWER")
    user = (await db.execute(select(User).where(User.email == "gone@corp.com"))).scalar_one()
    user.is_active = False
    await db.commit()
    with pytest.raises(sso_svc.SSOError):
        await sso_svc.provision_and_login(db, T, claims, "VIEWER")


# ── admin config surface ──────────────────────────────────────────────────────

async def test_upsert_connection_encrypts_secret_and_never_leaks_it(db):
    data = sso_routes.SSOConnectionIn(
        protocol="OIDC", provider_label="Okta", issuer="https://okta.example/",
        client_id="cid", client_secret="sh-secret", email_domain="Corp.com",
        default_role="ANALYST",
    )
    out = await sso_routes.upsert_connection(data, user={"role": "ADMIN"}, tenant_id=T, db=db)
    assert out["client_secret_set"] is True
    assert "client_secret" not in out               # secret never serialized
    assert out["issuer"] == "https://okta.example"  # trailing slash trimmed
    assert out["email_domain"] == "corp.com"        # normalized

    # The stored ciphertext decrypts back to the original secret (round-trip).
    from sqlalchemy import select
    from app.models.sso import SSOConnection
    conn = (await db.execute(
        select(SSOConnection).where(SSOConnection.tenant_id == T, SSOConnection.protocol == "OIDC")
    )).scalar_one()
    assert sso_svc.decrypt_client_secret(conn.client_secret_encrypted) == "sh-secret"


async def test_connection_for_email_empty_returns_none():
    # No domain -> no DB touch, returns None (login page falls back to password).
    assert await sso_svc.connection_for_email("") is None


async def test_upsert_update_keeps_secret_when_omitted(db):
    base = sso_routes.SSOConnectionIn(issuer="https://idp/", client_id="c", client_secret="s1")
    await sso_routes.upsert_connection(base, user={"role": "ADMIN"}, tenant_id=T, db=db)
    # Update without a secret must keep the stored one, not wipe it.
    upd = sso_routes.SSOConnectionIn(issuer="https://idp/", client_id="c2", client_secret=None)
    out = await sso_routes.upsert_connection(upd, user={"role": "ADMIN"}, tenant_id=T, db=db)
    assert out["client_secret_set"] is True and out["client_id"] == "c2"


async def test_saml_upsert_requires_idp_fields(db):
    from fastapi import HTTPException
    # Creating a SAML connection without the IdP URL + cert is a 400, not a silent create.
    data = sso_routes.SSOConnectionIn(protocol="SAML", issuer="https://idp.example/entity")
    with pytest.raises(HTTPException) as ei:
        await sso_routes.upsert_connection(data, user={"role": "ADMIN"}, tenant_id=T, db=db)
    assert ei.value.status_code == 400
    assert "idp_sso_url" in ei.value.detail

    # With both present it creates and reports the cert as set (never the cert body).
    ok = sso_routes.SSOConnectionIn(
        protocol="SAML", provider_label="Okta SAML", issuer="https://idp.example/entity",
        idp_sso_url="https://idp.example/sso", idp_x509_cert="MIIBcert...", email_domain="corp.com",
    )
    out = await sso_routes.upsert_connection(ok, user={"role": "ADMIN"}, tenant_id=T, db=db)
    assert out["protocol"] == "SAML"
    assert out["idp_sso_url"] == "https://idp.example/sso"
    assert out["idp_x509_cert_set"] is True
    assert "idp_x509_cert" not in out


# ── domain-ownership challenge (DNS TXT) ──────────────────────────────────────

@pytest.fixture
async def _sso_table():
    from app.core.database import engine as app_engine
    from app.models.sso import SSOConnection
    from sqlalchemy import text
    async with app_engine.begin() as conn:
        await conn.run_sync(SSOConnection.__table__.create, checkfirst=True)
        await conn.execute(text("DELETE FROM sso_connections"))
    yield
    async with app_engine.begin() as conn:
        await conn.execute(text("DELETE FROM sso_connections"))


async def _add_conn(tenant, domain, *, verified=False, token="tok"):
    from app.core.database import MaintenanceSessionLocal
    from app.models.sso import SSOConnection
    async with MaintenanceSessionLocal() as db:
        c = SSOConnection(tenant_id=tenant, protocol="OIDC", issuer="https://idp",
                          email_domain=domain, domain_verified=verified,
                          domain_verification_token=token, is_enabled=True)
        db.add(c)
        await db.commit()
        return c.id


async def test_unverified_domain_does_not_route_logins(_sso_table):
    await _add_conn("tenant_a", "victim.com", verified=False)
    # An unverified (possibly squatted) domain claim must not send anyone's users to it.
    assert await sso_svc.connection_for_email("bob@victim.com") is None


async def test_domain_verification_via_dns_txt(_sso_table, monkeypatch):
    cid = await _add_conn("tenant_a", "acme.com", verified=False, token="abc123")
    monkeypatch.setattr(sso_svc, "_resolve_txt", lambda name: [])
    r = await sso_svc.verify_domain(cid, "tenant_a")
    assert r["verified"] is False and r["error"] == "txt_record_not_found"
    assert await sso_svc.connection_for_email("x@acme.com") is None

    monkeypatch.setattr(sso_svc, "_resolve_txt",
                        lambda name: ["kaeos-domain-verification=abc123"])
    r = await sso_svc.verify_domain(cid, "tenant_a")
    assert r["verified"] is True
    routed = await sso_svc.connection_for_email("x@acme.com")
    assert routed is not None and routed.tenant_id == "tenant_a"


async def test_verified_domain_cannot_be_taken_over(_sso_table, monkeypatch):
    await _add_conn("tenant_a", "shared.com", verified=True, token="a")
    b = await _add_conn("tenant_b", "shared.com", verified=False, token="b")
    monkeypatch.setattr(sso_svc, "_resolve_txt",
                        lambda name: ["kaeos-domain-verification=b"])
    r = await sso_svc.verify_domain(b, "tenant_b")
    assert r["verified"] is False and r["error"] == "domain_claimed_by_another_tenant"
    # Discovery resolves to the original owner and does NOT 500 on the duplicate.
    routed = await sso_svc.connection_for_email("u@shared.com")
    assert routed is not None and routed.tenant_id == "tenant_a"


def test_safe_return_to_blocks_open_redirect():
    """Regression for the CRITICAL: the session token is handed back in the
    redirect, so return_to must never be an attacker host."""
    from app.api.routes.sso import _safe_return_to
    assert _safe_return_to("/app/callback") == "/app/callback"   # site-relative ok
    assert _safe_return_to("https://evil.example/steal") == "/"  # external host refused
    assert _safe_return_to("//evil.example") == "/"              # protocol-relative refused
    assert _safe_return_to("javascript:alert(1)") == "/"         # non-http scheme refused
    assert _safe_return_to(None) == "/"
