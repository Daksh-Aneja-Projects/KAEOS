"""
Regression: the skill executor must pass the step's instruction text to the
LLM regardless of which field the agent authored it in.

Agents write steps in two shapes:
  {"id", "action", "tool", "condition", "thresholds"}   (workforce shape)
  {"step", "name", "prompt"}                             (domain-agent shape)

The executor formatted only step["action"] into the LLM prompt, so the second
shape's instruction was silently dropped - the model saw ACTION: unknown and
(with strict models) refused the step, failing the whole skill as
FAILED_RULE_MISMATCH. Found live via scripts/validate_domain_agents.py.
"""
import asyncio

import pytest

from app.services.skill_executor import SkillExecutionEngine


class _CapturingLLM:
    def __init__(self, reply='{"status": "SUCCESS", "decision": "ok", "confidence": 0.9}'):
        self.prompts = []
        self.reply = reply

    async def complete(self, prompt, system_prompt=None, model_tier=None,
                       temperature=None, max_tokens=None):
        self.prompts.append(prompt)
        return self.reply


def _run_step(step):
    engine = SkillExecutionEngine.__new__(SkillExecutionEngine)
    engine.llm = _CapturingLLM()
    engine.tool_registry = None
    out = asyncio.run(engine._execute_step(
        step=step, step_num=1, total_steps=1, skill_id="t", tenant_id="t",
        context={"instruction": "ctx"}, prior_chain=[],
    ))
    return out, engine.llm.prompts


def test_prompt_shape_reaches_llm():
    step = {"step": 1, "name": "Classify",
            "prompt": "Classify severity from: server room flooding"}
    out, prompts = _run_step(step)
    assert out["status"] == "SUCCESS"
    assert any("server room flooding" in p for p in prompts), \
        "step prompt text never reached the LLM"


def test_action_shape_still_works():
    step = {"id": "s1", "action": "Audit the payroll totals", "tool": "none"}
    out, prompts = _run_step(step)
    assert out["status"] == "SUCCESS"
    assert any("Audit the payroll totals" in p for p in prompts)


def test_name_only_shape_falls_back():
    step = {"step": 1, "name": "Assess Compliance"}
    out, prompts = _run_step(step)
    assert any("Assess Compliance" in p for p in prompts)
    assert not any("ACTION: unknown" in p for p in prompts)


def test_negative_verdict_is_not_a_step_failure():
    # Models conflate "the obligation FAILS compliance" with step status FAILED.
    # A completed analysis (decision present, no error) must count as SUCCESS.
    engine = SkillExecutionEngine.__new__(SkillExecutionEngine)
    engine.llm = _CapturingLLM(
        '{"status": "FAILED", "decision": {"compliant": false, "gaps": ["no evidence"]}, "error": null}'
    )
    engine.tool_registry = None
    out = asyncio.run(engine._execute_step(
        step={"step": 1, "name": "Assess"}, step_num=1, total_steps=1,
        skill_id="t", tenant_id="t", context={}, prior_chain=[],
    ))
    assert out["status"] == "SUCCESS"
    assert out["decision"]["compliant"] is False


def test_genuine_failure_still_fails():
    engine = SkillExecutionEngine.__new__(SkillExecutionEngine)
    engine.llm = _CapturingLLM(
        '{"status": "FAILED", "decision": null, "error": "context missing required fields"}'
    )
    engine.tool_registry = None
    out = asyncio.run(engine._execute_step(
        step={"step": 1, "name": "Assess"}, step_num=1, total_steps=1,
        skill_id="t", tenant_id="t", context={}, prior_chain=[],
    ))
    assert out["status"] == "FAILED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
