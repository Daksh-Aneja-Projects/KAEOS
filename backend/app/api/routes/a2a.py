"""KAEOS speaks agent, surface 2: A2A (Agent2Agent).

Two endpoints:

1. ``GET /.well-known/agent-card.json`` (and the ``/.well-known/agent.json``
   alias some older A2A clients still probe) - the Agent Card: what KAEOS
   is, what skills it exposes, where to send tasks.
2. ``POST /a2a`` - JSON-RPC 2.0. Supports ``message/send`` (and the
   ``tasks/send`` alias some clients on an earlier spec revision still use)
   and ``tasks/get``.

Same design rule as the MCP adapter next to this file: a THIN PROTOCOL
ADAPTER. A message is forwarded in-process to the SAME governed
``/skills/{id}/execute`` route with the caller's own auth headers, so an
A2A caller inherits exactly the same 7-gate pipeline, RBAC and tenant
isolation as an MCP caller or a human user - never a side door.

Honesty boundary, stated plainly: this implements the parts of the A2A
spec understood at this build's knowledge cutoff (Agent Card discovery,
a synchronous message-to-task exchange) against a KAEOS skill named
EXPLICITLY in the message (a structured DataPart carrying skill_id) - it
does NOT do free-text natural-language routing to an arbitrary skill
(that is a real, separate intent-classification feature, not invented
here). Streaming, push notifications, and multi-turn task continuation
are not implemented either. **UNVERIFIED against a live reference A2A
client** - the spec has had real wire-format churn across revisions
(this build accepts both the current and one prior method name for
exactly that reason); this needs a genuine interop pass once such a
client is available to test against, the same honesty this codebase
already applies to Workday/OAuth2.1.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.tenant import require_role
from app.models.execution_status import ExecutionStatus

settings = get_settings()

router = APIRouter(tags=["Agent Interface — A2A"])

A2A_PROTOCOL_VERSION = "0.2.1"

# ExecutionStatus -> A2A TaskState. No member maps perfectly (A2A's states
# describe a single agent's own task lifecycle, not a multi-gate governance
# verdict) - documented judgment calls, not a spec guarantee:
# PENDING_HITL/ESCALATED_DEBATE -> "input-required" (closest built-in state
# for "paused, needs something before it can proceed" - not a literal match
# for "a human must approve", which A2A has no state for); BLOCKED_* ->
# "rejected" (the agent DECIDED not to act, which is what a governance
# refusal is); FAILED_* -> "failed"; everything terminal-successful ->
# "completed".
_TASK_STATE = {
    ExecutionStatus.SUCCESS_CLEAN: "completed",
    ExecutionStatus.SUCCESS_WITH_EDIT: "completed",
    ExecutionStatus.HUMAN_OVERRIDDEN: "completed",
    ExecutionStatus.PENDING_HITL: "input-required",
    ExecutionStatus.ESCALATED_DEBATE: "input-required",
    ExecutionStatus.BLOCKED_COMPLIANCE: "rejected",
    ExecutionStatus.BLOCKED_DEBATE: "rejected",
    ExecutionStatus.BLOCKED_ACTUATION: "rejected",
    ExecutionStatus.BLOCKED_RATE_LIMIT: "rejected",
}


# ── Agent Card ────────────────────────────────────────────────────────────────

def _agent_card(base_url: str) -> dict:
    return {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": "kaeos",
        "description": ("KAEOS runs company departments under a 7-gate "
                        "governance pipeline. Send a task naming a KAEOS "
                        "skill_id to run it; expect an input-required task "
                        "when the action is gated for human approval."),
        "url": f"{base_url}/a2a",
        "preferredTransport": "JSONRPC",
        "provider": {"organization": "KAEOS", "url": "https://kaeos.ai"},
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False,
                         "stateTransitionHistory": True},
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        # One representative skill (discovery), not the full per-tenant
        # catalog - that is /skills itself, reachable once governed. A2A's
        # own skills list is for advertising WHAT KIND of agent this is,
        # not enumerating every tenant-specific governed skill.
        "skills": [{
            "id": "execute_skill",
            "name": "Execute a governed KAEOS skill",
            "description": ("Run a named KAEOS skill through the full "
                            "7-gate pipeline. Send a DataPart "
                            '{"skill_id": "...", "intent": "...", '
                            '"context": {...}}.'),
            "tags": ["governed-execution", "enterprise"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        }],
    }


@router.get("/.well-known/agent-card.json")
@router.get("/.well-known/agent.json")   # pre-1.0 spec path some clients still probe
async def agent_card(request: Request):
    return JSONResponse(_agent_card(str(request.base_url).rstrip("/")))


# ── JSON-RPC plumbing (same shape as the MCP adapter next to this file) ──────

def _rpc_result(req_id: Any, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _rpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": code, "message": message}})


def _text_of(message: dict) -> str:
    parts = message.get("parts") or []
    return " ".join(str(p.get("text")) for p in parts
                    if isinstance(p, dict) and p.get("kind") == "text" and p.get("text"))


def _data_of(message: dict) -> dict:
    """The first structured DataPart's payload, or {} - KAEOS routes a task
    by an explicit skill_id in a DataPart, never by parsing the text part
    (that would be inventing an intent-classification feature this build
    does not have)."""
    for part in message.get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "data" and isinstance(part.get("data"), dict):
            return part["data"]
    return {}


async def _run_as_task(request: Request, message: dict) -> dict:
    """Forward one A2A message to /skills/{id}/execute and translate the
    real execution result into an A2A Task. The skill_id must be named
    explicitly in a DataPart - see this module's docstring."""
    from app.api.routes.agent_interface import _forward
    data = _data_of(message)
    skill_id = data.get("skill_id")
    task_id = str(uuid.uuid4())
    context_id = message.get("contextId") or str(uuid.uuid4())
    if not skill_id:
        return _task(task_id, context_id, "rejected", text=(
            "No skill_id in a DataPart. KAEOS does not guess which skill a "
            "free-text message means; send "
            '{"kind": "data", "data": {"skill_id": "...", "intent": "..."}}.'))
    intent = data.get("intent") or _text_of(message) or f"Run {skill_id}"
    body = {"intent": intent, "context": data.get("context") or {}}
    prefix = settings.API_PREFIX
    res = await _forward(request, "POST", f"{prefix}/skills/{skill_id}/execute",
                         json_body=body, channel="a2a")
    if res.status_code >= 400:
        return _task(task_id, context_id, "failed",
                    text=f"HTTP {res.status_code}: {res.text[:500]}")
    body_json = res.json() if "application/json" in res.headers.get("content-type", "") else {}
    status = str(body_json.get("status") or "")
    state = _TASK_STATE.get(status, "failed" if status else "completed")
    return _task(task_id, context_id, state, data=body_json)


