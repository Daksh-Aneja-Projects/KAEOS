"""A2A (Agent2Agent) adapter: the Agent Card is public and unauthenticated
(same reasoning as OIDC discovery), JSON-RPC 2.0 framing matches the /mcp
adapter's own conventions, a message must name a skill_id explicitly
(never a guessed/invented intent-classification), and the real execution
result translates into the right A2A task state."""
import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _dev_mode():
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = True
    yield
    settings.DEV_MODE = prev


async def test_agent_card_is_public_and_shaped_correctly(async_client: AsyncClient):
    # No Authorization header at all - discovery must work before a caller
    # knows how to authenticate to anything else.
    res = await async_client.get("/.well-known/agent-card.json")
    assert res.status_code == 200
    card = res.json()
    assert card["name"] == "kaeos"
    assert card["url"].endswith("/a2a")
    assert "/api/v1" not in card["url"]   # root-mounted, not under the API prefix
    assert card["skills"][0]["id"] == "execute_skill"

    # The pre-1.0 spec alias resolves to the same document.
    res2 = await async_client.get("/.well-known/agent.json")
    assert res2.status_code == 200 and res2.json()["name"] == "kaeos"


async def test_malformed_and_unknown_requests_are_honest_jsonrpc_errors(async_client: AsyncClient):
    bad_json = await async_client.post("/a2a", content=b"{not json",
                                       headers={"Authorization": "Bearer x"})
    assert bad_json.json()["error"]["code"] == -32700

    not_rpc = await async_client.post("/a2a", json={"hello": "world"},
                                      headers={"Authorization": "Bearer x"})
    assert not_rpc.json()["error"]["code"] == -32600

    unknown_method = await async_client.post(
        "/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "nonsense"},
        headers={"Authorization": "Bearer x"})
    assert unknown_method.json()["error"]["code"] == -32601


async def test_message_without_skill_id_is_rejected_never_guessed(async_client: AsyncClient):
    """The honesty boundary this module's docstring commits to: no
    free-text intent routing, ever."""
    res = await async_client.post(
        "/a2a", headers={"Authorization": "Bearer x"},
        json={"jsonrpc": "2.0", "id": 1, "method": "message/send",
              "params": {"message": {"parts": [
                  {"kind": "text", "text": "please do something useful"}]}}})
    task = res.json()["result"]
    assert task["status"]["state"] == "rejected"
    assert "skill_id" in task["artifacts"][0]["parts"][0]["text"]


async def test_message_send_forwards_to_execute_skill_and_maps_task_state(
        async_client: AsyncClient, monkeypatch):
    """The real wiring: a DataPart naming a skill_id forwards to
    /skills/{id}/execute on the A2A channel (not mislabeled as MCP), and
    the real execution status maps to the documented A2A task state."""
    import httpx

    from app.api.routes import agent_interface

    calls = []

    async def fake_forward(request, method, path, params=None, json_body=None, channel="mcp"):
        calls.append((method, path, json_body, channel))
        return httpx.Response(200, json={"status": "PENDING_HITL", "execution_id": "e1"})

    monkeypatch.setattr(agent_interface, "_forward", fake_forward)

    message = {"parts": [{"kind": "data",
                          "data": {"skill_id": "handle_refund_request",
                                  "intent": "refund order #1"}}]}
    payload = {"jsonrpc": "2.0", "id": 7, "method": "message/send",
              "params": {"message": message}}
    res = await async_client.post("/a2a", headers={"Authorization": "Bearer x"}, json=payload)
    body = res.json()
    assert body["id"] == 7
    task = body["result"]
    assert task["status"]["state"] == "input-required"   # PENDING_HITL's mapping
    assert task["artifacts"][0]["parts"][0]["data"]["execution_id"] == "e1"

    method, path, json_body, channel = calls[-1]
    assert path.endswith("/skills/handle_refund_request/execute")
    assert json_body == {"intent": "refund order #1", "context": {}}
    assert channel == "a2a"   # never mislabeled as MCP

    # tasks/get on that same id re-serves the same task.
    get_res = await async_client.post(
        "/a2a", headers={"Authorization": "Bearer x"},
        json={"jsonrpc": "2.0", "id": 8, "method": "tasks/get",
              "params": {"id": task["id"]}})
    assert get_res.json()["result"]["id"] == task["id"]

    unknown = await async_client.post(
        "/a2a", headers={"Authorization": "Bearer x"},
        json={"jsonrpc": "2.0", "id": 9, "method": "tasks/get",
              "params": {"id": "never-existed"}})
    assert unknown.json()["error"]["code"] == -32001


async def test_tasks_send_alias_behaves_identically_to_message_send(
        async_client: AsyncClient, monkeypatch):
    """Interop hedge for the pre-1.0 method name some real A2A clients still
    send - same handler, same result shape."""
    import httpx

    from app.api.routes import agent_interface

    async def fake_forward(request, method, path, params=None, json_body=None, channel="mcp"):
        return httpx.Response(200, json={"status": "SUCCESS_CLEAN"})

    monkeypatch.setattr(agent_interface, "_forward", fake_forward)

    res = await async_client.post(
        "/a2a", headers={"Authorization": "Bearer x"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/send",
              "params": {"message": {"parts": [
                  {"kind": "data", "data": {"skill_id": "s1"}}]}}})
    assert res.json()["result"]["status"]["state"] == "completed"
