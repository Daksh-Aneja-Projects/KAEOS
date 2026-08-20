"""
KAEOS Core — Shared Department HTTP Endpoint Plumbing

Two families of endpoint body were pasted into all ten department routers. They
live here once so a governance fix lands in every department instead of in the
one that happened to be edited:

  1. ``make_department_workflow_router()`` — the workflow HTTP surface over
     app/core/workflow.py: GET /workflows (the declared specs), GET
     /workflow-events (the transition audit trail) and POST
     /workflows/{entity_type}/bulk-transition.
  2. ``run_agent_endpoint()`` — the gated-AI-agent wrapper: run the agent,
     record the security event, map ValueError to 404 and anything else to a
     logged, detail-free 500.

The department routers keep their own endpoint NAMES and docstrings (they are
the operationIds and descriptions generated clients depend on), so this is a
body-only consolidation: every path, operationId, parameter and response is
unchanged.
"""
from __future__ import annotations

from typing import Any, Awaitable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.workflow import (
    BulkTransitionRequest, WorkflowSpec, apply_bulk_transition, list_workflow_events,
)


async def get_or_404(db: AsyncSession, model: Any, entity_id: Any, tenant_id: str, *, detail: str) -> Any:
    """Load one tenant-scoped row by primary key, or raise 404 with ``detail``.

    Emits exactly the statement the hand-written blocks emitted -
    ``select(model).where(model.id == entity_id, model.tenant_id == tenant_id)``
    with the filters in that order - and the same ``scalar_one_or_none()``
    fetch, so the SQL is byte-identical to what it replaced.

    ``tenant_id`` is a required positional, not an optional filter, so a
    conversion cannot silently drop the tenant predicate: this is a multi-tenant
    app behind Postgres RLS and an unscoped read is the one mistake worth making
    structurally impossible. Sites that filter on something other than
    ``model.id``/``model.tenant_id``, or that select a single column rather than
    the entity, are NOT convertible and are left hand-written.

    ``detail`` is required and never defaulted: the message is part of the
    published API contract and the departments disagree about wording
    ("Employee not found" vs "Lead {id} not found"), so each call site passes
    its own string verbatim rather than inheriting a normalised one.
    """
    row = (await db.execute(
        select(model).where(model.id == entity_id, model.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, detail=detail)
    return row


def make_department_workflow_router(
    domain: str,
    workflow_specs: Dict[str, WorkflowSpec],
    *,
    workflows_doc: Optional[str] = None,
    events_doc: Optional[str] = None,
    bulk_doc: Optional[str] = None,
) -> APIRouter:
    """Build the workflow endpoints a department asks for, named as it named them.

    Each ``*_doc`` argument both selects an endpoint and supplies its docstring;
    omit one and that endpoint is not registered. All ten departments now expose
    all three endpoints (S4.4 closed the last gaps: healthcare had no
    /workflow-events and no single-entity transition route, so its two declared
    state machines were unreachable over HTTP, and healthcare, lending and
    procurement had no bulk-transition). The selective mounting stays, because a
    department mounts the pieces separately — at the point in its router where
    the hand-written endpoints used to sit — so route order, and therefore match
    precedence, is unchanged.

    The generated functions carry the department's original ``__name__`` and
    ``__doc__``, so FastAPI derives exactly the same route name, operationId,
    summary and description it derived from the hand-written endpoints.
    """
    r = APIRouter()

    if workflows_doc is not None:
        async def workflows(tenant_id: str = Depends(get_tenant_id)):
            return {name: spec.describe() for name, spec in workflow_specs.items()}

        workflows.__name__ = f"get_{domain}_workflows"
        workflows.__doc__ = workflows_doc
        r.get("/workflows")(workflows)

    if events_doc is not None:
        async def workflow_events(
            entity_type: Optional[str] = None, entity_id: Optional[str] = None,
            tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
        ):
            return await list_workflow_events(db, tenant_id, domain=domain,
                                              entity_type=entity_type, entity_id=entity_id)

        workflow_events.__name__ = f"get_{domain}_workflow_events"
        workflow_events.__doc__ = events_doc
        r.get("/workflow-events")(workflow_events)

    if bulk_doc is not None:
        async def bulk_transition(
            entity_type: str, body: BulkTransitionRequest,
            tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
        ):
            spec = workflow_specs.get(entity_type)
            if not spec:
                raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(workflow_specs)}")
            return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)

        bulk_transition.__name__ = f"bulk_transition_{domain}"
        bulk_transition.__doc__ = bulk_doc
        r.post("/workflows/{entity_type}/bulk-transition")(bulk_transition)

    return r


async def run_agent_endpoint(
    coro: Awaitable[Any],
    tenant: dict,
    *,
    actor: Optional[str],
    resource_type: str,
    resource_id: Optional[str],
    logger: Any,
) -> Any:
    """Run one gated AI agent call and record it, with the shared error contract.

    ``coro`` is the un-awaited agent call, built by the caller so the agent
    object is constructed outside this try (as it was in every hand-written
    copy).

    ValueError maps to 404 (not 403) so another tenant's id is not confirmed to
    exist. Everything else is logged with a stack trace and returned as a
    detail-free 500, so an internal failure never leaks into the response body.

    ``actor`` is passed by every caller as ``approver_identity(tenant)`` — the
    one canonical, always-attributable principal identity (email -> user_id ->
    name -> "tenant:role"). It used to differ by department: engineering and
    operations already used ``approver_identity`` while legal/sales/support used
    ``tenant.get("name")``, which recorded None for a principal without a name, so
    18 of the 27 endpoints routed through here could land in the ledger with no
    attributable actor. Normalised to ``approver_identity`` everywhere (S4.10),
    and the JWT principal now carries a real ``email`` so the first branch
    attributes to the person, not an opaque id.

    The five hand-written departments now converge on this same error contract
    (S4.5 / S4.11):

      finance      /invoices/{id}/match and /receivables/{id}/dunning now map
                   ValueError -> 404 like the nine siblings (support /sla/check
                   takes no id, so it stays a 500-only tenant-wide sweep).
      healthcare,  the gated agent endpoints now add the logged, detail-free 500
      procurement  handler alongside their ValueError -> 404 mapping.
      hr           the gated agent endpoints stay bespoke (pre-fetch, mutate,
                   custom response shape) and are not members of this family, but
                   already satisfy the contract by other means: get_or_404 gives
                   the 404, and the global error envelope (install_error_handlers)
                   gives a non-leaky 500 for any uncaught agent failure.
    """
    tenant_id = tenant["tenant_id"]
    try:
        result = await coro
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=actor, actor_role=tenant.get("role"),
            resource_type=resource_type, resource_id=resource_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except HTTPException:
        raise  # a deliberate status (e.g. 409 invalid transition) is not a 500
    except Exception as e:
        # logger.name == the caller module's __name__, so this reproduces the
        # copies' `logger.exception("%s failed", __name__)` message exactly.
        logger.exception("%s failed", logger.name)
        raise HTTPException(500, detail="Internal error - see server logs") from e
