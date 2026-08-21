"""Harvest the in-file ``__main__`` honesty guards into CI.

~20 app modules carry an ``if __name__ == "__main__"`` self-check block that
asserts a load-bearing invariant (SOX four-eyes, ECOA late-notice, PHI Part-2
consent, minimum-necessary schema, SSRF pinning, cache tenant-isolation, ...).
CI never ran them, so every one of those guards was inert. This runs each via
``runpy.run_path(path, run_name="__main__")`` and asserts it raises nothing -
one CI gate that turns all of them live.

Curated allow-list, NOT a scan: some ``__main__`` blocks start servers, open
sockets, or need a live DB (seeders, scheduler, API routers, MCP bridges) and
are deliberately excluded. ``app/core/metrics.py`` is excluded too - running it
a second time re-registers its Prometheus collectors into the already-populated
default registry (duplicate-timeseries error), an artifact of re-execution, not
a real failure.
"""
import runpy
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

# Each entry is a module whose __main__ block is a pure assert-based self-check
# with no server/socket/live-DB/network side effects (verified by reading each).
SELF_CHECK_FILES = [
    "compliance/checkers/crm.py",
    "compliance/checkers/finance.py",
    "compliance/checkers/lending.py",
    "core/entitlements.py",
    "core/errors.py",
    "core/net.py",
    "core/outbound.py",
    # NOTE: core/result_cache.py is intentionally excluded - its __main__ _demo
    # runs against the real cache bus (Redis when one is up), so the demo keys
    # persist across runs and the "producer ran once" assertion flakes on the
    # second run within the TTL. Shared external state, not a pure self-check.
    "core/polystore/vector_store.py",
    "finance/services/three_way_match.py",
    "lending/services/underwriting.py",
    "healthcare/services/phi_disclosure.py",
    "services/consequence.py",
    "services/llm_router.py",
    "services/privacy_erasure.py",
    "services/retrieval.py",
    "support/agents/gated_runner.py",
    "support/agents/sla_agent.py",
    "operations/services/workflows.py",
    "hr/agents/offboarding_agent.py",
    "workforce/domain_packs/loader.py",
]


@pytest.mark.parametrize("rel", SELF_CHECK_FILES, ids=SELF_CHECK_FILES)
def test_module_self_check_passes(rel):
    path = _APP / rel
    assert path.exists(), f"self-check file missing: {rel}"
    # An AssertionError (or any exception) inside the __main__ block propagates
    # and fails this parametrized case - which is exactly the guard going live.
    runpy.run_path(str(path), run_name="__main__")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
