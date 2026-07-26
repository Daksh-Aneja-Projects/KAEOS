"""E2E — Agent Interface: the MCP endpoint + Company Skills File export.

Verifies that KAEOS speaks agent: an MCP client can initialize, discover the
tool catalog, read the brain/skills/metrics through it, and execute a skill
through the SAME 7-gate pipeline a human request uses. Also verifies the
Company Skills File export in both formats.
"""
import pytest

pytestmark = pytest.mark.asyncio


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    body = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _call(client, method, params=None, req_id=1):
    r = await client.post("/mcp", json=_rpc(method, params, req_id))
    assert r.status_code == 200, f"{method} → {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get("jsonrpc") == "2.0"
    assert data.get("id") == req_id
    assert "error" not in data, f"{method} errored: {data.get('error')}"
    return data["result"]


class TestMCPHandshake:
    async def test_initialize(self, client):
        result = await _call(client, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "0"},
        })
        assert result["protocolVersion"]
        assert result["serverInfo"]["name"] == "kaeos"
        assert "tools" in result["capabilities"]

    async def test_notification_gets_202(self, client):
        r = await client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert r.status_code == 202

    async def test_ping(self, client):
        assert await _call(client, "ping") == {}

    async def test_unknown_method_is_rpc_error(self, client):
        r = await client.post("/mcp", json=_rpc("no/such/method"))
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32601

    async def test_batch_rejected(self, client):
        r = await client.post("/mcp", json=[_rpc("ping")])
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32600


class TestMCPTools:
    async def test_tools_list(self, client):
        result = await _call(client, "tools/list")
        names = {t["name"] for t in result["tools"]}
        assert names == {
            "query_company_brain", "list_skills", "execute_skill",
            "get_safe_autonomy_rate", "list_pending_approvals",
            "export_skills_file",
        }
        for t in result["tools"]:
            assert t["description"]
            assert t["inputSchema"]["type"] == "object"

    async def test_query_company_brain(self, client):
        result = await _call(client, "tools/call",
                             {"name": "query_company_brain", "arguments": {}})
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"

    async def test_list_skills(self, client):
        result = await _call(client, "tools/call",
                             {"name": "list_skills", "arguments": {}})
        assert result["isError"] is False
        data = result["structuredContent"]
        assert data["total"] >= 1, "seeded tenant should have skills"
        assert isinstance(data["skills"], list)

    async def test_safe_autonomy_rate(self, client):
        result = await _call(client, "tools/call",
                             {"name": "get_safe_autonomy_rate",
                              "arguments": {"days": 30}})
        assert result["isError"] is False
        assert "timeseries" in result["structuredContent"]

    async def test_pending_approvals(self, client):
        result = await _call(client, "tools/call",
                             {"name": "list_pending_approvals", "arguments": {}})
        assert result["isError"] is False

    async def test_unknown_tool_is_tool_error_not_crash(self, client):
        result = await _call(client, "tools/call",
                             {"name": "not_a_tool", "arguments": {}})
        assert result["isError"] is True


class TestSkillsFile:
    async def test_markdown_export(self, client):
        r = await client.get("/brain/skills-file")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert "# KAEOS Company Skills File" in r.text
        assert "## Operating rules" in r.text
        assert "## Executable skills" in r.text
        assert "7-gate pipeline" in r.text

    async def test_json_export(self, client):
        r = await client.get("/brain/skills-file", params={"format": "json"})
        assert r.status_code == 200
        data = r.json()
        assert data["artifact"] == "kaeos-company-skills-file"
        assert data["counts"]["skills"] == len(data["skills"])
        assert data["counts"]["rules"] == len(data["rules"])
        for s in data["skills"][:3]:
            assert "skill_id" in s and "confidence" in s

    async def test_export_via_mcp_tool(self, client):
        result = await _call(client, "tools/call",
                             {"name": "export_skills_file",
                              "arguments": {"format": "markdown"}})
        assert result["isError"] is False
        assert "# KAEOS Company Skills File" in result["content"][0]["text"]


class TestGovernedExecutionViaMCP:
    @pytest.mark.ollama
    async def test_execute_skill_runs_the_real_pipeline(self, client, has_ollama):
        """An MCP agent executing a skill hits the same 7-gate pipeline:
        the outcome must be a real pipeline status, and PENDING_HITL counts
        as success — that is governance working."""
        if not has_ollama:
            pytest.skip("Ollama required")
        skills = (await _call(client, "tools/call",
                              {"name": "list_skills", "arguments": {}}
                              ))["structuredContent"]["skills"]
        assert skills, "need at least one seeded skill"
        target = max(skills, key=lambda s: s.get("confidence") or 0)
        result = await _call(client, "tools/call", {
            "name": "execute_skill",
            "arguments": {
                "skill_id": target["skill_id"],
                "intent": "Run a routine governed check of this item.",
                "context": {"source": "mcp-e2e"},
            },
        }, req_id=42)
        assert result["isError"] is False, result["content"][0]["text"][:300]
        data = result["structuredContent"]
        assert data["execution_id"]
        assert data["status"], "pipeline must report a status"
        # Any of these means the pipeline genuinely ran and decided.
        assert any(k in data["status"] for k in
                   ("SUCCESS", "PENDING", "BLOCKED", "FAILED", "HITL"))
