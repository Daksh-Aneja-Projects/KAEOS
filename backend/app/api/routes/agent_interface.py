"""KAEOS speaks agent — the machine-facing interface.

Two surfaces:

1. ``GET /brain/skills-file`` — the Company Brain exported as an executable
   Company Skills File (markdown for context windows, JSON for programs).

2. ``POST /mcp`` — a Model Context Protocol endpoint (JSON-RPC 2.0 over
   streamable HTTP). Any MCP-speaking agent can discover and call KAEOS
   tools: query the brain, list skills, run a skill, read the safe-autonomy
   rate, and see what is waiting on a human.

Design rule: the MCP layer is a THIN PROTOCOL ADAPTER. Tool calls are
forwarded in-process to the existing governed REST routes with the caller's
auth headers, so an agent inherits exactly the same 7-gate pipeline, RBAC,
and tenant isolation as a human user — never a side door around them.
"""
import json

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.services.skills_file import build_skills_file, render_markdown

settings = get_settings()

router = APIRouter(tags=["Agent Interface — MCP"])

MCP_PROTOCOL_VERSION = "2025-06-18"
_FORWARD_HEADERS = ("authorization", "x-api-key", "x-tenant-id")
# Skill executions run real multi-step LLM calls on local models.
_INTERNAL_TIMEOUT = 300.0


# ── Company Skills File ──────────────────────────────────────────────────────

@router.get("/brain/skills-file")
async def get_skills_file(
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The Company Brain as a portable, executable skills file."""
    payload = await build_skills_file(db, tenant_id)
    if format == "json":
        return JSONResponse(payload)
    return PlainTextResponse(render_markdown(payload), media_type="text/markdown")


# ── MCP tool registry ────────────────────────────────────────────────────────
# name → (description, JSON schema, forwarder spec)

TOOLS = [
    {
        "name": "query_company_brain",
        "description": (
            "Overview of this organization's Company Brain: rules, skills, "
            "signals, departments, and current knowledge posture."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_skills",
        "description": (
            "List the organization's executable skills with confidence, "
            "success rate, and compliance tags. Optionally filter by "
            "department or status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "status": {"type": "string"},
                "min_confidence": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_skill",
        "description": (
            "Execute a skill through the FULL KAEOS 7-gate governance "
            "pipeline (compliance, fairness, confidence, human gate, debate, "
            "execute, provenance). May return PENDING_HITL when a human must "
            "approve — that is the system working, not an error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "intent": {"type": "string", "description": "What you want done, in plain language."},
                "context": {"type": "object"},
            },
            "required": ["skill_id", "intent"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_safe_autonomy_rate",
        "description": (
            "The north-star metric: the share of real work completed with no "
            "human in the loop, with its fallout breakdown and daily series."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_pending_approvals",
        "description": "Decisions currently paused at the human gate, waiting for sign-off.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "export_skills_file",
        "description": (
            "Export the Company Skills File: the organization's rules and "
            "executable skills as one portable document (markdown or json)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"format": {"type": "string", "enum": ["markdown", "json"]}},
            "additionalProperties": False,
        },
    },
]


def _rpc_error(req_id, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _rpc_result(req_id, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


async def _forward(request: Request, method: str, path: str,
                   params: dict | None = None, json_body: dict | None = None) -> httpx.Response:
    """Call one of our own governed routes in-process, as the caller."""
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_HEADERS}
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://kaeos-internal", timeout=_INTERNAL_TIMEOUT
    ) as client:
        return await client.request(method, path, params=params, json=json_body, headers=headers)


async def _call_tool(request: Request, name: str, args: dict) -> dict:
    prefix = settings.API_PREFIX
    if name == "query_company_brain":
        r = await _forward(request, "GET", f"{prefix}/brain/overview")
    elif name == "list_skills":
        params = {k: v for k, v in args.items() if v is not None}
        # No trailing slash: the route is defined as "" under the /skills
        # prefix, so "/skills/" draws a 307 the internal client won't follow.
        r = await _forward(request, "GET", f"{prefix}/skills", params=params)
    elif name == "execute_skill":
        skill_id = args["skill_id"]
        body = {"intent": args["intent"], "context": args.get("context") or {}}
        r = await _forward(request, "POST", f"{prefix}/skills/{skill_id}/execute", json_body=body)
    elif name == "get_safe_autonomy_rate":
        params = {"days": args.get("days") or 30}
        r = await _forward(request, "GET", f"{prefix}/metrics/safe-autonomy", params=params)
    elif name == "list_pending_approvals":
        r = await _forward(request, "GET", f"{prefix}/skills/hitl/pending")
    elif name == "export_skills_file":
        fmt = args.get("format") or "markdown"
        r = await _forward(request, "GET", f"{prefix}/brain/skills-file", params={"format": fmt})
    else:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }

    if r.status_code >= 400:
        return {
            "content": [{"type": "text", "text": f"HTTP {r.status_code}: {r.text[:500]}"}],
            "isError": True,
        }
    content_type = r.headers.get("content-type", "")
    if "application/json" in content_type:
        data = r.json()
        return {
            "content": [{"type": "text", "text": json.dumps(data, default=str)[:20000]}],
            "structuredContent": data if isinstance(data, dict) else {"items": data},
            "isError": False,
        }
    return {"content": [{"type": "text", "text": r.text[:40000]}], "isError": False}


# ── MCP endpoint (JSON-RPC 2.0, streamable HTTP) ─────────────────────────────

@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    # Default-deny: every mutation-capable route carries an explicit role gate.
    # Viewer is the floor - any authenticated user may SPEAK the protocol - and
    # the dangerous tools re-verify stronger roles downstream: tools/call
    # forwards the caller's own auth headers to the governed routes, where
    # execute_skill still demands the operator role. Two independent walls.
    tenant: dict = Depends(require_role("viewer")),
):
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        # Malformed / non-JSON body -> JSON-RPC parse error. Narrowed so a real
        # bug (e.g. TypeError in downstream code) is never masked as "parse error".
        return _rpc_error(None, -32700, "Parse error: body is not valid JSON")

    if isinstance(payload, list):
        return _rpc_error(None, -32600, "Batch requests are not supported")
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _rpc_error(payload.get("id") if isinstance(payload, dict) else None,
                          -32600, "Invalid JSON-RPC 2.0 request")

    method = payload.get("method", "")
    req_id = payload.get("id")

    # Notifications get 202 Accepted with no body, per streamable HTTP.
    if req_id is None:
        return Response(status_code=202)

    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "kaeos",
                "title": "KAEOS — governed enterprise actions for AI agents",
                "version": "1.0.0",
            },
            "instructions": (
                "KAEOS runs company departments under a 7-gate governance "
                "pipeline. Use list_skills / query_company_brain to discover "
                "capability, execute_skill to act (expect PENDING_HITL on "
                "gated actions), and export_skills_file for portable context."
            ),
        })
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        if not name:
            return _rpc_error(req_id, -32602, "Missing tool name")
        args = params.get("arguments") or {}
        result = await _call_tool(request, name, args)
        return _rpc_result(req_id, result)

    return _rpc_error(req_id, -32601, f"Method not found: {method}")
