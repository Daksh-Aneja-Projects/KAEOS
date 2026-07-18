"""
Authoring-time step validation: a skill step must carry instruction text in
'action', 'prompt', or 'name' - otherwise it reaches the model as ACTION
"unknown" and fails silently at run time.
"""
import pytest

from app.schemas.skills import SkillStep, validate_steps


def test_action_shape_valid():
    s = SkillStep(id="s1", action="Audit the payroll totals", tool="none")
    assert s.action == "Audit the payroll totals"


def test_prompt_shape_valid():
    out = validate_steps([{"step": 1, "name": "Classify", "prompt": "Classify this ticket"}])
    assert out[0]["prompt"] == "Classify this ticket"


def test_instructionless_step_rejected():
    with pytest.raises(ValueError, match="no instruction text"):
        validate_steps([{"step": 1, "tool": "none"}])


def test_blank_instruction_rejected():
    with pytest.raises(ValueError, match="step 1 invalid"):
        validate_steps([{"action": "   "}])


def test_non_dict_step_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        validate_steps(["just a string"])


def test_extra_fields_preserved():
    out = validate_steps([{"name": "Do", "custom_meta": {"a": 1}}])
    assert out[0]["custom_meta"] == {"a": 1}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