def _task(task_id: str, context_id: str, state: str, *,
         text: str | None = None, data: dict | None = None) -> dict:
    parts: list[dict] = []
    if text:
        parts.append({"kind": "text", "text": text})
    if data:
        parts.append({"kind": "data", "data": data})
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "artifacts": [{"artifactId": str(uuid.uuid4()), "name": "kaeos-result", "parts": parts}]
                     if parts else [],
        "history": [],
        "kind": "task",
    }


# In-memory task store: this build's tasks are synchronous (the skill runs
# to completion, or to a PENDING_HITL pause, before message/send returns),
# so there is no separate async worker updating a task after the fact -
# tasks/get on a KNOWN id just re-serves what message/send already
# computed. FIFO-capped so a caller that never polls cannot leak memory.
# ponytail: process-local, not shared across workers - a multi-worker
# deployment would need this in the DB or Redis; add if tasks/get from a
# different worker than the one that ran message/send is ever observed.
_TASKS: dict[str, dict] = {}
_TASKS_CAP = 1000


@router.post("/a2a")
async def a2a_endpoint(
    request: Request,
    # Same default-deny shape as /mcp: viewer is the floor, execute_skill
    # re-verifies the operator role downstream via the forwarded request.
    tenant: dict = Depends(require_role("viewer")),
):
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        return _rpc_error(None, -32700, "Parse error: body is not valid JSON")
    if isinstance(payload, list):
        return _rpc_error(None, -32600, "Batch requests are not supported")
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _rpc_error(payload.get("id") if isinstance(payload, dict) else None,
                          -32600, "Invalid JSON-RPC 2.0 request")

    method = payload.get("method", "")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    if method in ("message/send", "tasks/send"):
        message = params.get("message") or {}
        if not isinstance(message, dict) or not message.get("parts"):
            return _rpc_error(req_id, -32602, "params.message.parts is required")
        task = await _run_as_task(request, message)
        while len(_TASKS) >= _TASKS_CAP:
            _TASKS.pop(next(iter(_TASKS)))
        _TASKS[task["id"]] = task
        return _rpc_result(req_id, task)
    if method == "tasks/get":
        task_id = params.get("id") or params.get("taskId")
        task = _TASKS.get(str(task_id))
        if task is None:
            return _rpc_error(req_id, -32001, f"Task not found: {task_id}")
        return _rpc_result(req_id, task)

    return _rpc_error(req_id, -32601, f"Method not found: {method}")
