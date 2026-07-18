import pytest
from app.services.debate_engine import DebateEngine
from app.models.domain import Skill

@pytest.mark.asyncio
async def test_debate_engine_skips_when_not_required():
    engine = DebateEngine()
    skill = Skill(skill_id="test_skill", confidence=0.99, execution_count=10, compliance_tags=[])
    should_debate, reason = engine.should_debate(skill, {})
    assert not should_debate

@pytest.mark.asyncio
async def test_debate_engine_triggers_on_tier_1_tags():
    engine = DebateEngine()
    skill = Skill(skill_id="test_skill", confidence=0.99, execution_count=10, compliance_tags=["SOX"])
    should_debate, reason = engine.should_debate(skill, {})
    assert should_debate
