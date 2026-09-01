"""The Enterprise seam (fusion F0): inert without kaeos_enterprise, honest on
every degrade path, and observers can never alter a governed verdict.

kaeos_enterprise itself is private and never installed in this repo's CI, so
these tests pin the CORE half of the contract: registration, dispatch error
containment, adapter push rules, boot loading semantics, and the professional
entitlement refusal.
"""
import sys
import types

import pytest
from fastapi import HTTPException

from app.core import entitlements
from app.core.extensions import ExtensionRegistry, extensions, load_enterprise


@pytest.fixture(autouse=True)
def _inert_seam():
    """Every test starts and ends with the process-wide seam inert."""
    extensions.reset()
    yield
    extensions.reset()
    sys.modules.pop("kaeos_enterprise", None)


def _fake_ee(register=None, version="0.0-test", features=("proof",)):
    """Install a stand-in kaeos_enterprise module into sys.modules."""
    mod = types.ModuleType("kaeos_enterprise")
    mod.__version__ = version
    mod.FEATURES = tuple(features)
    mod.register = register or (lambda hooks: None)
    sys.modules["kaeos_enterprise"] = mod
    return mod


def test_registry_inert_by_default():
    reg = ExtensionRegistry()
    assert not reg.provides()
    assert not reg.provides("proof")
    assert reg.status() == {
        "installed": False, "loaded": False, "version": None,
        "features": [], "error": None,
    }


async def test_dispatch_swallows_hook_errors():
    reg = ExtensionRegistry()
    seen = []

    async def bad(*a):
        raise RuntimeError("boom")

    async def good(context, gate, state, detail):
        seen.append((gate, state))

    reg.add_gate_stage_hook(bad)
    reg.add_gate_stage_hook(good)
    await reg.dispatch_gate_stage({}, "compliance", "passed")
    assert seen == [("compliance", "passed")]

    terminal = []

    async def bad_t(*a):
        raise RuntimeError("boom")

    async def good_t(skill, context, result):
        terminal.append(result["status"])

    reg.add_pipeline_terminal_hook(bad_t)
    reg.add_pipeline_terminal_hook(good_t)
    await reg.dispatch_pipeline_terminal({}, {}, {"status": "SUCCESS_CLEAN"})
    assert terminal == ["SUCCESS_CLEAN"]


def test_add_vendor_adapters_push_and_clash():
    from app.services.vendor_adapters import registry as vreg
    reg = ExtensionRegistry()
    sentinel = object()
    try:
        reg.add_vendor_adapters({"ee_test_adapter": sentinel},
                                {"ee_test_adapter": ["instance_url"]})
        assert vreg.VENDOR_ADAPTERS["ee_test_adapter"] is sentinel
        assert vreg.VENDOR_REQUIRED_CONFIG["ee_test_adapter"] == ["instance_url"]
        # Shadowing a core adapter is a packaging bug, refused loudly.
        with pytest.raises(ValueError, match="github"):
            reg.add_vendor_adapters({"github": sentinel})
        assert vreg.VENDOR_ADAPTERS["github"] is not sentinel
    finally:
        vreg.VENDOR_ADAPTERS.pop("ee_test_adapter", None)
        vreg.VENDOR_REQUIRED_CONFIG.pop("ee_test_adapter", None)


def test_load_enterprise_not_installed():
    sys.modules.pop("kaeos_enterprise", None)
    status = load_enterprise()
    assert status["loaded"] is False
    assert status["installed"] is False
    assert status["error"] is None


def test_load_enterprise_disabled_env(monkeypatch):
    _fake_ee()
    monkeypatch.setenv("KAEOS_EE_DISABLED", "1")
    status = load_enterprise()
    assert status["loaded"] is False


def test_load_enterprise_registers_and_mounts():
    marker_router = object()

    def register(hooks):
        hooks.add_router(marker_router)

    _fake_ee(register=register, features=("proof", "rehearsal"))

    mounted = []

    class FakeApp:
        def include_router(self, router, prefix=""):
            mounted.append((router, prefix))

    status = load_enterprise(FakeApp(), prefix="/api/v1")
    assert status["loaded"] is True
    assert status["version"] == "0.0-test"
    assert status["features"] == ["proof", "rehearsal"]
    assert mounted == [(marker_router, "/api/v1")]
    assert extensions.provides("proof")
    assert not extensions.provides("gateway")


def test_load_enterprise_broken_register_resets():
    async def hook(*a):  # pragma: no cover - never dispatched
        pass

    def register(hooks):
        hooks.add_gate_stage_hook(hook)  # partial registration...
        raise RuntimeError("license file unreadable")  # ...then failure

    _fake_ee(register=register)
    status = load_enterprise()
    # Fail to inert, never half-loaded: the partial hook must be gone.
    assert status["loaded"] is False
    assert "license file unreadable" in status["error"]
    assert extensions.gate_stage_hooks == []
    assert status["installed"] is True  # honest: present but broken


async def test_dispatch_startup_runs_hooks():
    ran = []

    async def hook():
        ran.append(True)

    extensions.add_startup_hook(hook)
    await extensions.dispatch_startup()
    assert ran == [True]


async def test_dispatch_startup_failure_resets_seam():
    async def ok_hook():
        pass

    async def bad_hook():
        raise RuntimeError("EE tables could not be created")

    extensions.loaded = True
    extensions.add_pipeline_terminal_hook(ok_hook)  # type: ignore[arg-type]
    extensions.add_startup_hook(bad_hook)
    await extensions.dispatch_startup()
    # Half-initialised Enterprise must not run: seam inert, error surfaced.
    assert extensions.loaded is False
    assert extensions.pipeline_terminal_hooks == []
    assert "EE tables could not be created" in extensions.error


async def test_emit_gate_reaches_registered_hook():
    from app.agents.runtime import AgentExecutor
    seen = []

    async def hook(context, gate, state, detail):
        seen.append((gate, state, detail))

    extensions.add_gate_stage_hook(hook)
    ex = AgentExecutor(None, None)
    await ex._emit_gate({"tenant_id": "t", "execution_id": "e"},
                        "compliance", "passed", "ok")
    assert seen == [("compliance", "passed", "ok")]


async def test_require_enterprise_refusal_copy(monkeypatch):
    checker = entitlements.require_enterprise("proof")

    # Not loaded: professional 402, names the capability, no stack trace.
    with pytest.raises(HTTPException) as exc:
        await checker(tenant={"tenant_id": "t1"}, db=None)
    assert exc.value.status_code == 402
    assert "KAEOS Enterprise capability" in exc.value.detail
    assert "proof" in exc.value.detail

    # Loaded, self-host: passes through.
    extensions.loaded = True
    extensions.features = frozenset({"proof"})
    tenant = {"tenant_id": "t1"}
    assert await checker(tenant=tenant, db=None) is tenant

    # Loaded, managed cloud, plan without the feature: upgrade refusal.
    monkeypatch.setattr(entitlements, "_managed_cloud", lambda: True)

    async def fake_plan(db, tenant_id):
        return "team"

    monkeypatch.setattr(entitlements, "plan_for_tenant", fake_plan)
    with pytest.raises(HTTPException) as exc:
        await checker(tenant=tenant, db=None)
    assert exc.value.status_code == 402
    assert "team" in exc.value.detail

    # Managed cloud, enterprise plan: entitled.
    async def ent_plan(db, tenant_id):
        return "enterprise"

    monkeypatch.setattr(entitlements, "plan_for_tenant", ent_plan)
    assert await checker(tenant=tenant, db=None) is tenant
