"""Guard for URLs that the server will fetch or POST to on a caller's behalf.

Three request-supplied values end up as outbound HTTP targets: a live
connector's `*_url` config, an event-bus webhook `endpoint`, and the pipeline's
webhook destination `url`. Without a check, `http://169.254.169.254/...` turns
any of them into a cloud-metadata read, and on the connector sync path the
response is normalised into Signal rows the tenant can read back, which makes it
an SSRF with the response returned.

The cloud metadata address and non-HTTP schemes are refused everywhere. Loopback
and private ranges are refused only outside DEV_MODE, because local development
and the test suite legitimately point webhooks at 127.0.0.1.

ponytail: this validates the hostname, it does not pin the connection to the
resolved address, so a DNS entry that changes between the check and the request
still gets through. Closing that needs a custom transport that dials a
pre-resolved IP; worth doing if these endpoints ever face untrusted tenants.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import get_settings

# Link-local, used by AWS/GCP/Azure for instance metadata. Never reachable on
# purpose from user-supplied config, in any environment.
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata"}

_ALLOWED_SCHEMES = {"http", "https"}


def _resolved_ips(host: str) -> list:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return out


def check_outbound_url(url: str, *, allow_private: bool | None = None) -> str | None:
    """Return a reason string if `url` is an unsafe outbound target, else None."""
    if not url or not isinstance(url, str):
        return "URL is required"

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return "URL must use http or https"
    host = (parsed.hostname or "").lower()
    if not host:
        return "URL must include a host"
    if host in _METADATA_HOSTS:
        return "URL may not target the cloud metadata service"

    if allow_private is None:
        allow_private = get_settings().DEV_MODE

    candidates = _resolved_ips(host)
    # A literal IP that does not resolve still needs checking.
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        pass

    for ip in candidates:
        if ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "URL may not target a link-local or reserved address"
        if not allow_private and (ip.is_private or ip.is_loopback):
            return "URL may not target a private or loopback address"
    return None


def assert_safe_outbound_url(url: str, *, allow_private: bool | None = None) -> None:
    """Raise ValueError if `url` is an unsafe outbound target."""
    reason = check_outbound_url(url, allow_private=allow_private)
    if reason:
        raise ValueError(reason)


def _demo() -> None:
    """Self-check: metadata and bad schemes always blocked; private is gated."""
    assert check_outbound_url("https://example.com/hook", allow_private=False) is None
    assert check_outbound_url("http://169.254.169.254/latest/meta-data/", allow_private=True)
    assert check_outbound_url("file:///etc/passwd", allow_private=True)
    assert check_outbound_url("", allow_private=True)
    # Loopback: refused in production, allowed in dev/test.
    assert check_outbound_url("http://127.0.0.1:9/nope", allow_private=False)
    assert check_outbound_url("http://127.0.0.1:9/nope", allow_private=True) is None
    print("outbound._demo OK")


if __name__ == "__main__":
    _demo()
