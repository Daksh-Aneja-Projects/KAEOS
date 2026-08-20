"""Differential equivalence harness for the M2.2 gate-pipeline split.

Same pattern as diff_refactor_equivalence.py (M0) and diff_router_equivalence.py
(S2): load the PRE-refactor ``app/agents/runtime.py`` from a git ref as a
standalone module, stub every boundary identically on the OLD and the NEW
``AgentExecutor``, run ``_run_gates`` over a structured input matrix that
reaches every branch of every gate, and compare exactly:

  * the returned result (or raised exception),
  * the full ordered sequence of boundary calls (compliance, fairness, hitl,
    debate, executor, actuator, audit, activity feed, gate emissions, blocked
    persistence, failure marking, memory), and
  * the JSON-safe context mutations the pipeline made.

``_run_gates`` (not ``execute_skill``) is the seam on purpose: the M6.1 release
block, tracing and latency bookkeeping above it are not being refactored, and
stubbing them would only blur the comparison.

Usage:
    cd backend && python scripts/diff_gate_equivalence.py <OLD_GIT_REF>

    # the M2.2 baseline (the commit the split starts from):
    python scripts/diff_gate_equivalence.py f513bc8

Exit 0 on zero mismatches. Proven able to fail: flip any branch's status
string or reorder a boundary call in the working tree and it reports the exact
case and the first divergence.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import types

import logging
logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("SECRET_KEY", "diff-gate-harness")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

OLD_REF = sys.argv[1] if len(sys.argv) > 1 else "HEAD"

STATE = {"total": 0}
MISMATCHES: list[dict] = []


def load_old(ref: str):
    src = subprocess.run(
        ["git", "show", f"{ref}:backend/app/agents/runtime.py"],
        capture_output=True, text=True, check=True, cwd="..",
    ).stdout
    spec = importlib.util.spec_from_loader("old_runtime", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__file__"] = f"<git:{ref}>"
    exec(compile(src, f"<git:{ref}>", "exec"), mod.__dict__)
    return mod


def enc(v):
    try:
        return json.loads(json.dumps(v, sort_keys=True, default=str))
    except Exception:
        return str(v)


# ── Boundary stubs. One factory per run; every call lands in `cap` in order. ──

class Cap:
    def __init__(self):
        self.calls: list = []

    def rec(self, name, **kw):
        self.calls.append({name: enc(kw)})


class StubCompliance:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg
        self.pre_calls = 0

    async def check_before_execution(self, tags, context):
        self.pre_calls += 1
        # First call is Gate 1; a second call is Gate 5b's write re-gate.
        which = "gate1" if self.pre_calls == 1 else "gate5b"
        self.cap.rec(f"compliance.{which}", tags=list(tags))
        return list(self.cfg["gate1" if which == "gate1" else "write_violations"]) \
            if which == "gate5b" else list(self.cfg["violations"])

    def enforce_audit_requirements(self, tags, context):
        self.cap.rec("compliance.audit", tags=list(tags))
        return self.cfg["audit_passed"]


class StubFairness:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg

    def requires_fairness_check(self, skill_obj, context):
        self.cap.rec("fairness.requires", required=self.cfg["required"])
        return self.cfg["required"]

    async def score_fairness(self, skill_obj, context, *, tenant_id, execution_id):
        self.cap.rec("fairness.score", tenant_id=tenant_id)
        return dict(self.cfg["result"])

    async def override_block(self, audit_log_id, tenant_id, approver, note):
        self.cap.rec("fairness.override", audit_log_id=audit_log_id,
                     approver=approver, note=note)


class StubHitl:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg

    async def request_human_confirmation(self, skill, context):
        self.cap.rec("hitl.request", skill_id=skill.get("skill_id"))
        return dict(self.cfg["decision"])


class StubDebate:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg

    def should_debate(self, skill_obj, context):
        self.cap.rec("debate.should", should=self.cfg["should"])
        return self.cfg["should"], "matrix"

    async def run_debate(self, skill_obj, context, *, execution_id, tenant_id):
        self.cap.rec("debate.run", execution_id=bool(execution_id))
        t = types.SimpleNamespace()
        t.id = "transcript-1"
        t.arbitrator_decision = {"decision": self.cfg["decision"],
                                 "rationale": "matrix rationale"}
        return t


class StubExec:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg

    async def run(self, *, skill, context, execution_id, tenant_id, skill_obj,
                  compliance_warnings):
        self.cap.rec("exec.run", execution_id=bool(execution_id),
                     warnings=enc(compliance_warnings))
        return dict(self.cfg["exec_result"])


class StubFeed:
    def __init__(self, cap):
        self.cap = cap

    async def emit(self, **kw):
        self.cap.rec("feed.emit", event_type=str(kw.get("event_type")),
                     title=kw.get("title"))


class StubActuator:
    def __init__(self, cap, cfg):
        self.cap, self.cfg = cap, cfg

    async def apply_action(self, db, **kw):
        self.cap.rec("actuator.apply", **{k: kw.get(k) for k in
                     ("system", "object_type", "external_id", "operation",
                      "execution_id", "actor", "idempotency_key")})
        if self.cfg["apply"] == "raise":
            raise RuntimeError("actuator down")
        rec = types.SimpleNamespace()
        rec.id = "act-1"
        rec.system = kw.get("system")
        rec.external_id = kw.get("external_id")
        rec.status = "APPLIED"
        return rec

    async def reverse_action(self, db, *, tenant_id, action_id, actor):
        self.cap.rec("actuator.reverse", action_id=action_id, actor=actor)
        if self.cfg["reverse"] == "raise":
            raise RuntimeError("compensation down")
        return {"status": "REVERSED"}


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def patch_module(mod, cap, cfg):
    """Patch the module-level boundaries both versions share."""
    saved = {}

    def put(name, val):
        saved[name] = mod.__dict__.get(name)
        mod.__dict__[name] = val

    async def _persist_blocked(execution_id, tenant_id, skill, status, reason,
                               duration_ms=0):
        cap.rec("persist_blocked", status=status, reason=reason)
    put("persist_blocked_execution", _persist_blocked)

    async def _resolve(tenant_id, department):
        cap.rec("resolve_threshold", department=department)
        if cfg["threshold"] == "raise":
            raise RuntimeError("dial down")
        return cfg["threshold"]
    put("resolve_min_confidence", _resolve)

    def _high(x):
        # Same answer for the dict and the ORM row, like a tag-driven check.
        return cfg["high_consequence"]
    put("is_high_consequence", _high)

    class _Router:
        @staticmethod
        async def for_tenant(tenant_id):
            cap.rec("router.for_tenant")
            if cfg["ceiling"] == "raise":
                raise RuntimeError("byok probe down")
            r = types.SimpleNamespace()
            r.confidence_ceiling = lambda kind: cfg["ceiling"]
            return r
    put("LLMRouter", _Router)

    class _Settings:
        FAILSAFE_CONFIDENCE_CEILING = 0.55
    put("get_settings", lambda: _Settings())

    put("AsyncSessionLocal", _FakeSession)
    put("Actuator", StubActuator(cap, cfg))

    async def _mark_failed(execution_id, status):
        cap.rec("mark_failed", status=status)
    # Static method on the class in both versions.
    saved["_mark_execution_failed"] = mod.AgentExecutor._mark_execution_failed
    mod.AgentExecutor._mark_execution_failed = staticmethod(_mark_failed)
    return saved


def restore_module(mod, saved):
    for name, val in saved.items():
        if name == "_mark_execution_failed":
            mod.AgentExecutor._mark_execution_failed = val
        else:
            mod.__dict__[name] = val


CTX_SNAPSHOT_KEYS = (
    "execution_id", "tenant_id", "_skill_id_name", "_compliance_warnings",
    "fairness_review_log_id", "fairness_review_flagged",
)


def matrix():
    """Structured, branch-reaching enumeration - not a blind cross product."""
    base = dict(
        department="operations", skill_tags=["SOX"], obj_tags=["SOX"],
        confidence=0.9, threshold=0.5, ceiling=0.95, high_consequence=False,
        pre_approved=False, review_log_id=False, has_approver=False,
        skill_obj=True, required=False,
        result={"passed": True},
        violations=[], write_violations=[],
        decision={"pending": True, "execution_id": "exec-matrix01",
                  "reason": "Awaiting human approval"},
        should=False, debate_decision="PROCEED",
        exec_result={"status": "SUCCESS_CLEAN", "reasoning_chain": [],
                     "steps_completed": 1, "duration_ms": 5, "cost": {"usd": 0.02}},
        actuation=None, apply="ok", reverse="ok", audit_passed=True,
    )

    def mk(**over):
        cfg = dict(base)
        cfg.update(over)
        cfg["result"] = dict(cfg["result"])
        cfg["exec_result"] = dict(cfg["exec_result"])
        # run_debate reads cfg["decision"] for HITL and cfg["debate_decision"]
        # for the arbiter - map the stub fields.
        cfg["decision"] = dict(cfg["decision"])
        return cfg

    blocker = [{"severity": "BLOCKER", "reason": "no lawful basis"}]
    warn = [{"severity": "WARNING", "reason": "heads up"}]
    fair_block = {"passed": False, "score": 0.4,
                  "flagged_attributes": ["age"], "rationale": "adverse",
                  "audit_log_id": "flog-1"}

    cases = []

    # Gate 1: compliance verdicts, with and without concurrent fairness.
    for required in (False, True):
        for viol, tag in ((([], "clean")), ((warn, "warn")), ((blocker, "block"))):
            cases.append((f"g1-{tag}-fair{required}",
                          mk(violations=viol, required=required)))

    # Gate 2: fairness blocked - the plain pause, and both override arms.
    cases.append(("g2-blocked-pause", mk(required=True, result=fair_block)))
    cases.append(("g2-blocked-preapproved-no-marker",
                  mk(required=True, result=fair_block, pre_approved=True)))
    cases.append(("g2-blocked-override",
                  mk(required=True, result=fair_block, pre_approved=True,
                     review_log_id=True, has_approver=True)))
    cases.append(("g2-blocked-override-anon",
                  mk(required=True, result=fair_block, pre_approved=True,
                     review_log_id=True)))

    # Gate 3: threshold routing, high consequence, ceiling failure, HITL arms.
    cases.append(("g3-below-threshold", mk(threshold=0.95)))
    cases.append(("g3-high-consequence", mk(high_consequence=True)))
    cases.append(("g3-ceiling-raises", mk(ceiling="raise")))
    cases.append(("g3-ceiling-caps", mk(ceiling=0.3)))
    cases.append(("g3-threshold-raises", mk(threshold="raise")))
    cases.append(("g3-hitl-rejects",
                  mk(threshold=0.95,
                     decision={"pending": False, "approved": False,
                               "reason": "no thanks"})))
    cases.append(("g3-hitl-silent-approve",
                  mk(threshold=0.95, decision={"pending": False})))

    # Gate 4: debate arms (and no skill_obj skips it entirely).
    cases.append(("g4-no-skill-obj", mk(skill_obj=False)))
    cases.append(("g4-debate-block", mk(should=True, debate_decision="BLOCK")))
    cases.append(("g4-debate-escalate", mk(should=True, debate_decision="ESCALATE")))
    cases.append(("g4-debate-proceed", mk(should=True, debate_decision="PROCEED")))
    cases.append(("g4-preapproved-skips-debate",
                  mk(should=True, debate_decision="BLOCK", pre_approved=True)))

    # Gate 5: executor failure surfaces as-is.
    cases.append(("g5-exec-fails",
                  mk(exec_result={"status": "FAILED_RULE_MISMATCH",
                                  "reasoning_chain": [], "steps_completed": 0,
                                  "duration_ms": 3, "cost": None})))

    # Gate 5b: actuation arms.
    act = {"system": "erp", "object_type": "invoice", "external_id": "inv-9",
           "operation": "UPDATE", "payload": {"n": 1}, "idempotency_key": "k1"}
    cases.append(("g5b-ok", mk(actuation=act)))
    cases.append(("g5b-ok-approver", mk(actuation=act, has_approver=True)))
    cases.append(("g5b-apply-raises", mk(actuation=act, apply="raise")))
    cases.append(("g5b-write-blocked",
                  mk(actuation=act, write_violations=blocker)))
    cases.append(("g5b-untagged-finance",
                  mk(actuation=act, department="finance", skill_tags=[],
                     obj_tags=[], write_violations=blocker)))
    cases.append(("g5b-untagged-other-skips-regate",
                  mk(actuation=act, skill_tags=[], obj_tags=[])))

    # Gate 6: audit arms, with and without a committed write to compensate.
    cases.append(("g6-audit-fails-no-write", mk(audit_passed=False)))
    cases.append(("g6-audit-fails-reversed",
                  mk(actuation=act, audit_passed=False)))
    cases.append(("g6-audit-fails-reverse-raises",
                  mk(actuation=act, audit_passed=False, reverse="raise")))

    # Warnings must ride through to the executor and the success payload.
    cases.append(("g6-success-with-warnings", mk(violations=warn)))
    cases.append(("g6-success-with-warnings-actuation",
                  mk(violations=warn, actuation=act)))

    # Pre-approved straight-through (mission/HITL resume) incl. actuation.
    cases.append(("pre-approved-clean", mk(pre_approved=True)))
    cases.append(("pre-approved-actuation",
                  mk(pre_approved=True, actuation=act, has_approver=True)))
    return cases


async def main():
    old_mod = load_old(OLD_REF)
    import app.agents.runtime as new_mod

    for label, cfg in matrix():
        # StubHitl reads cfg["decision"] (the human's verdict); StubDebate gets
        # a view where "decision" resolves to the arbiter verdict instead.
        merged = dict(cfg)
        merged["debate_verdict"] = cfg["debate_decision"]
        o = await run_one_wired(old_mod, merged, label)
        n = await run_one_wired(new_mod, merged, label)
        STATE["total"] += 1
        if o != n:
            MISMATCHES.append({"case": label, "old": o, "new": n})

    print(f"\n=== {STATE['total']} pipeline runs compared against {OLD_REF}, "
          f"{len(MISMATCHES)} mismatches ===")
    for m in MISMATCHES[:8]:
        print("\n--- MISMATCH:", m["case"], "---")
        oc, nc = m["old"], m["new"]
        if oc["out"] != nc["out"]:
            print(" result OLD:", json.dumps(oc["out"])[:600])
            print(" result NEW:", json.dumps(nc["out"])[:600])
        if oc["ctx"] != nc["ctx"]:
            print(" ctx OLD:", json.dumps(oc["ctx"])[:400])
            print(" ctx NEW:", json.dumps(nc["ctx"])[:400])
        for i, (a, b) in enumerate(zip(oc["calls"], nc["calls"])):
            if a != b:
                print(f" first call divergence at #{i}:")
                print("  OLD:", json.dumps(a)[:300])
                print("  NEW:", json.dumps(b)[:300])
                break
        if len(oc["calls"]) != len(nc["calls"]):
            print(f" call-count OLD={len(oc['calls'])} NEW={len(nc['calls'])}")
    return 1 if MISMATCHES else 0


class _DebateView:
    """cfg proxy whose "decision" key resolves to the arbiter verdict."""

    def __init__(self, base):
        self._b = base

    def __getitem__(self, k):
        if k == "decision":
            return self._b["debate_verdict"]
        return self._b[k]


async def run_one_wired(mod, cfg, label):
    return await _run(mod, cfg, _DebateView(cfg), label)


async def _run(mod, cfg, debate_cfg, label):
    cap = Cap()
    saved = patch_module(mod, cap, cfg)
    try:
        ex = mod.AgentExecutor(StubCompliance(cap, cfg), StubHitl(cap, cfg))
        ex._fairness_engine = StubFairness(cap, cfg)
        ex._debate_engine = StubDebate(cap, debate_cfg)
        ex._activity_feed = StubFeed(cap)
        ex._exec_engine = StubExec(cap, cfg)

        async def _emit(context, gate, state, detail=""):
            cap.rec("gate", gate=gate, state=state, detail=detail)
        ex._emit_gate = _emit

        async def _cost(context):
            cap.rec("gate_cost")
            return {"usd": 0.01}
        ex._gate_cost = _cost

        async def _recall(context, skill):
            cap.rec("memory.recall")
        ex._recall_memory = _recall

        async def _store(context, skill, result):
            cap.rec("memory.store", status=result.get("status"))
        ex._store_memory = _store

        skill = {
            "skill_id": "matrix.skill",
            "department": cfg["department"],
            "compliance_tags": list(cfg["skill_tags"]),
            "confidence": cfg["confidence"],
            "steps": [{"id": "s1"}],
        }
        if cfg["actuation"] is not None:
            skill["actuation"] = dict(cfg["actuation"])
        skill_obj = None
        if cfg["skill_obj"]:
            skill_obj = types.SimpleNamespace()
            skill_obj.compliance_tags = list(cfg["obj_tags"])
            skill_obj.department = cfg["department"]
        context = {
            "tenant_id": "tenant_matrix",
            "execution_id": "exec-matrix01",
            "_skill_obj": skill_obj,
        }
        if cfg["review_log_id"]:
            context["fairness_review_log_id"] = "flog-1"
        if cfg["has_approver"]:
            context["has_human_approver"] = "approver@matrix"
        try:
            result = await ex._run_gates(
                skill, context, hitl_pre_approved=cfg["pre_approved"])
            out = ["return", enc(result)]
        except Exception as e:  # noqa: BLE001
            out = ["raise", type(e).__name__, str(e)]
        ctx_snap = {k: enc(context.get(k)) for k in CTX_SNAPSHOT_KEYS}
        return {"out": out, "calls": cap.calls, "ctx": ctx_snap}
    finally:
        restore_module(mod, saved)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
