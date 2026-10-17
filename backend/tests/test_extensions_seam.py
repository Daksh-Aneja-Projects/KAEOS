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


class _FakeTranscript:
    def __init__(self, decision="PROCEED", rationale="llm view"):
        self.id = "transcript-seam-test"  # absent from the DB; persist no-ops
        self.proposer_argument = {"evidence": ["a"], "confidence": 0.9}
        self.advocate_argument = {"risks": [], "ungrounded_claims_found": 0}
        self.arbitrator_decision = {"decision": decision, "rationale": rationale,
                                    "final_confidence": 0.9}


class _FakeDebateEngine:
    def __init__(self, transcript):
        self._t = transcript

    def should_debate(self, skill_obj, context):
        return True, "seam-test"

    async def run_debate(self, skill_obj, context, execution_id, tenant_id):
        return self._t


async def test_debate_solver_decides_the_gate():
    from app.agents.runtime import AgentExecutor
    seen = []

    async def solver(roles, context):
        seen.append(roles)
        return {"decision": "PROCEED", "rationale": "arithmetic says go",
                "proof_summary": {"margin": 0.2}}

    extensions.set_debate_solver(solver)
    ex = AgentExecutor(None, None)
    # The LLM arbitrator says BLOCK; the registered solver's PROCEED decides.
    ex._debate_engine = _FakeDebateEngine(_FakeTranscript(decision="BLOCK"))
    outcome = await ex._gate_debate(
        {"skill_id": "s"}, {"tenant_id": "t", "execution_id": "e"},
        object(), pre_approved=False)
    assert outcome is None, "solver PROCEED must let the pipeline continue"
    assert seen and set(seen[0]) == {"proposer", "advocate", "arbitrator"}


async def test_debate_solver_error_falls_back_to_llm():
    from app.agents.runtime import AgentExecutor

    async def broken(roles, context):
        raise RuntimeError("solver down")

    extensions.set_debate_solver(broken)
    ex = AgentExecutor(None, None)
    # Solver fails; the LLM arbitrator's PROCEED stands (fail-closed to the
    # existing verdict, never a crash).
    ex._debate_engine = _FakeDebateEngine(_FakeTranscript(decision="PROCEED"))
    outcome = await ex._gate_debate(
        {"skill_id": "s"}, {"tenant_id": "t", "execution_id": "e"},
        object(), pre_approved=False)
    assert outcome is None


async def test_confidence_caps_lower_and_force_but_never_raise():
    from app.agents.runtime import AgentExecutor

    async def capping(skill, context):
        return {"ceiling": 0.6, "force_hitl": False, "reason": "uncertain input"}

    async def raising(skill, context):
        return {"ceiling": 0.99, "force_hitl": False, "reason": "generous"}

    async def forcing(skill, context):
        return {"ceiling": None, "force_hitl": True, "reason": "suspect input"}

    extensions.add_confidence_cap(capping)
    extensions.add_confidence_cap(raising)
    extensions.add_confidence_cap(forcing)
    ex = AgentExecutor(None, None)
    conf, force, refuse = await ex._apply_extension_caps(
        0.9, {"skill_id": "s"}, {"tenant_id": "t", "execution_id": "e"})
    assert conf == 0.6, "min() semantics: a cap can lower, never raise"
    assert force == "suspect input"
    assert refuse is None


async def test_erroring_cap_provider_fails_closed():
    from app.agents.runtime import AgentExecutor
    from app.core.config import get_settings

    async def broken(skill, context):
        raise RuntimeError("provider down")

    extensions.add_confidence_cap(broken)
    ex = AgentExecutor(None, None)
    conf, force, refuse = await ex._apply_extension_caps(
        0.95, {"skill_id": "s"}, {"tenant_id": "t", "execution_id": "e"})
    assert conf == min(0.95, get_settings().FAILSAFE_CONFIDENCE_CEILING)
    assert force is None and refuse is None


async def test_cap_provider_can_refuse_outright():
    """A policy refusal (the origin rule) is neither a cap nor a pause: it is
    surfaced as a third return the gate turns into BLOCKED."""
    from app.agents.runtime import AgentExecutor

    async def refusing(skill, context):
        return {"ceiling": None, "force_hitl": False, "refuse": True,
                "reason": "top-tier write proposed from external content"}

    extensions.add_confidence_cap(refusing)
    ex = AgentExecutor(None, None)
    conf, force, refuse = await ex._apply_extension_caps(
        0.9, {"skill_id": "s"}, {"tenant_id": "t", "execution_id": "e"})
    assert conf == 0.9 and force is None
    assert refuse == "top-tier write proposed from external content"


