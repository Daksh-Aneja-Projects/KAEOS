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

``check_outbound_url`` is the cheap up-front reject. The authoritative gate is
``guarded_async_client()`` / ``GuardedTransport``: it re-resolves the host at
connect time, validates EVERY resolved address, and dials the vetted IP directly
(preserving the Host header and TLS SNI), so a DNS entry that flips between the
check and the request (DNS rebinding) cannot reach an internal/metadata target.

ponytail: per-request re-resolution is the ceiling. An allowlist of egress IPs
or a dedicated egress proxy is the upgrade if these endpoints ever face fully
untrusted tenants at scale.
"""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

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


def _pick_safe_ip(host: str, *, allow_private: bool | None = None) -> str:
    """Resolve `host`, reject if ANY resolved address is unsafe, return one vetted IP.

    Resolution and validation happen together here and the returned IP is what the
    caller connects to, so there is no window for the record to change in between.
    """
    host = (host or "").strip("[]").lower()
    if not host:
        raise ValueError("URL must include a host")
    if host in _METADATA_HOSTS:
        raise ValueError("URL may not target the cloud metadata service")
    if allow_private is None:
        allow_private = get_settings().DEV_MODE

    candidates = _resolved_ips(host)
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not candidates:
        raise ValueError(f"Cannot resolve host: {host}")

    for ip in candidates:
        if ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("URL may not target a link-local or reserved address")
        if not allow_private and (ip.is_private or ip.is_loopback):
            raise ValueError("URL may not target a private or loopback address")
    return str(candidates[0])


class GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx transport that pins each request to a freshly vetted IP.

    On every outbound request it resolves the host, validates all resolved
    addresses, then rewrites the request to dial the vetted IP while keeping the
    original Host header and TLS SNI. This closes the DNS-rebind TOCTOU that a
    pre-flight hostname check cannot.
    """

    def __init__(self, *, allow_private: bool | None = None, **kwargs):
        super().__init__(**kwargs)
        self._allow_private = allow_private

    async def handle_async_request(self, request):
        host = request.url.host
        safe_ip = _pick_safe_ip(host, allow_private=self._allow_private)
        # Preserve TLS cert validation (SNI + hostname) against the original host,
        # then connect to the vetted IP literal.
        request.extensions = {**request.extensions, "sni_hostname": host}
        request.url = request.url.copy_with(host=safe_ip)
        # The Host header was already set from the original URL at build time and
        # is deliberately NOT rewritten, so virtual-host routing still works.
        return await super().handle_async_request(request)


def guarded_async_client(*, allow_private: bool | None = None, **kwargs) -> httpx.AsyncClient:
    """An AsyncClient whose connections are SSRF-pinned. follow_redirects forced off.

    Use this in place of ``httpx.AsyncClient(...)`` for any fetch/POST to a
    request- or tenant-supplied URL.
    """
    kwargs["follow_redirects"] = False
    return httpx.AsyncClient(transport=GuardedTransport(allow_private=allow_private), **kwargs)


def _demo() -> None:
    """Self-check: metadata and bad schemes always blocked; private is gated."""
    assert check_outbound_url("https://example.com/hook", allow_private=False) is None
    assert check_outbound_url("http://169.254.169.254/latest/meta-data/", allow_private=True)
    assert check_outbound_url("file:///etc/passwd", allow_private=True)
    assert check_outbound_url("", allow_private=True)
    # Loopback: refused in production, allowed in dev/test.
    assert check_outbound_url("http://127.0.0.1:9/nope", allow_private=False)
    assert check_outbound_url("http://127.0.0.1:9/nope", allow_private=True) is None

    # Pin: a host resolving to the metadata IP is refused at connect-vetting time,
    # even though the literal-string check above only catches the known hostnames.
    import socket as _socket
    _orig = _socket.getaddrinfo
    _socket.getaddrinfo = lambda h, *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))]
    try:
        try:
            _pick_safe_ip("rebind.example.com", allow_private=True)
            raise AssertionError("rebind to link-local should have been refused")
        except ValueError:
            pass
    finally:
        _socket.getaddrinfo = _orig
    # A public literal is fine and is returned for dialing.
    assert _pick_safe_ip("93.184.216.34", allow_private=False) == "93.184.216.34"
    print("outbound._demo OK")


if __name__ == "__main__":
    _demo()
