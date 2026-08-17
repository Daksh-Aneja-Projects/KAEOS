"""EGRESS-FIREWALL gate: no bare httpx client may bypass the SSRF guard.

Any outbound HTTP the server makes on a caller's behalf must go through
``app.core.outbound.guarded_async_client`` / ``GuardedTransport``, which
re-resolves the host at connect time and refuses metadata/private targets
(DNS-rebind proof). A bare ``httpx.AsyncClient(...)`` / ``httpx.Client(...)``
anywhere in the app makes a request that skips that vetting - the exact SSRF
class outbound.py exists to close.

This test scans the whole ``app/`` tree and fails the build on any bare client
that is not one of the three sanctioned forms:

  1. outbound.py itself - it defines the guarded client + GuardedTransport.
  2. an in-process ASGITransport client (``transport=httpx.ASGITransport(...)``),
     which never touches the network, so SSRF does not apply.
  3. the EXPLICIT allowlist below: constant, non-tenant-controlled provider
     URLs that cannot be steered at a private/metadata address.

Add a new bare client anywhere else and this test goes red. To add a genuinely
new allowed egress, either route it through ``guarded_async_client`` (preferred)
or, for a hard-coded provider endpoint, add a (path, reason) entry here with the
reason it is safe - never widen it silently.

ponytail: line-window text scan, not an AST walk. Upgrade to ast if a false
positive from a docstring/comment mentioning the pattern ever appears (today
the only such mention lives in outbound.py, which is allowlisted).
"""
import re
from pathlib import Path

# tests/ -> backend/ ; the app package is the whole scanned surface.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = BACKEND_ROOT / "app"

_BARE_CLIENT = re.compile(r"httpx\.(?:Async)?Client\(")

# Explicit allowlist: repo-relative path -> why a bare client here is safe.
# Anything NOT covered by this set, the ASGITransport carve-out, or outbound.py
# is a violation.
ALLOWLIST = {
    "app/core/outbound.py":
        "defines guarded_async_client + GuardedTransport - the SSRF wrapper itself",
    "app/services/foundry/finetune.py":
        "posts only to the constant https://api.openai.com provider endpoint; "
        "the URL is hard-coded, never tenant- or request-supplied",
}


def _iter_bare_clients():
    """Yield (repo_relative_path, line_no, context) for every bare-client match.

    context = the match line plus a few following lines, so a ``transport=``
    kwarg that wraps onto continuation lines is still visible to the classifier.
    """
    for py in sorted(APP_DIR.rglob("*.py")):
        rel = py.relative_to(BACKEND_ROOT).as_posix()
        lines = py.read_text(encoding="utf-8").splitlines()
        uses_asgi = any("httpx.ASGITransport(" in ln for ln in lines)
        for i, line in enumerate(lines):
            if _BARE_CLIENT.search(line):
                context = "\n".join(lines[i:i + 5])
                yield rel, i + 1, context, uses_asgi


def _is_allowed(rel: str, context: str, uses_asgi: bool) -> bool:
    if rel in ALLOWLIST:
        return True
    # In-process ASGI transport = no real network egress, so no SSRF surface.
    if uses_asgi and "transport=" in context:
        return True
    return False


def test_no_unguarded_httpx_clients():
    """Every bare httpx client in app/ must be a sanctioned form."""
    violations = [
        f"{rel}:{ln} constructs a bare httpx client that bypasses the "
        f"SSRF-guarded wrapper"
        for rel, ln, context, uses_asgi in _iter_bare_clients()
        if not _is_allowed(rel, context, uses_asgi)
    ]
    assert not violations, (
        "Unguarded outbound HTTP client(s) found - route these through "
        "app.core.outbound.guarded_async_client, or (for a constant provider "
        "endpoint) add a justified entry to ALLOWLIST in this file:\n  "
        + "\n  ".join(violations)
    )


def test_allowlist_entries_still_exist():
    """A stale allowlist path hides a moved/deleted exemption - fail on rot."""
    stale = [p for p in ALLOWLIST if not (BACKEND_ROOT / p).exists()]
    assert not stale, f"ALLOWLIST cites path(s) that no longer exist: {stale}"


def test_guard_wrapper_is_present():
    """The gate is meaningless if the wrapper it points at has been removed."""
    src = (APP_DIR / "core" / "outbound.py").read_text(encoding="utf-8")
    assert "def guarded_async_client(" in src
    assert "class GuardedTransport(" in src