async def test_hitl_enrichers_observe_and_swallow_errors():
    seen = []

    async def attach(skill, context):
        context["rehearsal"] = {"summary": "one field changes"}
        seen.append(skill["skill_id"])

    async def broken(skill, context):
        raise RuntimeError("enricher down")

    extensions.add_hitl_enricher(broken)
    extensions.add_hitl_enricher(attach)
    ctx = {"tenant_id": "t"}
    await extensions.dispatch_hitl_enrich({"skill_id": "s"}, ctx)
    assert seen == ["s"] and ctx["rehearsal"]["summary"] == "one field changes"
    extensions.reset()
    assert extensions.hitl_enrichers == [] and extensions.actuation_guards == []


async def test_actuation_guard_refuses_and_fails_closed():
    action = {"tenant_id": "t", "system": "sandbox", "object_type": "invoice",
              "external_id": "INV-1", "operation": "UPDATE", "payload": {}}
    assert await extensions.guard_actuation(action, {}) is None   # no guard: proceed

    async def allow(a, c):
        return None

    async def refuse(a, c):
        return {"refuse": True, "reason": "the record changed since the rehearsal"}

    async def broken(a, c):
        raise RuntimeError("guard down")

    extensions.add_actuation_guard(allow)
    assert await extensions.guard_actuation(action, {}) is None
    extensions.actuation_guards.clear()
    extensions.add_actuation_guard(refuse)
    assert "record changed" in await extensions.guard_actuation(action, {})
    extensions.actuation_guards.clear()
    extensions.add_actuation_guard(broken)
    reason = await extensions.guard_actuation(action, {})
    assert reason and "Nothing was changed" in reason, "an erroring guard refuses (fail-closed)"

    # Multiple guards: the FIRST refusal wins, later guards are not consulted.
    extensions.actuation_guards.clear()
    extensions.add_actuation_guard(refuse)
    extensions.add_actuation_guard(broken)
    reason = await extensions.guard_actuation(action, {})
    assert reason and "record changed" in reason, "first refusal short-circuits"
    extensions.actuation_guards.clear()


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


def test_periodic_hooks_register_and_reset():
    """The ladder governor's cadence slot: named, positive interval, cleared
    with the rest of the seam so a failed registration leaves no stray job."""
    reg = ExtensionRegistry()

    async def sweep():
        pass

    reg.add_periodic_hook("ladder_sweep", sweep, hours=6)
    assert reg.periodic_hooks == [("ladder_sweep", sweep, 6.0)]
    with pytest.raises(ValueError):
        reg.add_periodic_hook("", sweep, hours=6)
    with pytest.raises(ValueError):
        reg.add_periodic_hook("x", sweep, hours=0)
    reg.reset()
    assert reg.periodic_hooks == []


async def test_scheduler_leader_only_wrapper(monkeypatch):
    """Enterprise periodic hooks run through the same leader guard as core jobs."""
    from app.services import scheduler as sched
    ran = []

    async def fn():
        ran.append(1)

    monkeypatch.setattr(sched, "_is_leader", lambda: False)
    await sched._leader_only(fn)()
    assert ran == []
    monkeypatch.setattr(sched, "_is_leader", lambda: True)
    await sched._leader_only(fn)()
    assert ran == [1]


async def test_writeback_adapters_fill_stubs_but_never_shadow_core_writers():
    from app.services import sync_engine

    async def workday_writer(config, secrets, write):
        return None

    async def rogue_servicenow(config, secrets, write):
        return None

    extensions.add_writeback_adapters({"workday": workday_writer})
    assert extensions.writeback_adapters["workday"] is workday_writer
    with pytest.raises(ValueError, match="shadow core writers"):
        extensions.add_writeback_adapters({"servicenow": rogue_servicenow})
    assert "workday" in sync_engine.WRITEBACK_STUBS

    class _W:
        entity_type, op, external_id, internal_id = "time_off", "UPSERT", "E1", "i1"
        payload, idempotency_key, id = {}, None, "w1"

    # The sync engine consults the seam first: the stub's message is replaced.
    assert await sync_engine._write_via_adapter("workday", None, {}, {}, _W()) is None
    extensions.reset()
    assert extensions.writeback_adapters == {}
    err = await sync_engine._write_via_adapter("workday", None, {}, {}, _W())
    assert err and "customer Workday tenant" in err


