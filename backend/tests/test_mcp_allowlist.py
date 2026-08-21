"""M3: the per-tenant MCP tool allowlist is enforced.

The executor called execute_tool with allowed_tools left None, so every tenant
agent could call every registered tool. It now derives the allowlist from the
tenant's MCPToolConfig (active tool_ids) and passes it through. A tenant with no
config keeps the prior unrestricted behavior; a configured tenant is restricted
to its active tools."""
import pytest

from app.core.database import AsyncSessionLocal
from app.models.settings import MCPToolConfig
from app.services.skill_executor import SkillExecutionEngine


@pytest.mark.asyncio
async def test_no_config_means_no_restriction():
    eng = SkillExecutionEngine()
    assert await eng._tenant_tool_allowlist("t_none_m3") is None


@pytest.mark.asyncio
async def test_config_restricts_to_active_tools():
    async with AsyncSessionLocal() as s:
        s.add(MCPToolConfig(tenant_id="t_cfg_m3", tool_id="tool_a", is_active=True))
        s.add(MCPToolConfig(tenant_id="t_cfg_m3", tool_id="tool_b", is_active=False))
        await s.commit()

    eng = SkillExecutionEngine()
    allow = await eng._tenant_tool_allowlist("t_cfg_m3")
    assert allow == {"tool_a"}, "only active tools are permitted"


@pytest.mark.asyncio
async def test_allowlist_actually_refuses_a_non_permitted_tool():
    from app.agents.mcp_tools_dynamic.registry import MCPToolRegistry
    reg = MCPToolRegistry()
    names = list(reg.tool_names())
    if not names:
        pytest.skip("no registered tools to probe")
    target = names[0]
    # An allowlist that excludes the target must refuse it.
    res = await reg.execute_tool(target, {}, tenant_id="t_x", allowed_tools=set())
    assert "refus" in str(res).lower() or "not permitted" in str(res).lower() \
        or "allowlist" in str(res).lower()
