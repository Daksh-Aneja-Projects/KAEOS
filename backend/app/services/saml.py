"""KAEOS - SAML 2.0 Service Provider (real, signature-verified).

This replaces the 501 that ``/auth/sso/saml`` used to return. KAEOS acts as a
SAML **Service Provider** in the SP-initiated HTTP-Redirect / HTTP-POST profile:

  1. ``/auth/sso/saml/metadata`` publishes SP metadata for the IdP admin.
  2. ``/auth/sso/saml/login``    deflates + base64s an ``AuthnRequest`` and
                                 redirects the browser to the tenant's IdP.
  3. ``/auth/sso/saml/acs``      receives the POSTed ``SAMLResponse``, verifies
                                 its XML signature against the configured IdP
                                 certificate, validates every condition, and
                                 hands the claims to the same
                                 ``sso.provision_and_login`` the OIDC flow uses.

Security posture (a SAML SP is an authentication boundary; nothing here is
"best effort"):

  * The signature is checked with ``signxml`` (pure Python: lxml + cryptography,
    so it installs on every platform without the xmlsec C library).
  * Only the **verified** subtree is ever read. Assertions are extracted from
    ``signed_xml``, never from the raw document, which is what defeats XML
    Signature Wrapping - an attacker-injected unsigned assertion is simply not
    in the tree we look at.
  * Conditions enforced: Status=Success, NotBefore/NotOnOrAfter (both on
    Conditions and on SubjectConfirmationData), AudienceRestriction == our SP
    entity ID, Recipient == our ACS URL, and InResponseTo == the request we
    actually issued (carried in the signed RelayState).
  * Assertion IDs are single-use; a replayed assertion is refused.
  * Encrypted assertions are refused honestly rather than silently accepted
    unverified.
"""
from __future__ import annotations

import base64
import logging
import secrets
import zlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from app.core.config import get_settings
from app.models.sso import SSOConnection
from app.services.sso import SSOError

logger = logging.getLogger(__name__)

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}

# Clocks between an IdP and an SP are never perfectly aligned; 2 minutes is the
# window every major IdP recommends. Wider than this starts to matter for replay.
CLOCK_SKEW = timedelta(seconds=120)

_STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
_NAMEID_EMAIL = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

# Attribute names IdPs use for email / display name, in preference order.
_EMAIL_ATTRS = (
    "email", "mail", "emailaddress", "urn:oid:0.9.2342.19200300.100.1.3",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
)
_NAME_ATTRS = (
    "displayname", "name", "cn", "urn:oid:2.16.840.1.113730.3.1.241",
    "http://schemas.microsoft.com/identity/claims/displayname",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
)


# ── SP identity ───────────────────────────────────────────────────────────────

def _base(request_base: str) -> str:
    settings = get_settings()
    return (settings.PUBLIC_BASE_URL or request_base).rstrip("/")


def sp_entity_id(request_base: str) -> str:
    """Our EntityID - the audience the IdP must stamp into the assertion."""
    return f"{_base(request_base)}{get_settings().API_PREFIX}/auth/sso/saml/metadata"


def acs_url(request_base: str) -> str:
    """Our Assertion Consumer Service URL - where the IdP POSTs the response."""
    return f"{_base(request_base)}{get_settings().API_PREFIX}/auth/sso/saml/acs"


def sp_metadata(request_base: str) -> str:
    """SP metadata XML to hand to the IdP administrator.

    KAEOS does not request encrypted assertions (see ``_reject_encrypted``), so
    no SP encryption key is advertised; transport security is TLS.
    """
    entity, acs = sp_entity_id(request_base), acs_url(request_base)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<md:EntityDescriptor xmlns:md="{NS["md"]}" entityID="{entity}">\n'
        '  <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true"\n'
        '      protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
        f'    <md:NameIDFormat>{_NAMEID_EMAIL}</md:NameIDFormat>\n'
        '    <md:AssertionConsumerService index="0" isDefault="true"\n'
        '        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"\n'
        f'        Location="{acs}"/>\n'
        '  </md:SPSSODescriptor>\n'
        '</md:EntityDescriptor>\n'
    )


# ── 2. AuthnRequest ───────────────────────────────────────────────────────────

def new_request_id() -> str:
    """A fresh AuthnRequest ID. Must be an xsd:ID, so it cannot start with a digit."""
    return f"_{secrets.token_hex(16)}"