def test_grounding_event_is_honest_both_ways():
    from app.api.routes.chat import _grounding_event
    ok = _grounding_event([], [{"content": "x"}])
    assert ok["figures_grounded"] is True and "Every figure" in ok["note"]
    none = _grounding_event([], [])
    assert "No records were retrieved" in none["note"]
    bad = _grounding_event(["38", "3"], [{"content": "x"}])
    assert bad["figures_grounded"] is False and "38, 3" in bad["note"]


def test_mcp_tools_extend_but_never_shadow_core_tools():
    good = {"name": "get_action_contracts", "description": "Typed contracts.",
            "inputSchema": {"type": "object", "properties": {}},
            "forward": {"method": "GET", "path": "/gateway/contracts", "args": "params"}}
    extensions.add_mcp_tools([good])
    assert extensions.mcp_tools[0]["name"] == "get_action_contracts"
    with pytest.raises(ValueError, match="shadow core tools"):
        extensions.add_mcp_tools([{**good, "name": "execute_skill"}])
    with pytest.raises(ValueError, match="malformed"):
        extensions.add_mcp_tools([{**good, "forward": {"method": "PATCH", "path": "/x"}}])
    with pytest.raises(ValueError, match="malformed"):
        extensions.add_mcp_tools([{**good, "forward": {"method": "GET", "path": "no-slash"}}])
    extensions.reset()
    assert extensions.mcp_tools == []


async def test_billing_classifier_can_only_narrow_the_metered_count(monkeypatch):
    """Outcome-verified billing: the classifier's verified count replaces the
    governed-run count but can never exceed it, and an erroring classifier
    leaves the plain count in force."""
    from app.services import usage_rating

    async def fake_scalar(*a, **k):
        return 10

    class _DB:
        async def scalar(self, *a, **k):
            return 10

    async def plan(db, tenant_id):
        return "enterprise"

    monkeypatch.setattr(usage_rating, "plan_for_tenant", plan)
    monkeypatch.setattr(usage_rating, "allowance_for_plan", lambda p: 5)

    async def narrow(db, tenant_id, start, end):
        return {"metered_executions": 7, "by_class": {"autonomous": 4, "assisted": 3, "blocked": 3}}

    async def inflate(db, tenant_id, start, end):
        return {"metered_executions": 99}

    async def broken(db, tenant_id, start, end):
        raise RuntimeError("classifier down")

    extensions.set_billing_classifier(narrow)
    r = await usage_rating.rate_tenant_period(_DB(), "t")
    assert (r["governed_executions"], r["metered_executions"], r["overage_units"]) == (10, 7, 2)
    assert r["metered_by_outcome"]["blocked"] == 3
    extensions.set_billing_classifier(inflate)
    assert (await usage_rating.rate_tenant_period(_DB(), "t"))["metered_executions"] == 10
    extensions.set_billing_classifier(broken)
    r = await usage_rating.rate_tenant_period(_DB(), "t")
    assert r["metered_executions"] == 10 and "metered_by_outcome" not in r
    extensions.reset()
    assert (await usage_rating.rate_tenant_period(_DB(), "t"))["metered_executions"] == 10


# ── autonomy authorizers (F14): on whose authority does the machine act alone? ──

async def test_autonomy_authorizer_returning_none_lets_the_run_proceed():
    seen = []

    async def lends(skill, context):
        seen.append((skill["skill_id"], context["execution_id"]))
        context["authority"] = {"basis": "delegated", "holder": "priya@example.com"}
        return None

    # no authorizer at all: nothing to object
    assert await extensions.authorize_autonomy({"skill_id": "s"}, {"execution_id": "e0"}) is None
    extensions.add_autonomy_authorizer(lends)
    ctx = {"execution_id": "e1"}
    assert await extensions.authorize_autonomy({"skill_id": "s"}, ctx) is None
    assert seen == [("s", "e1")]
    assert ctx["authority"]["holder"] == "priya@example.com", "an authorizer may stamp the basis"


async def test_autonomy_authorizer_first_objection_wins_and_later_ones_are_not_asked():
    asked = []

    def authorizer(name, verdict):
        async def fn(skill, context):
            asked.append(name)
            return verdict
        return fn

    extensions.add_autonomy_authorizer(authorizer("quiet", None))
    # a verdict that neither forces a human nor refuses is not an objection
    extensions.add_autonomy_authorizer(authorizer("shrug", {"note": "fine by me"}))
    extensions.add_autonomy_authorizer(authorizer("falsey", {"force_hitl": False, "reason": "x"}))
    extensions.add_autonomy_authorizer(
        authorizer("first", {"force_hitl": True, "reason": "nobody has lent authority"}))
    extensions.add_autonomy_authorizer(authorizer("second", {"refuse": True, "reason": "no"}))

    verdict = await extensions.authorize_autonomy({"skill_id": "s"}, {"execution_id": "e"})
    assert verdict == {"force_hitl": True, "reason": "nobody has lent authority"}
    assert asked == ["quiet", "shrug", "falsey", "first"], "the objection short-circuits"


