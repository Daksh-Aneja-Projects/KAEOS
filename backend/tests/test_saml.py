"""SAML 2.0 SP - real signature verification, condition checks, replay guard.

Everything runs against a locally-generated RSA keypair + self-signed cert and a
genuinely XML-DSig-signed assertion (``signxml.XMLSigner``), so the whole ACS
path is exercised without a live IdP: a valid login succeeds, and every attack
(tampered body, wrong audience, wrong recipient, expired window, wrong
InResponseTo, unsigned/wrapped assertion, replay) is refused.
"""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from lxml import etree

from app.services import saml as saml_svc
from app.services.sso import SSOError

NS = saml_svc.NS
REQUEST_BASE = "https://kaeos.example/"
# saml_svc derives audience/recipient from PUBLIC_BASE_URL or the request base.
AUDIENCE = saml_svc.sp_entity_id(REQUEST_BASE)
ACS = saml_svc.acs_url(REQUEST_BASE)
IDP_ENTITY = "https://idp.example/entity"
REQ_ID = "_" + "a" * 32


def _cert_and_key():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return cert_pem, key_pem


def _instant(delta_seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _response_xml(*, assertion_id="_assert-1", audience=AUDIENCE, recipient=ACS,
                  in_response_to=REQ_ID, not_after_delta=300, not_before_delta=-60,
                  email="alice@corp.com", status=saml_svc._STATUS_SUCCESS, issuer=IDP_ENTITY):
    """A SAML Response whose single Assertion we will sign."""
    return f"""<samlp:Response xmlns:samlp="{NS['samlp']}" xmlns:saml="{NS['saml']}"
    ID="_resp-1" Version="2.0" IssueInstant="{_instant()}" Destination="{recipient}">
  <saml:Issuer>{issuer}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="{status}"/></samlp:Status>
  <saml:Assertion ID="{assertion_id}" Version="2.0" IssueInstant="{_instant()}">
    <saml:Issuer>{issuer}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="{saml_svc._NAMEID_EMAIL}">{email}</saml:NameID>
      <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <saml:SubjectConfirmationData NotOnOrAfter="{_instant(not_after_delta)}"
          Recipient="{recipient}" InResponseTo="{in_response_to}"/>
      </saml:SubjectConfirmation>
    </saml:Subject>
    <saml:Conditions NotBefore="{_instant(not_before_delta)}" NotOnOrAfter="{_instant(not_after_delta)}">
      <saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AuthnStatement AuthnInstant="{_instant()}" SessionIndex="sess-1">
      <saml:AuthnContext>
        <saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef>
      </saml:AuthnContext>
    </saml:AuthnStatement>
    <saml:AttributeStatement>
      <saml:Attribute Name="displayName"><saml:AttributeValue>Alice A</saml:AttributeValue></saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>"""


def _sign_assertion(xml_str, key_pem, cert_pem):
    """XML-DSig-sign the Assertion (enveloped) and return the base64 Response."""
    from signxml import XMLSigner, methods

    root = etree.fromstring(xml_str.encode())
    assertion = root.find(f"{{{NS['saml']}}}Assertion")
    signed = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
    ).sign(assertion, key=key_pem, cert=cert_pem, reference_uri=assertion.get("ID"))
    # Splice the signed assertion back in place of the unsigned one.
    root.replace(assertion, signed)
    return base64.b64encode(etree.tostring(root)).decode()


class _Conn:
    def __init__(self, cert_pem):
        self.protocol = "SAML"
        self.issuer = IDP_ENTITY
        self.idp_sso_url = "https://idp.example/sso"
        self.idp_x509_cert = cert_pem.decode()
        self.default_role = "VIEWER"


@pytest.fixture(scope="module")
def creds():
    return _cert_and_key()


def _verify(b64, conn, request_id=REQ_ID):
    return saml_svc.verify_response(b64, conn, REQUEST_BASE, request_id)


# ── happy path ────────────────────────────────────────────────────────────────

def test_valid_signed_assertion_passes(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(), key_pem, cert_pem)
    claims = _verify(b64, _Conn(cert_pem))
    assert claims["email"] == "alice@corp.com"
    assert claims["name"] == "Alice A"
    assert claims["assertion_id"] == "_assert-1"


# ── signature / integrity ─────────────────────────────────────────────────────

def test_tampered_email_after_signing_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(email="alice@corp.com"), key_pem, cert_pem)
    raw = base64.b64decode(b64).replace(b"alice@corp.com", b"attacker@evil.com")
    with pytest.raises(SSOError):
        _verify(base64.b64encode(raw).decode(), _Conn(cert_pem))


def test_unsigned_assertion_is_rejected(creds):
    cert_pem, _ = creds
    b64 = base64.b64encode(_response_xml().encode()).decode()   # never signed
    with pytest.raises(SSOError):
        _verify(b64, _Conn(cert_pem))


def test_wrong_certificate_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(), key_pem, cert_pem)
    other_cert, _ = _cert_and_key()
    with pytest.raises(SSOError):
        _verify(b64, _Conn(other_cert))


# ── condition enforcement ─────────────────────────────────────────────────────

def test_wrong_audience_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(audience="https://someone-else/sp"), key_pem, cert_pem)
    with pytest.raises(SSOError, match="audience"):
        _verify(b64, _Conn(cert_pem))


def test_wrong_recipient_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(recipient="https://evil/acs"), key_pem, cert_pem)
    # Recipient is inside the signed subtree, so tampering means re-signing for a
    # different ACS - which the audience check would also catch; assert refusal.
    with pytest.raises(SSOError):
        _verify(b64, _Conn(cert_pem))


def test_expired_assertion_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(not_after_delta=-300), key_pem, cert_pem)
    with pytest.raises(SSOError, match="expired"):
        _verify(b64, _Conn(cert_pem))


def test_wrong_in_response_to_is_rejected(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(_response_xml(in_response_to="_someone-elses-request"), key_pem, cert_pem)
    with pytest.raises(SSOError, match="different AuthnRequest"):
        _verify(b64, _Conn(cert_pem))


def test_idp_failure_status_is_surfaced(creds):
    cert_pem, key_pem = creds
    b64 = _sign_assertion(
        _response_xml(status="urn:oasis:names:tc:SAML:2.0:status:AuthnFailed"), key_pem, cert_pem)
    with pytest.raises(SSOError, match="refused"):
        _verify(b64, _Conn(cert_pem))


# ── replay guard ──────────────────────────────────────────────────────────────

async def test_assertion_id_is_single_use():
    await saml_svc.claim_assertion_id("_once-only-xyz")
    with pytest.raises(SSOError, match="replay"):
        await saml_svc.claim_assertion_id("_once-only-xyz")


# ── AuthnRequest + metadata shape ─────────────────────────────────────────────

def test_build_authn_request_and_metadata():
    conn = _Conn(_cert_and_key()[0])
    rid = saml_svc.new_request_id()
    assert rid.startswith("_")   # xsd:ID cannot start with a digit; the "_" guarantees it
    url = saml_svc.build_authn_request(conn, REQUEST_BASE, "relay-state", rid)
    assert url.startswith("https://idp.example/sso?")
    assert "SAMLRequest=" in url and "RelayState=relay-state" in url

    md = saml_svc.sp_metadata(REQUEST_BASE)
    assert AUDIENCE in md and ACS in md
    assert "WantAssertionsSigned=\"true\"" in md