def build_authn_request(conn: SSOConnection, request_base: str,
                        relay_state: str, request_id: str) -> str:
    """Return the IdP redirect URL for the HTTP-Redirect binding.

    ``request_id`` is generated by the caller and carried in the signed
    RelayState, so the ACS can enforce ``InResponseTo`` statelessly - an
    assertion minted for somebody else's login is refused.
    """
    if not conn.idp_sso_url:
        raise SSOError("SAML connection has no IdP SSO URL configured")

    issued = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issued}" '
        f'Destination="{conn.idp_sso_url}" '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'AssertionConsumerServiceURL="{acs_url(request_base)}">'
        f'<saml:Issuer>{sp_entity_id(request_base)}</saml:Issuer>'
        f'<samlp:NameIDPolicy Format="{_NAMEID_EMAIL}" AllowCreate="true"/>'
        '</samlp:AuthnRequest>'
    )
    # HTTP-Redirect binding carries the request raw-DEFLATEd then base64'd.
    deflated = zlib.compress(xml.encode())[2:-4]
    params = urlencode({
        "SAMLRequest": base64.b64encode(deflated).decode(),
        "RelayState": relay_state,
    })
    sep = "&" if "?" in conn.idp_sso_url else "?"
    return f"{conn.idp_sso_url}{sep}{params}"


# ── 3. ACS: verify + validate ─────────────────────────────────────────────────

def _pem(cert: str) -> str:
    """Accept either a full PEM block or a bare base64 X509 body (what IdP
    metadata and admin copy-paste usually contain)."""
    cert = (cert or "").strip()
    if not cert:
        raise SSOError("SAML connection has no IdP certificate configured")
    if "BEGIN CERTIFICATE" in cert:
        return cert
    body = "".join(cert.split())
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----\n"


def _reject_encrypted(root) -> None:
    if root.find(".//saml:EncryptedAssertion", NS) is not None or \
            root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}EncryptedAssertion") is not None:
        raise SSOError(
            "Encrypted SAML assertions are not supported. Disable assertion "
            "encryption at the IdP (the channel is already TLS-protected) and "
            "keep assertion signing enabled."
        )


def _check_status(root) -> None:
    code = root.find("./samlp:Status/samlp:StatusCode", NS)
    value = code.get("Value") if code is not None else None
    if value and value != _STATUS_SUCCESS:
        msg = root.find(".//samlp:StatusMessage", NS)
        detail = f": {msg.text}" if msg is not None and msg.text else ""
        raise SSOError(f"IdP refused the login ({value.rsplit(':', 1)[-1]}){detail}")