async def test_autonomy_authorizer_refuse_verdict_is_returned_as_is():
    refusal = {"refuse": True, "reason": "the grant was revoked", "extra": 1}

    async def refuses(skill, context):
        return refusal

    extensions.add_autonomy_authorizer(refuses)
    assert await extensions.authorize_autonomy({"skill_id": "s"}, {}) is refusal


async def test_autonomy_authorizer_that_raises_fails_closed_naming_the_exception():
    asked = []

    async def broken(skill, context):
        raise ConnectionError("authority ledger unreachable")

    async def never(skill, context):
        asked.append("never")
        return None

    extensions.add_autonomy_authorizer(broken)
    extensions.add_autonomy_authorizer(never)
    verdict = await extensions.authorize_autonomy({"skill_id": "s"}, {"execution_id": "e"})
    assert verdict["force_hitl"] is True, "an unverified authority routes to a human"
    assert "ConnectionError" in verdict["reason"] and "a human decides" in verdict["reason"]
    assert "unreachable" not in verdict["reason"], "the reason names the class, never the message"
    assert asked == [], "the failure short-circuits the remaining authorizers"


def test_registry_reset_clears_autonomy_authorizers():
    reg = ExtensionRegistry()

    async def fn(skill, context):
        return None

    reg.add_autonomy_authorizer(fn)
    assert reg.autonomy_authorizers == [fn]
    reg.reset()
    assert reg.autonomy_authorizers == []
    extensions.add_autonomy_authorizer(fn)
    extensions.reset()
    assert extensions.autonomy_authorizers == []


# Gate 3 harness: the executor's confidence gate driven directly, with a captured HITL
# manager, the tenant ceiling and the department threshold pinned (no database, no model).

class _GateHITL:
    def __init__(self):
        self.calls = []

    async def request_human_confirmation(self, skill, context):
        self.calls.append(context.get("hitl_reason"))
        return {"pending": True, "execution_id": context.get("execution_id"),
                "reason": "Awaiting human approval."}


@pytest.fixture()
def _gate3(monkeypatch):
    """(executor, hitl) with the tenant ceiling at 1.0 and the department threshold at 0.82."""
    from app.agents import runtime
    from app.agents.runtime import AgentExecutor
    from app.services import llm_router as lr

    class _Router:
        def confidence_ceiling(self, model_tier="reasoning"):
            return 1.0

    async def for_tenant(cls, tenant_id):
        return _Router()

    async def threshold(tenant_id, department):
        return 0.82

    async def no_cost(self, context):
        return None

    async def no_mark(execution_id, status):
        return None

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(for_tenant))
    monkeypatch.setattr(runtime, "resolve_min_confidence", threshold)
    monkeypatch.setattr(AgentExecutor, "_gate_cost", no_cost)
    monkeypatch.setattr(AgentExecutor, "_mark_execution_failed", staticmethod(no_mark))
    hitl = _GateHITL()
    return AgentExecutor(None, hitl), hitl


def _recording_authorizer(verdict=None):
    calls = []

    async def authorizer(skill, context):
        calls.append((skill, context))
        return verdict

    return authorizer, calls


_CONFIDENT = {"skill_id": "triage_ticket", "department": "support", "confidence": 0.95}
_GATE_CTX = {"tenant_id": "t", "execution_id": "e-gate3"}


async def test_gate3_never_asks_authority_for_a_high_consequence_skill(_gate3):
    ex, hitl = _gate3
    authorizer, calls = _recording_authorizer({"force_hitl": True, "reason": "unlent"})
    extensions.add_autonomy_authorizer(authorizer)
    skill = {**_CONFIDENT, "skill_id": "wire_funds", "always_hitl": True}
    ctx = dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl(skill, ctx, None, hitl_pre_approved=False)
    assert out["status"] == "PENDING_HITL"
    assert calls == [], "authority is never consumed by a run a human was going to see anyway"
    assert "high-consequence" in ctx["hitl_reason"]
    assert hitl.calls == [ctx["hitl_reason"]]


async def test_gate3_never_asks_authority_when_confidence_is_below_the_threshold(_gate3):
    ex, hitl = _gate3
    authorizer, calls = _recording_authorizer({"force_hitl": True, "reason": "unlent"})
    extensions.add_autonomy_authorizer(authorizer)
    ctx = dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl({**_CONFIDENT, "confidence": 0.5}, ctx, None,
                                         hitl_pre_approved=False)
    assert out["status"] == "PENDING_HITL" and calls == []
    assert "below this department's autonomy threshold" in ctx["hitl_reason"]


