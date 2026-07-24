"""
Phase 2E — PII egress scrubber must FAIL CLOSED under a data-residency policy.

Previously a scrub failure degraded to sending unscrubbed text to the cloud
provider. Under DATA_RESIDENCY / SCRUB_PII_BEFORE_LLM this now raises
PIIScrubError so the cloud call is blocked; without such a policy it still
degrades gracefully so a transient error never takes down inference.
"""
from types import SimpleNamespace

import pytest

from app.services.llm_router import LLMRouter, PIIScrubError

pytestmark = pytest.mark.asyncio


def _break_backstop(monkeypatch):
    import app.transforms.pii_scrubber as ps

    def boom(text):
        raise RuntimeError("scrubber unavailable")

    monkeypatch.setattr(ps, "redact_structured_pii", boom)


def test_config_fail_closed_property():
    from app.core.config import Settings
    assert Settings(DATA_RESIDENCY="eu").pii_egress_fail_closed is True
    assert Settings(SCRUB_PII_BEFORE_LLM=True).pii_egress_fail_closed is True
    assert Settings(DATA_RESIDENCY="", SCRUB_PII_BEFORE_LLM=False).pii_egress_fail_closed is False


async def test_scrub_fails_closed_under_residency(monkeypatch):
    import app.core.config as cfg
    _break_backstop(monkeypatch)
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(pii_egress_fail_closed=True))

    router = LLMRouter()
    with pytest.raises(PIIScrubError):
        await router._scrub_for_cloud("contact me at alice@example.com or 555-123-4567")


async def test_scrub_degrades_without_residency(monkeypatch):
    import app.core.config as cfg
    _break_backstop(monkeypatch)
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(pii_egress_fail_closed=False))

    router = LLMRouter()
    # Must not raise — returns best-effort text so inference is never taken down.
    out = await router._scrub_for_cloud("hello world")
    assert out is not None
