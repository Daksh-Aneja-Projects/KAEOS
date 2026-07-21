"""Pre-egress PII scrubbing: PII must be redacted before any CLOUD LLM call,
and must be left intact for LOCAL (in-region) Ollama calls.

Covers the belt-and-suspenders design in LLMRouter._scrub_for_cloud:
  * the deterministic structured backstop (redact_structured_pii) works with no
    Presidio dependency — the guarantee that a phone/SSN never egresses;
  * a real cloud _call_llm scrubs the outbound messages;
  * a local Ollama _call_llm does NOT scrub (data stays in-region anyway, and
    scrubbing every local token would be wasted work).
"""
import types

import pytest

from app.transforms.pii_scrubber import redact_structured_pii
from app.services.llm_router import LLMRouter

PII_TEXT = (
    "Reach Jane at jane.roe@corp.com or 415-555-2671; "
    "SSN 123-45-6789, card 4111 1111 1111 1111, host 10.0.0.5."
)
STRUCTURED_LEAKS = [
    "jane.roe@corp.com", "415-555-2671", "123-45-6789",
    "4111 1111 1111 1111", "10.0.0.5",
]


def test_redact_structured_pii_is_deterministic_and_complete():
    """Regex backstop redacts every structured identifier, no Presidio needed."""
    out, n = redact_structured_pii(PII_TEXT)
    assert n >= 5
    for leak in STRUCTURED_LEAKS:
        assert leak not in out, f"structured PII leaked: {leak}"
    assert "[EMAIL_ADDRESS]" in out and "[US_SSN]" in out and "[PHONE_NUMBER]" in out


def test_redact_structured_pii_empty_is_noop():
    assert redact_structured_pii("") == ("", 0)
    assert redact_structured_pii("nothing sensitive here") == ("nothing sensitive here", 0)


@pytest.mark.asyncio
async def test_scrub_for_cloud_removes_all_structured_pii():
    out = await LLMRouter()._scrub_for_cloud(PII_TEXT)
    for leak in STRUCTURED_LEAKS:
        assert leak not in out, f"structured PII leaked through egress scrub: {leak}"


class _FakeResp:
    """Minimal stand-in for a litellm completion response."""
    def __init__(self, content):
        msg = types.SimpleNamespace(content=content)
        self.choices = [types.SimpleNamespace(message=msg)]
        self.model = "fake"
        self.usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)


@pytest.mark.asyncio
async def test_cloud_call_scrubs_before_egress(monkeypatch):
    """A real cloud _call_llm must scrub PII out of the outbound messages."""
    import litellm

    captured = {}

    async def fake_acompletion(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return _FakeResp("ok")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    router = LLMRouter()
    # Force provider availability without any network probe.
    async def _always(*_a, **_k):
        return True
    monkeypatch.setattr(router, "provider_available", _always)

    await router._call_llm(
        "gpt-4o-mini", PII_TEXT, system_prompt="Caller SSN 987-65-4321.",
        temperature=0.0, max_tokens=16, tenant_api_keys={"openai": "sk-test"},
    )

    blob = " ".join(m["content"] for m in captured["messages"])
    for leak in STRUCTURED_LEAKS + ["987-65-4321"]:
        assert leak not in blob, f"PII egressed to cloud provider: {leak}"


@pytest.mark.asyncio
async def test_local_call_does_not_scrub(monkeypatch):
    """A local Ollama _call_llm leaves PII intact (in-region, no egress)."""
    import litellm

    captured = {}

    async def fake_acompletion(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return _FakeResp("ok")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    router = LLMRouter()
    async def _always(*_a, **_k):
        return True
    monkeypatch.setattr(router, "provider_available", _always)

    await router._call_llm(
        "ollama/qwen2.5-coder:7b", PII_TEXT, system_prompt=None,
        temperature=0.0, max_tokens=16, tenant_api_keys=None,
    )

    blob = " ".join(m["content"] for m in captured["messages"])
    # The raw identifiers are still present — local inference stays in-region.
    assert "jane.roe@corp.com" in blob and "123-45-6789" in blob
