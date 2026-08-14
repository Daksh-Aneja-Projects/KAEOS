"""Resolve the real client IP when KAEOS runs behind trusted reverse proxies.

``request.client.host`` is the immediate peer. Behind an L7 proxy that peer IS
the proxy, so the per-tenant IP allowlist and the login audit would compare/record
the proxy address, not the caller. When (and only when) the peer is a configured
trusted proxy, the X-Forwarded-For chain is trusted and the right-most entry that
is not itself a trusted proxy is returned - the real client the outermost trusted
proxy saw. With no trusted proxies configured (the default), the raw peer is
always returned: an untrusted peer can spoof XFF freely, so it is never consulted.

ponytail: XFF-chain heuristic, no PROXY-protocol / Forwarded RFC 7239 parsing;
add those if a proxy in front does not speak X-Forwarded-For.
"""
import ipaddress
from typing import Optional

from app.core.config import get_settings


def _trusted_networks() -> list:
    nets = []
    for entry in getattr(get_settings(), "TRUSTED_PROXIES", []) or []:
        try:
            nets.append(ipaddress.ip_network(str(entry), strict=False))
        except ValueError:
            continue
    return nets


def _is_trusted(ip_str: Optional[str], nets: list) -> bool:
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def client_ip(request) -> Optional[str]:
    """The best-effort real client IP for ``request``.

    Returns the raw peer unless it is a configured trusted proxy, in which case
    the right-most non-trusted X-Forwarded-For entry is returned.
    """
    peer = request.client.host if request.client else None
    nets = _trusted_networks()
    if not nets or not _is_trusted(peer, nets):
        return peer
    xff = request.headers.get("x-forwarded-for", "") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for candidate in reversed(parts):
        if not _is_trusted(candidate, nets):
            return candidate
    return peer


def _demo() -> None:
    """Self-check without a real Request: a tiny stub with .client and .headers."""
    class _C:
        def __init__(self, host):
            self.host = host

    class _R:
        def __init__(self, host, xff=None):
            self.client = _C(host)
            self.headers = {"x-forwarded-for": xff} if xff else {}

    import app.core.config as cfg

    class _S:
        TRUSTED_PROXIES: list = []

    orig = cfg.get_settings
    cfg.get_settings = lambda: _S()
    try:
        # No trusted proxies -> always the peer, XFF ignored even if present.
        assert client_ip(_R("10.0.0.1", "1.2.3.4")) == "10.0.0.1"
        _S.TRUSTED_PROXIES = ["10.0.0.0/8"]
        # Trusted peer -> right-most non-trusted XFF entry is the real client.
        assert client_ip(_R("10.0.0.1", "1.2.3.4, 10.0.0.9")) == "1.2.3.4"
        # Untrusted peer -> spoofed XFF ignored.
        assert client_ip(_R("203.0.113.7", "1.2.3.4")) == "203.0.113.7"
    finally:
        cfg.get_settings = orig
    print("net._demo OK")


if __name__ == "__main__":
    _demo()
