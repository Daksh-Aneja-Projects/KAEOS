"""
KAEOS HR Vertical — V1 API Router

Read endpoints plus the state-changing mutations/triggers for the recruiting
pipeline. Tenant is always derived from the authenticated context
(``Depends(get_tenant_id)``) — never a query param or a hardcoded "default".

AI actions that change state (candidate screening) run through the gated
``AgentExecutor`` pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate ->
Execute -> Audit) via the HR agents, and responses carry provenance / HITL
references so callers can trace or resolve them.

The endpoints themselves live in ``routers/``, one module per sub-domain. This
module is the assembler: it owns the ``/hr`` prefix and the department tag (the
single place either is declared), and the include order below IS the route
order, so match precedence is readable in one place. It keeps the two HITL
endpoints inline because they resolve ``record_security_event`` through this
module's globals, which is where callers patch it.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.audit import record_security_event
from app.core.tenant import approver_identity, require_role
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: F401  (re-exported)

from app.hr.api.v1.routers import (
    benefits, compensation, compliance, connectors, dashboard, employee_documents,
    employee_relations, employees, interviews, learning, metrics, onboarding, payroll,
    performance, recruiting, timesheets, workflows, workforce_planning,
)

router = APIRouter(prefix="/hr", tags=["Human Resources"])


class HITLDecision(BaseModel):
    reason: str = ""
    # DEPRECATED / IGNORED: the approver is derived from the authenticated
    # principal server-side (see hitl_approve/hitl_reject). Kept only so older
    # clients that still send it do not break; its value is never trusted.
    approver: str = "human"


router.include_router(employees.router)
router.include_router(recruiting.router)


# ── HITL approve / reject ─────────────────────────────────────────────────────
# INTENTIONALLY KEPT despite being unreachable from the current frontend (the
# HITLQueue UI resolves every domain's pending executions through the generic
# api.approveHITL/api.rejectHITL -> hitl_manager path, which is
# domain-agnostic and works fine for HR too). These HR-scoped routes stay as a
# stable, documented surface for API-only / integration callers who want an
# `/hr/...` URL rather than the generic one — same resolution, same audit
# trail, just namespaced. Delete only if that use case is confirmed dead too.

@router.post("/hitl/{execution_id}/approve")
async def hitl_approve(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Approve a pending HITL-gated HR execution.

    The approver recorded is the AUTHENTICATED principal — the client-supplied
    ``body.approver`` is ignored (a spoofable approver would undermine every
    HITL data point that feeds the safe-autonomy metric).
    """
    tenant_id = tenant["tenant_id"]
    approver = approver_identity(tenant)
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, True, approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
        details={"reason": body.reason},
    )
    return {"execution_id": execution_id, "approved": True, "approver": approver}


@router.post("/hitl/{execution_id}/reject")
async def hitl_reject(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Reject a pending HITL-gated HR execution.

    Approver = authenticated principal; ``body.approver`` is ignored.
    """
    tenant_id = tenant["tenant_id"]
    approver = approver_identity(tenant)
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, False, approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
        details={"reason": body.reason},
    )
    return {"execution_id": execution_id, "approved": False, "approver": approver}


router.include_router(dashboard.router)
router.include_router(workflows.router)

# ═══════════════════════════════════════════════════════════════════════
# Full-schema coverage — the other 9 model groups (Benefits, Compensation,
# Onboarding/Offboarding, Learning, Employee Relations, Workforce Planning,
# Payroll, Compliance, Analytics) plus Interviews/EmployeeDocuments/
# Timesheets and the 6 previously-dead HR agents (bound only to org-graph
# metadata nothing ever read — see workforce_generator.HR_AGENT_REGISTRY).
# Every mutation is tenant-scoped and real DB-backed logic; every agent
# trigger below persists its decision onto the entity, never just returns
# a dict and forgets it.
# ═══════════════════════════════════════════════════════════════════════
router.include_router(benefits.router)
router.include_router(compensation.router)
router.include_router(onboarding.router)
router.include_router(learning.router)
router.include_router(employee_relations.router)
router.include_router(workforce_planning.router)
router.include_router(payroll.router)
router.include_router(compliance.router)
router.include_router(metrics.router)
router.include_router(interviews.router)
router.include_router(employee_documents.router)
router.include_router(timesheets.router)
router.include_router(performance.router)
router.include_router(connectors.router)
