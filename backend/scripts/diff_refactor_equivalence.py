"""Differential equivalence harness for behaviour-preserving refactors.

Proves a refactor changed nothing by RUNNING both versions, rather than by
reading them. It loads each ORIGINAL module (extracted from a pre-refactor git
ref) as a standalone module, runs it and the refactored one over the same input
matrix with the boundary call stubbed to capture its arguments, and compares the
captured payloads exactly.

This is the harness that proved the ten-department gated_runner consolidation
(app/agents/department_gate.py) across 4563 input combinations with 0
mismatches. It caught two real behaviours that careful code review had missed:
engineering's per-skill DEPLOY_COMPLIANCE/confidence overrides, and lending's
has_human_approver normalisation. Reuse it for the remaining de-duplication
milestones (router endpoint families, seed scaffolds, the runtime.py gate split)
rather than trusting inspection.

Usage:
    # 1. extract the pre-refactor originals
    mkdir -p /tmp/old
    for d in hr finance legal ...; do
      git show <PRE_REFACTOR_REF>:backend/app/$d/agents/gated_runner.py > /tmp/old/$d.py
    done
    # 2. compare
    cd backend && python scripts/diff_refactor_equivalence.py /tmp/old

Exits non-zero and prints the differing payloads when any combination diverges.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from app.agents.runtime import AgentExecutor  # noqa: E402

OLD_DIR = sys.argv[1]

DEPARTMENTS = [
    "engineering", "finance", "healthcare", "hr", "legal",
    "lending", "operations", "procurement", "sales", "support",
]

# Skills with known special handling, plus a generic one per department.
SPECIAL_SKILLS = {
    "engineering": ["engineering_deploy_approval"],
    "sales": ["sales_proposal_gen"],
    "support": ["support_auto_resolve"],
}

TAG_CASES = [None, [], ["GDPR"], ["SOX"], ["GAAP"], ["PCI"], ["CCPA"], ["HIPAA"], ["SOX", "GDPR"]]

CONTEXT_CASES = [
    {},
    {"legal_basis": "contract"},
    {"legal_basis": ""},
    {"amount": 100},
    {"amount": 0},
    {"pci_validated": True},
    {"data_processing_basis_logged": False},
    {"financial_amount_logged": False},
    {"has_human_approver": "alice@example.com"},
    {"has_human_approver": True},
    {"maker": "bob", "approver": "carol"},
    {"execution_id": "fixed-exec-id"},
    {"legal_basis": "consent", "amount": 42, "pci_validated": True,
     "has_human_approver": "dana", "execution_id": "fixed-exec-id"},
]

CONFIDENCE_CASES = [None, 0.5, 0.99]


def load_old(dept: str):
    path = os.path.join(OLD_DIR, f"{dept}.py")
    spec = importlib.util.spec_from_file_location(f"_old_{dept}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def freeze(skill_dict, ctx):
    """Normalize the captured payload so it can be compared and printed."""
    def enc(v):
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        return f"<{type(v).__name__}>"

    skill_obj = ctx.get("_skill_obj")
    skill_fields = None
    if skill_obj is not None:
        skill_fields = {
            k: enc(getattr(skill_obj, k, None))
            for k in ("skill_id", "department", "domain", "confidence",
                      "confidence_tier", "execution_count", "success_rate")
        }
        skill_fields["compliance_tags"] = list(getattr(skill_obj, "compliance_tags", []) or [])
        skill_fields["steps"] = getattr(skill_obj, "steps", None)

    return {
        "skill_dict": {k: (list(v) if isinstance(v, list) else enc(v))
                       for k, v in sorted(skill_dict.items())},
        "ctx": {k: enc(v) for k, v in sorted(ctx.items()) if k != "_skill_obj"},
        "skill_obj": skill_fields,
    }


async def capture(fn, skill_id, tags, conf, context):
    captured = {}

    async def stub(self, skill_dict, ctx, **kw):
        captured["payload"] = freeze(skill_dict, ctx)
        captured["kwargs"] = sorted(kw)
        return {"status": "SUCCESS_CLEAN"}

    original = AgentExecutor.execute_skill
    AgentExecutor.execute_skill = stub
    try:
        kwargs = {"compliance_tags": tags}
        if conf is not None:
            kwargs["confidence"] = conf
        await fn(skill_id, [{"step": 1, "name": "S", "prompt": "p"}],
                 dict(context), "tenant_acme", **kwargs)
    finally:
        AgentExecutor.execute_skill = original
    return captured


async def main():
    total = mismatches = 0
    report = []

    for dept in DEPARTMENTS:
        old_mod = load_old(dept)
        new_mod = importlib.import_module(f"app.{dept}.agents.gated_runner")
        fname = f"run_gated_{dept}_skill"
        old_fn, new_fn = getattr(old_mod, fname), getattr(new_mod, fname)

        skills = SPECIAL_SKILLS.get(dept, []) + [f"{dept}_generic_skill"]
        for skill_id in skills:
            for tags in TAG_CASES:
                for conf in CONFIDENCE_CASES:
                    for context in CONTEXT_CASES:
                        total += 1
                        # execution_id is a fresh uuid4 unless the context pins
                        # one; compare that key only when it is deterministic.
                        pinned = "execution_id" in context
                        o = await capture(old_fn, skill_id, tags, conf, context)
                        n = await capture(new_fn, skill_id, tags, conf, context)
                        if not pinned:
                            for c in (o, n):
                                c["payload"]["ctx"].pop("execution_id", None)
                        if o != n:
                            mismatches += 1
                            if len(report) < 12:
                                report.append({
                                    "dept": dept, "skill_id": skill_id,
                                    "tags": tags, "confidence": conf,
                                    "context": context,
                                    "old": o, "new": n,
                                })
        print(f"  {dept:12} done")

    print(f"\n=== {total} input combinations compared, {mismatches} mismatches ===")
    for r in report:
        print("\n--- MISMATCH ---")
        print(json.dumps(r, indent=2, default=str)[:3000])
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