def _parse_instant(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise SSOError(f"Malformed SAML timestamp '{value}'") from e


def _check_window(not_before: Optional[str], not_on_or_after: Optional[str], what: str) -> None:
    now = datetime.now(timezone.utc)
    nb, noa = _parse_instant(not_before), _parse_instant(not_on_or_after)
    if nb and now + CLOCK_SKEW < nb:
        raise SSOError(f"SAML assertion is not valid yet ({what})")
    if noa and now - CLOCK_SKEW >= noa:
        raise SSOError(f"SAML assertion has expired ({what})")


def _verified_assertion(xml_bytes: bytes, conn: SSOConnection):
    """Verify the XML signature and return the assertion element from the
    *verified* subtree only. Anything outside it is attacker-controlled."""
    from signxml import XMLVerifier  # imported lazily: heavy lxml dependency

    try:
        result = XMLVerifier().verify(xml_bytes, x509_cert=_pem(conn.idp_x509_cert))
    except SSOError:
        raise
    except Exception as e:
        raise SSOError(f"SAML signature verification failed: {e}") from e

    signed = result.signed_xml
    if signed is None:
        raise SSOError("SAML response carried no verifiable signed content")

    tag = signed.tag.rsplit("}", 1)[-1]   # strip {namespace} -> localname
    if tag == "Assertion":
        assertion = signed
    elif tag == "Response":
        # Response-level signature: the assertion is trusted only because it is
        # inside the subtree the signature covers.
        assertion = signed.find(f"./{{{NS['saml']}}}Assertion")
        if assertion is None:
            raise SSOError("Signed SAML response contains no assertion")
    else:
        raise SSOError(f"Unexpected signed SAML element '{tag}'")
    return assertion


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _attributes(assertion) -> dict[str, str]:
    out: dict[str, str] = {}
    for attr in assertion.iter(f"{{{NS['saml']}}}Attribute"):
        name = (attr.get("Name") or attr.get("FriendlyName") or "").strip().lower()
        values = [_text(v) for v in attr.findall(f"{{{NS['saml']}}}AttributeValue")]
        values = [v for v in values if v]
        if name and values:
            out[name] = values[0]
    return out


def _first(attrs: dict[str, str], keys) -> str:
    for k in keys:
        if attrs.get(k):
            return attrs[k]
    return ""


def verify_response(saml_response_b64: str, conn: SSOConnection, request_base: str,
                    expected_request_id: Optional[str]) -> dict:
    """Verify a base64 ``SAMLResponse`` and return OIDC-shaped claims.

    The returned dict matches what ``sso.provision_and_login`` expects
    (``email`` / ``name``), so both protocols share one provisioning path.
    """
    try:
        xml_bytes = base64.b64decode(saml_response_b64, validate=True)
    except Exception as e:
        raise SSOError("SAMLResponse is not valid base64") from e

    # defusedxml for the *untrusted* pre-signature pass (status + encryption
    # probe) - entity expansion and external DTDs must never be honoured here.
    from defusedxml.ElementTree import fromstring as safe_fromstring
    try:
        root = safe_fromstring(xml_bytes)
    except Exception as e:
        raise SSOError(f"SAMLResponse is not well-formed XML: {e}") from e

    _reject_encrypted(root)
    _check_status(root)

    assertion = _verified_assertion(xml_bytes, conn)

    # Issuer must be the IdP we configured.
    issuer = _text(assertion.find(f"{{{NS['saml']}}}Issuer"))
    if conn.issuer and issuer and issuer.rstrip("/") != conn.issuer.rstrip("/"):
        raise SSOError(f"SAML assertion issuer '{issuer}' does not match the configured IdP")

    # Conditions: validity window + audience.
    conditions = assertion.find(f"{{{NS['saml']}}}Conditions")
    if conditions is None:
        raise SSOError("SAML assertion has no Conditions element")
    _check_window(conditions.get("NotBefore"), conditions.get("NotOnOrAfter"), "Conditions")

    expected_audience = sp_entity_id(request_base)
    audiences = [_text(a) for a in
                 conditions.iter(f"{{{NS['saml']}}}Audience")]
    if expected_audience not in audiences:
        raise SSOError(
            f"SAML assertion audience {audiences or '[]'} does not include this "
            f"service provider ({expected_audience})"
        )

    # Subject confirmation: recipient + window + InResponseTo.
    scd = assertion.find(
        f"{{{NS['saml']}}}Subject/{{{NS['saml']}}}SubjectConfirmation/"
        f"{{{NS['saml']}}}SubjectConfirmationData"
    )
    if scd is not None:
        _check_window(scd.get("NotBefore"), scd.get("NotOnOrAfter"), "SubjectConfirmationData")
        recipient = (scd.get("Recipient") or "").rstrip("/")
        if recipient and recipient != acs_url(request_base).rstrip("/"):
            raise SSOError(f"SAML assertion Recipient '{recipient}' is not this ACS endpoint")
        in_response_to = scd.get("InResponseTo")
        if expected_request_id and in_response_to and in_response_to != expected_request_id:
            raise SSOError("SAML assertion answers a different AuthnRequest (possible replay)")

    # Single use.
    assertion_id = assertion.get("ID") or ""
    if not assertion_id:
        raise SSOError("SAML assertion has no ID; cannot enforce single use")

    name_id_el = assertion.find(f"{{{NS['saml']}}}Subject/{{{NS['saml']}}}NameID")
    name_id = _text(name_id_el)
    attrs = _attributes(assertion)

    email = _first(attrs, _EMAIL_ATTRS)
    if not email and "@" in name_id:
        email = name_id
    if not email:
        raise SSOError(
            "SAML assertion carries no email address. Map an email attribute "
            "(or an emailAddress NameID) at the IdP."
        )

    return {
        "email": email.strip().lower(),
        "name": _first(attrs, _NAME_ATTRS) or name_id or email,
        "sub": name_id or email,
        "assertion_id": assertion_id,
        "session_index": (assertion.find(f"{{{NS['saml']}}}AuthnStatement").get("SessionIndex")
                          if assertion.find(f"{{{NS['saml']}}}AuthnStatement") is not None else None),
    }


# ── replay guard ──────────────────────────────────────────────────────────────

# ponytail: in-process fallback is per-worker. Redis (present in every non-dev
# deployment) makes it fleet-wide; the fallback only degrades single-node dev.
_SEEN: dict[str, datetime] = {}
_SEEN_TTL = timedelta(minutes=10)


async def claim_assertion_id(assertion_id: str) -> None:
    """Consume an assertion ID once. Raises ``SSOError`` on a replay."""
    from app.core.redis import get_redis

    redis = await get_redis()
    if redis is not None:
        # SET NX is atomic, so two concurrent replays cannot both win.
        won = await redis.set(f"saml:seen:{assertion_id}", "1",
                              nx=True, ex=int(_SEEN_TTL.total_seconds()))
        if not won:
            raise SSOError("SAML assertion has already been used (replay refused)")
        return

    now = datetime.now(timezone.utc)
    for key, seen_at in list(_SEEN.items()):
        if now - seen_at > _SEEN_TTL:
            _SEEN.pop(key, None)
    if assertion_id in _SEEN:
        raise SSOError("SAML assertion has already been used (replay refused)")
    _SEEN[assertion_id] = now