async def test_gate3_never_asks_authority_when_an_input_trust_cap_forced_review(_gate3):
    ex, hitl = _gate3
    authorizer, calls = _recording_authorizer({"force_hitl": True, "reason": "unlent"})

    async def suspect(skill, context):
        return {"ceiling": None, "force_hitl": True, "reason": "the input looks injected"}

    extensions.add_confidence_cap(suspect)
    extensions.add_autonomy_authorizer(authorizer)
    ctx = dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), ctx, None, hitl_pre_approved=False)
    assert out["status"] == "PENDING_HITL" and calls == []
    assert ctx["hitl_reason"] == "the input looks injected"


async def test_gate3_never_asks_authority_for_a_run_a_human_already_approved(_gate3):
    ex, hitl = _gate3
    authorizer, calls = _recording_authorizer({"force_hitl": True, "reason": "unlent"})
    extensions.add_autonomy_authorizer(authorizer)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), dict(_GATE_CTX), None,
                                         hitl_pre_approved=True)
    assert out is None and calls == [] and hitl.calls == []


async def test_gate3_asks_authority_for_a_confident_low_consequence_run_and_pauses_on_force(
        _gate3):
    ex, hitl = _gate3
    reason = "No one has lent authority for triage ticket in support."
    authorizer, calls = _recording_authorizer({"force_hitl": True, "reason": reason})
    extensions.add_autonomy_authorizer(authorizer)
    skill, ctx = dict(_CONFIDENT), dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl(skill, ctx, None, hitl_pre_approved=False)
    assert len(calls) == 1 and calls[0][0] is skill and calls[0][1] is ctx
    assert out["status"] == "PENDING_HITL"
    assert ctx["hitl_reason"] == reason, "the approver is told exactly why, in the authorizer's words"
    assert hitl.calls == [reason]


async def test_gate3_force_without_a_reason_still_pauses_with_a_stated_cause(_gate3):
    ex, hitl = _gate3
    authorizer, _ = _recording_authorizer({"force_hitl": True})
    extensions.add_autonomy_authorizer(authorizer)
    ctx = dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), ctx, None, hitl_pre_approved=False)
    assert out["status"] == "PENDING_HITL"
    assert "no one has lent authority" in ctx["hitl_reason"]


async def test_gate3_lets_a_lent_run_through_without_a_human(_gate3):
    ex, hitl = _gate3
    gates = []

    async def watch(context, gate, state, detail):
        gates.append((gate, state, detail))

    async def lends(skill, context):
        context["authority"] = {"basis": "delegated", "holder": "priya@example.com"}
        return None

    extensions.add_gate_stage_hook(watch)
    extensions.add_autonomy_authorizer(lends)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), dict(_GATE_CTX), None,
                                         hitl_pre_approved=False)
    assert out is None and hitl.calls == []
    assert ("authority", "lent", "priya@example.com") in gates
    assert ("hitl", "passed", "") in gates


async def test_gate3_blocks_a_refused_run_instead_of_queueing_it(_gate3):
    ex, hitl = _gate3
    authorizer, calls = _recording_authorizer({"refuse": True, "reason": "grant revoked"})
    extensions.add_autonomy_authorizer(authorizer)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), dict(_GATE_CTX), None,
                                         hitl_pre_approved=False)
    assert len(calls) == 1
    assert out["status"] == "BLOCKED_ACTUATION" and out["reason"] == "grant revoked"
    assert hitl.calls == [], "a refusal is not an approval request"


async def test_gate3_an_erroring_authorizer_pauses_the_run_for_a_human(_gate3):
    ex, hitl = _gate3

    async def broken(skill, context):
        raise RuntimeError("ledger down")

    extensions.add_autonomy_authorizer(broken)
    ctx = dict(_GATE_CTX)
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), ctx, None, hitl_pre_approved=False)
    assert out["status"] == "PENDING_HITL"
    assert "RuntimeError" in ctx["hitl_reason"], "fail-closed: no lent authority, no autonomy"


async def test_gate3_with_no_authorizer_registered_behaves_as_before(_gate3):
    ex, hitl = _gate3
    assert extensions.autonomy_authorizers == []
    out = await ex._gate_confidence_hitl(dict(_CONFIDENT), dict(_GATE_CTX), None,
                                         hitl_pre_approved=False)
    assert out is None and hitl.calls == []
