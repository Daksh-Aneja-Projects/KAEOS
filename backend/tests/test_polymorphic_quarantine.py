"""Code-safety: the polymorphic engine (LLM-authored Python written into the app
import path) must be OFF by default and refuse to run without an explicit opt-in.

These are pure unit checks: no Ollama, no disk writes, no DB.
"""
import asyncio
from types import SimpleNamespace

from app.services.polymorphic_engine import PolymorphicEngine


def _settings(flag):
    return lambda: SimpleNamespace(ALLOW_POLYMORPHIC_CODEGEN=flag)


def test_disabled_by_default_refuses_without_llm_or_disk(monkeypatch):
    """Flag absent/False => refuse BEFORE any LLM call or file write."""
    monkeypatch.setattr("app.core.config.get_settings", _settings(False))

    # If synthesis reached codegen it would call the LLM router; make that explode
    # so the test fails loudly if the guard is ever bypassed.
    def _boom(*a, **k):
        raise AssertionError("codegen ran while disabled")

    monkeypatch.setattr(PolymorphicEngine, "_generate_tool_code", staticmethod(_boom))

    tool = asyncio.run(PolymorphicEngine.synthesize_tool("intent", "some_integration"))
    assert tool.status == "DISABLED_BY_CONFIG"
    assert tool.source_code == ""


def test_enabled_flag_lets_it_proceed_to_codegen(monkeypatch):
    """Flag True => guard passes and control reaches codegen (mocked)."""
    monkeypatch.setattr("app.core.config.get_settings", _settings(True))

    async def _fake_code(intent, name):
        return "class X: pass"

    monkeypatch.setattr(PolymorphicEngine, "_generate_tool_code", staticmethod(_fake_code))

    # Stop before touching disk: fail the sandbox scan so no file is written.
    async def _fake_scan(code, name):
        return False

    monkeypatch.setattr(PolymorphicEngine, "_sandbox_execution_scan", staticmethod(_fake_scan))

    tool = asyncio.run(PolymorphicEngine.synthesize_tool("intent", "some_integration"))
    assert tool.status == "FAILED_SANDBOX_SCAN"


def test_ast_scan_catches_rce_and_introspection_escapes():
    """The defence-in-depth AST guard flags eval/exec/os.system and the
    __class__->__subclasses__ traversal that a name-only denylist misses."""
    dangerous = [
        "eval('1+1')",
        "import os\nos.system('rm -rf /')",
        "__import__('os').system('x')",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read()",
    ]
    for src in dangerous:
        findings = PolymorphicEngine._scan_findings(src)
        assert findings, f"expected the guard to flag: {src!r}"

    clean = "import httpx\nclass FooTool:\n    async def execute(self, payload: dict):\n        return payload\n"
    assert PolymorphicEngine._scan_findings(clean) == []


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
