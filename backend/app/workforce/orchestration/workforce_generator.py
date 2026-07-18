"""
KAEOS Workforce Layer — Workforce Generator

Translates a Domain Pack definition into concrete Department, Capability,
and Process records. Bridges the gap between the YAML template and the DB.
"""
import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workforce.models.core import Department, Capability, BusinessProcess, DepartmentAgent, WorkforceDeployment
from app.workforce.models.domain_pack import DomainPack

logger = logging.getLogger(__name__)


# ── Real agent class registry ────────────────────────────────────────────────
# Maps a pack agent `type` to the concrete implementation class and its primary
# action method. Used to bind generated skills to REAL agent behaviour instead of
# placeholder no-ops, and consumed by the gated executor (Task 8).
HR_AGENT_REGISTRY: dict[str, dict] = {
    "recruiting": {
        "module": "app.hr.agents.recruiting_agent", "class": "RecruitingAgent",
        "method": "screen_candidate", "compliance": ["EEOC", "GDPR"],
    },
    "sourcing": {
        "module": "app.hr.agents.recruiting_agent", "class": "RecruitingAgent",
        "method": "screen_candidate", "compliance": ["EEOC", "GDPR"],
    },
    "onboarding": {
        "module": "app.hr.agents.onboarding_agent", "class": "OnboardingAgent",
        "method": "check_in_with_new_hire", "compliance": ["I9"],
    },
    "benefits": {
        "module": "app.hr.agents.benefits_agent", "class": "BenefitsAgent",
        "method": "answer_benefits_query", "compliance": ["HIPAA", "ACA"],
    },
    "compensation": {
        "module": "app.hr.agents.compensation_agent", "class": "CompensationAgent",
        "method": "analyze_salary_band", "compliance": ["EEOC"],
    },
    "performance": {
        "module": "app.hr.agents.performance_agent", "class": "PerformanceAgent",
        "method": "synthesize_feedback", "compliance": ["EEOC"],
    },
    "employee_relations": {
        "module": "app.hr.agents.employee_relations_agent", "class": "EmployeeRelationsAgent",
        "method": "triage_case", "compliance": ["EEOC", "GDPR"],
    },
    "offboarding": {
        "module": "app.hr.agents.offboarding_agent", "class": "OffboardingAgent",
        "method": "analyze_exit_interview", "compliance": ["GDPR"],
    },
}

# Finance domain agents
FINANCE_AGENT_REGISTRY: dict[str, dict] = {
    "ap_matching": {
        "module": "app.finance.agents.ap_agent", "class": "APAgent",
        "method": "process_invoice", "compliance": ["SOX", "GAAP", "PCI"],
    },
    "ar_dunning": {
        "module": "app.finance.agents.ar_agent", "class": "ARAgent",
        "method": "generate_dunning", "compliance": ["SOX", "GAAP"],
    },
    "budget_variance": {
        "module": "app.finance.agents.budget_agent", "class": "BudgetAgent",
        "method": "analyze_variance", "compliance": ["GAAP"],
    },
    "expense_audit": {
        "module": "app.finance.agents.expense_agent", "class": "ExpenseAgent",
        "method": "audit_report", "compliance": ["SOX", "PCI"],
    },
    "payroll_audit": {
        "module": "app.finance.agents.tax_agent", "class": "TaxAgent",
        "method": "audit_payroll", "compliance": ["SOX"],
    },
}

# Legal domain agents
LEGAL_AGENT_REGISTRY: dict[str, dict] = {
    "contract_review": {
        "module": "app.legal.agents.contract_review_agent", "class": "ContractReviewAgent",
        "method": "review_contract", "compliance": ["GDPR", "CCPA"],
    },
    "compliance_audit": {
        "module": "app.legal.agents.compliance_audit_agent", "class": "ComplianceAuditAgent",
        "method": "audit_obligation", "compliance": ["GDPR", "CCPA"],
    },
    "litigation_eval": {
        "module": "app.legal.agents.litigation_agent", "class": "LitigationAgent",
        "method": "evaluate_case", "compliance": ["CCPA"],
    },
    "privacy_dsar": {
        "module": "app.legal.agents.privacy_dsar_agent", "class": "PrivacyDSARAgent",
        "method": "process_dsar", "compliance": ["GDPR", "CCPA"],
    },
}

# Sales domain agents
SALES_AGENT_REGISTRY: dict[str, dict] = {
    "lead_scoring": {
        "module": "app.sales.agents.lead_scoring_agent", "class": "LeadScoringAgent",
        "method": "score_lead", "compliance": ["CCPA"],
    },
    "account_health": {
        "module": "app.sales.agents.account_health_agent", "class": "AccountHealthAgent",
        "method": "assess_health", "compliance": ["CCPA"],
    },
    "pipeline_coach": {
        "module": "app.sales.agents.pipeline_coach_agent", "class": "PipelineCoachAgent",
        "method": "coach_opportunity", "compliance": ["SOX"],
    },
    "forecast": {
        "module": "app.sales.agents.forecast_agent", "class": "ForecastAgent",
        "method": "predict_forecast", "compliance": ["SOX"],
    },
    "proposal_gen": {
        "module": "app.sales.agents.proposal_gen_agent", "class": "ProposalGenAgent",
        "method": "generate_proposal", "compliance": ["SOX"],
    },
    "churn_prevention": {
        "module": "app.sales.agents.churn_agent", "class": "ChurnAgent",
        "method": "identify_churn_risk", "compliance": ["CCPA"],
    },
}

# Support domain agents
SUPPORT_AGENT_REGISTRY: dict[str, dict] = {
    "triage": {
        "module": "app.support.agents.triage_agent", "class": "TriageAgent",
        "method": "triage_ticket", "compliance": ["GDPR", "CCPA", "SLA"],
    },
    "auto_resolve": {
        "module": "app.support.agents.auto_resolve_agent", "class": "AutoResolveAgent",
        "method": "generate_response", "compliance": ["GDPR", "CCPA"],
    },
    "escalation": {
        "module": "app.support.agents.escalation_agent", "class": "EscalationAgent",
        "method": "escalate_ticket", "compliance": ["SLA"],
    },
    "csat_analysis": {
        "module": "app.support.agents.csat_agent", "class": "CSATAgent",
        "method": "analyze_surveys", "compliance": ["GDPR"],
    },
    "sla_monitor": {
        "module": "app.support.agents.sla_agent", "class": "SLAAgent",
        "method": "check_sla", "compliance": ["SLA"],
    },
}

# Operations domain agents
OPERATIONS_AGENT_REGISTRY: dict[str, dict] = {
    "project_eval": {
        "module": "app.operations.agents.project_agent", "class": "ProjectAgent",
        "method": "evaluate_project", "compliance": ["SOC2"],
    },
    "resource_check": {
        "module": "app.operations.agents.resource_agent", "class": "ResourceAgent",
        "method": "check_resources", "compliance": ["SOC2"],
    },
    "vendor_risk": {
        "module": "app.operations.agents.vendor_agent", "class": "VendorAgent",
        "method": "evaluate_vendor", "compliance": ["SOC2"],
    },
    "procurement_audit": {
        "module": "app.operations.agents.procurement_agent", "class": "ProcurementAgent",
        "method": "audit_request", "compliance": ["SOC2"],
    },
    "qa_inspect": {
        "module": "app.operations.agents.qa_agent", "class": "QAAgent",
        "method": "inspect_qa", "compliance": ["SOC2"],
    },
}

# Unified registry for all domains
AGENT_REGISTRY = {
    **HR_AGENT_REGISTRY,
    **FINANCE_AGENT_REGISTRY,
    **LEGAL_AGENT_REGISTRY,
    **SALES_AGENT_REGISTRY,
    **SUPPORT_AGENT_REGISTRY,
    **OPERATIONS_AGENT_REGISTRY,
}

# Real, action-bearing skill steps per HR agent type (replaces the old
# parse_payload / execute_task_logic / emit_event_log placeholders).
_HR_AGENT_STEPS: dict[str, list] = {
    "recruiting": [
        {"id": "load_candidate", "action": "Retrieve candidate record, resume, and the linked job requisition from the ATS", "tool": "none", "condition": "candidate_id present"},
        {"id": "screen_candidate", "action": "Objectively screen the candidate against requisition requirements; produce score (0-100), summary, red_flags, recommend_advance — no protected-attribute inference", "tool": "none", "condition": "Always"},
        {"id": "record_screening", "action": "Persist AI score, summary and red flags to the candidate and advance/reject the stage", "tool": "none", "condition": "Always"},
    ],
    "onboarding": [
        {"id": "load_new_hire", "action": "Retrieve the new hire record and their 30/60/90 onboarding plan", "tool": "none", "condition": "employee_id present"},
        {"id": "check_in", "action": "Run the scheduled new-hire check-in and assess sentiment / blockers", "tool": "none", "condition": "Always"},
        {"id": "verify_tasks", "action": "Verify completion of onboarding tasks (I-9, equipment, orientation) and flag gaps", "tool": "none", "condition": "Always"},
    ],
    "benefits": [
        {"id": "load_context", "action": "Retrieve the employee's benefits enrollment and relevant plan documents", "tool": "none", "condition": "employee_id present"},
        {"id": "answer_query", "action": "Answer the benefits question grounded in plan documents; never expose PHI beyond the minimum necessary", "tool": "none", "condition": "Always"},
    ],
    "compensation": [
        {"id": "load_band", "action": "Retrieve the role's current salary band and market context", "tool": "none", "condition": "job_title present"},
        {"id": "analyze_band", "action": "Analyze the salary band for market alignment and pay-equity risk", "tool": "none", "condition": "Always"},
    ],
    "performance": [
        {"id": "load_review", "action": "Retrieve the performance review and raw feedback inputs", "tool": "none", "condition": "review_id present"},
        {"id": "synthesize", "action": "Synthesize balanced, bias-checked feedback from the raw inputs", "tool": "none", "condition": "Always"},
    ],
    "employee_relations": [
        {"id": "load_case", "action": "Retrieve the employee relations case and its history", "tool": "none", "condition": "case_id present"},
        {"id": "triage", "action": "Triage the case for severity, policy implications and required escalation", "tool": "none", "condition": "Always"},
    ],
    "offboarding": [
        {"id": "load_exit", "action": "Retrieve the departing employee record and exit-interview responses", "tool": "none", "condition": "employee_id present"},
        {"id": "analyze_exit", "action": "Analyze the exit interview for attrition drivers and retention signals", "tool": "none", "condition": "Always"},
    ],
}


def build_agent_skill(agent_def: dict, pack_slug: str, capability) -> dict:
    """Return real skill steps + the bound agent handler for a pack agent def.

    For known agent types (all domains) this emits action-bearing steps and records the
    concrete class/method to invoke. For unmapped agent types it emits a single
    meaningful step describing the agent's real role (no placeholder no-ops).
    """
    agent_type = (agent_def.get("type") or "").lower()
    registry = AGENT_REGISTRY.get(agent_type)  # Check unified registry for all domains
    steps = _HR_AGENT_STEPS.get(agent_type)  # Only HR has pre-defined steps for now

    if steps is None:
        # Non-HR (or unmapped) agent — describe the real role rather than no-ops.
        role = agent_def.get("description") or agent_def.get("name", "agent")
        steps = [
            {"id": "assess", "action": f"Assess the incoming {capability.name} task for '{role}'", "tool": "none", "condition": "Always"},
            {"id": "act", "action": f"Execute the {role} decision and produce a structured, auditable outcome", "tool": "none", "condition": "Always"},
        ]

    handler = None
    if registry:
        handler = {
            "module": registry["module"],
            "class": registry["class"],
            "method": registry["method"],
        }
        # Bind the handler to the primary action step for the executor to route.
        for step in steps:
            if step["id"] in ("screen_candidate", "check_in", "answer_query", "analyze_band",
                              "synthesize", "triage", "analyze_exit"):
                step["agent_handler"] = handler
                break

    return {"steps": steps, "handler": handler, "compliance": (registry or {}).get("compliance", [])}


class WorkforceGenerator:
    
    async def generate_department_structure(self, db: AsyncSession, tenant_id: str, deployment_id: str) -> Department:
        """Creates the logical structure (Dept -> Capability -> Process)."""
        logger.info(f"Generating department structure for deployment {deployment_id}")
        
        q = await db.execute(select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id))
        deployment = q.scalar_one_or_none()
        
        # Idempotency: if this deployment already created a department, reuse it
        # instead of creating a duplicate (protects against pipeline re-runs).
        if deployment.department_id:
            existing_q = await db.execute(
                select(Department).where(Department.id == deployment.department_id)
            )
            existing_dept = existing_q.scalar_one_or_none()
            if existing_dept:
                logger.info(
                    f"[Generator] Department {existing_dept.id} already exists for "
                    f"deployment {deployment_id} — reusing (idempotent)."
                )
                return existing_dept
        
        pack_q = await db.execute(select(DomainPack).where(DomainPack.id == deployment.domain_pack_id))
        pack = pack_q.scalar_one_or_none()

        # Idempotency across deployments: departments are unique per
        # (tenant_id, slug) — redeploying a pack must adopt the existing
        # department rather than violate the constraint.
        slug_q = await db.execute(
            select(Department).where(
                Department.tenant_id == tenant_id, Department.slug == pack.slug
            )
        )
        existing_by_slug = slug_q.scalar_one_or_none()
        if existing_by_slug:
            logger.info(
                f"[Generator] Department slug '{pack.slug}' already exists for "
                f"tenant {tenant_id} — adopting it for deployment {deployment_id}."
            )
            existing_by_slug.employee_count = deployment.employee_count or existing_by_slug.employee_count
            if deployment.connected_systems:
                existing_by_slug.connected_systems = deployment.connected_systems
            deployment.department_id = existing_by_slug.id
            db.add(existing_by_slug)
            db.add(deployment)
            await db.commit()
            await db.refresh(existing_by_slug)
            return existing_by_slug

        # 1. Create Department
        dept = Department(
            tenant_id=tenant_id,
            name=pack.name,
            slug=pack.slug,
            description=pack.description,
            icon=pack.icon,
            domain_pack_id=pack.id,
            domain_pack_version=pack.version,
            employee_count=deployment.employee_count,
            connected_systems=deployment.connected_systems,
            compliance_frameworks=pack.compliance_frameworks
        )
        db.add(dept)
        await db.commit()
        await db.refresh(dept)
        
        deployment.department_id = dept.id
        db.add(deployment)
        
        capabilities_created = []
        processes_created = []
        
        # 2. Create Capabilities
        for cap_def in pack.capabilities:
            if cap_def["id"] in deployment.selected_capabilities or not deployment.selected_capabilities:
                cap = Capability(
                    tenant_id=tenant_id,
                    department_id=dept.id,
                    name=cap_def["name"],
                    slug=cap_def["id"],
                    description=cap_def.get("description", ""),
                    icon=cap_def.get("icon", "⚡"),
                    agent_definitions=cap_def.get("agents", []),
                    process_definitions=cap_def.get("processes", []),
                    compliance_tags=cap_def.get("compliance", [])
                )
                db.add(cap)
                await db.commit()
                await db.refresh(cap)
                capabilities_created.append(cap.id)
                
                # 3. Create Processes for this capability
                for proc_id in cap.process_definitions:
                    # Find process definition in pack
                    proc_def = next((p for p in pack.process_definitions if p["id"] == proc_id), None)
                    if proc_def:
                        proc = BusinessProcess(
                            tenant_id=tenant_id,
                            capability_id=cap.id,
                            department_id=dept.id,
                            name=proc_def["name"],
                            slug=proc_def["id"],
                            sla_hours=proc_def.get("sla_hours"),
                            steps=proc_def.get("steps", [])
                        )
                        db.add(proc)
                        processes_created.append(proc.id)
                        
        await db.commit()
        
        # Update deployment record
        deployment.capabilities_activated = capabilities_created
        deployment.processes_created = processes_created
        db.add(deployment)
        await db.commit()
        
        # Update counts
        dept.capability_count = len(capabilities_created)
        dept.process_count = len(processes_created)
        db.add(dept)
        await db.commit()
        
        return dept

    async def deploy_agents(self, db: AsyncSession, tenant_id: str, deployment_id: str, department_id: str):
        """Creates DepartmentAgent records and triggers KAEOS blueprint/agent generation."""
        logger.info(f"Deploying agents for department {department_id}")
        
        # Idempotency: don't re-deploy if this department already has agents.
        existing_agents_q = await db.execute(
            select(DepartmentAgent).where(DepartmentAgent.department_id == department_id)
        )
        if existing_agents_q.scalars().first() is not None:
            logger.info(
                f"[Generator] Department {department_id} already has agents — "
                f"skipping deploy_agents (idempotent)."
            )
            return
        
        q = await db.execute(select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id))
        deployment = q.scalar_one_or_none()
        
        pack_q = await db.execute(select(DomainPack).where(DomainPack.id == deployment.domain_pack_id))
        pack = pack_q.scalar_one_or_none()
        
        agents_created = []
        
        # Find active capabilities
        cap_q = await db.execute(select(Capability).where(Capability.department_id == department_id))
        capabilities = cap_q.scalars().all()
        
        from app.models.agent_factory import AgentBlueprint, DeployedAgent, BlueprintStatus, AgentStatus, AgentType
        from app.models.domain import Skill
        
        for cap in capabilities:
            # Match agent definitions from the pack belonging to this capability or matching by name/type
            matched_defs = []
            for a in pack.agent_definitions:
                if a.get("capability") == cap.slug:
                    matched_defs.append(a)
                elif cap.agent_definitions and any(
                    a["name"].lower() == name.lower() or
                    a.get("type", "").lower() == name.lower() or
                    name.lower().replace("_", "") in a["name"].lower() or
                    a.get("type", "").lower() in name.lower()
                    for name in cap.agent_definitions
                ):
                    if a not in matched_defs:
                        matched_defs.append(a)

            for agent_def in matched_defs:
                # 1. Create AgentBlueprint
                bp_id = str(uuid.uuid4())
                blueprint = AgentBlueprint(
                    id=bp_id,
                    tenant_id=tenant_id,
                    name=agent_def["name"],
                    description=agent_def.get("description", f"Autonomous agent for {cap.name}"),
                    domain=pack.slug,
                    department=pack.slug,
                    status=BlueprintStatus.DEPLOYED,
                    mcp_tools_required=agent_def.get("tools", []),
                    compliance_tags=cap.compliance_tags or []
                )
                db.add(blueprint)
                await db.commit()

                # 2. Create Skill for this agent — bound to a REAL agent action,
                #    with neutral, un-fabricated initial metrics.
                skill_uuid = str(uuid.uuid4())
                skill_id_name = f"{pack.slug}_{agent_def['type']}_core"
                built = build_agent_skill(agent_def, pack.slug, cap)
                skill_compliance = list({*(cap.compliance_tags or []), *built["compliance"]})
                skill = Skill(
                    id=skill_uuid,
                    skill_id=skill_id_name,
                    tenant_id=tenant_id,
                    department=pack.slug,
                    domain=cap.slug,
                    version=pack.version,
                    status="ACTIVE",
                    # Neutral prior: unproven skill, no executions yet.
                    confidence=0.5,
                    confidence_tier="INFERRED",
                    confidence_vector={
                        "source_breadth": 0.5, "source_authority": 0.5,
                        "temporal_freshness": 0.5, "outcome_validation": 0.5,
                        "explicit_validation": 0.5,
                    },
                    execution_count=0,
                    success_rate=0.0,
                    half_life_days=90,
                    triggers=[f"incoming task for {agent_def['name']}"],
                    steps=built["steps"],
                    compliance_tags=skill_compliance,
                )
                db.add(skill)
                await db.commit()

                # 3. Create DeployedAgent
                da_id = str(uuid.uuid4())
                deployed_agent = DeployedAgent(
                    id=da_id,
                    tenant_id=tenant_id,
                    blueprint_id=bp_id,
                    agent_name=agent_def["name"],
                    agent_type=AgentType.PERSISTENT,
                    status=AgentStatus.RUNNING,
                    compiled_skill_id=skill_uuid,
                    execution_count=skill.execution_count,
                    success_count=int(skill.execution_count * skill.success_rate)
                )
                db.add(deployed_agent)
                await db.commit()
                
                # 4. Create DepartmentAgent link
                dept_agent = DepartmentAgent(
                    tenant_id=tenant_id,
                    department_id=department_id,
                    capability_id=cap.id,
                    agent_name=agent_def["name"],
                    agent_type=agent_def["type"],
                    persona=agent_def.get("persona", ""),
                    role_in_department=agent_def.get("description", ""),
                    blueprint_id=bp_id,
                    deployed_agent_id=da_id
                )
                db.add(dept_agent)
                await db.commit()
                await db.refresh(dept_agent)
                agents_created.append(dept_agent.id)
                
                # Create startup activity event
                from app.models.agent_factory import ActivityFeedEvent, ActivityEventType, ActivitySeverity
                event = ActivityFeedEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    event_type=ActivityEventType.AGENT_STARTED,
                    severity=ActivitySeverity.INFO,
                    title=f"Agent {agent_def['name']} Deployed",
                    description=f"Persistent workforce agent {agent_def['name']} has been initialized under capability {cap.name} for the {pack.name} department.",
                    source_type="agent",
                    source_id=da_id
                )
                db.add(event)
                await db.commit()
                    
        deployment.agents_created = agents_created
        db.add(deployment)
        
        dept_q = await db.execute(select(Department).where(Department.id == department_id))
        dept = dept_q.scalar_one()
        dept.agent_count = len(agents_created)
        db.add(dept)
        
        await db.commit()

    async def seed_knowledge(self, db: AsyncSession, tenant_id: str, deployment_id: str, department_id: str):
        """Seeds the EnterpriseMemory and Knowledge base with templates from the pack."""
        logger.info(f"Seeding knowledge for department {department_id}")
        
        q = await db.execute(select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id))
        deployment = q.scalar_one_or_none()
        
        pack_q = await db.execute(select(DomainPack).where(DomainPack.id == deployment.domain_pack_id))
        pack = pack_q.scalar_one_or_none()
        
        # 1. Create Workflow and Rule entries based on pack definitions
        from app.models.domain import Workflow, Rule, ConfidenceTier
        
        # Find active capabilities
        cap_q = await db.execute(select(Capability).where(Capability.department_id == department_id))
        capabilities = cap_q.scalars().all()
        
        for cap in capabilities:
            # Create a Workflow for each process definition
            for proc_id in cap.process_definitions:
                proc_def = next((p for p in pack.process_definitions if p["id"] == proc_id), None)
                if proc_def:
                    wf_id = f"wf_{proc_id}_{str(uuid.uuid4())[:8]}"
                    workflow = Workflow(
                        id=wf_id,
                        tenant_id=tenant_id,
                        name=proc_def["name"],
                        department=pack.slug,
                        sla_hours=proc_def.get("sla_hours", 48),
                        coverage_score=0.85
                    )
                    db.add(workflow)
                    await db.commit()
                    
                    # Create some default rules for this workflow
                    rule_statements = self._get_default_rules_for_domain(pack.slug, proc_id)
                    for stmt, trigger, action in rule_statements:
                        rule = Rule(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            statement=stmt,
                            trigger_json=trigger,
                            action_json=action,
                            domain=pack.slug,
                            workflow_id=wf_id,
                            confidence_scalar=0.88,
                            confidence_tier=ConfidenceTier.VERIFIED,
                            is_executable=True,
                            compliance_tags=cap.compliance_tags or []
                        )
                        db.add(rule)
                    await db.commit()

        # Add a compliance scan event or general deployment event to activity log
        from app.models.agent_factory import ActivityFeedEvent, ActivityEventType, ActivitySeverity
        event = ActivityFeedEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            event_type=ActivityEventType.BLUEPRINT_APPROVED,
            severity=ActivitySeverity.INFO,
            title=f"{pack.name} Knowledge Base Seeded",
            description=f"Compliance frameworks {', '.join(pack.compliance_frameworks or [])} mapped and initial knowledge base policies indexed.",
            source_type="department",
            source_id=department_id
        )
        db.add(event)
        await db.commit()

    def _get_default_rules_for_domain(self, domain: str, process_id: str):
        rules_map = {
            "hr": {
                "candidate_screening": [
                    ("Candidate screening must evaluate only job-related qualifications; race, gender, age, religion, national origin, disability and genetic information are never scored (EEOC).",
                     {"trigger": "candidate_submitted"}, {"action": "screen_job_related_only"}),
                    ("Any screening decision with an AI fairness score below the department threshold is routed to a human recruiter (EEOC).",
                     {"trigger": "screening_scored", "fairness_below_threshold": True}, {"action": "route_to_hitl"}),
                    ("Candidate personal data is processed only for the applied role and retained per the GDPR retention policy.",
                     {"trigger": "candidate_submitted", "has_pii": True}, {"action": "apply_gdpr_retention"}),
                ],
                "interview_scheduling": [
                    ("Interview panels use a structured, identical question set per requisition to ensure comparable, non-discriminatory evaluation (EEOC).",
                     {"trigger": "interview_scheduling"}, {"action": "enforce_structured_panel"}),
                    ("Reasonable-accommodation requests for interviews are honored and never recorded against the candidate (ADA/EEOC).",
                     {"trigger": "accommodation_requested"}, {"action": "grant_accommodation"}),
                ],
                "offer_generation": [
                    ("Offer compensation must fall within the approved, pay-equity-reviewed band for the role and location (EEOC).",
                     {"trigger": "offer_drafted", "outside_band": True}, {"action": "block_and_review"}),
                    ("Offers require human approval before release; candidate PII in the offer is handled per GDPR.",
                     {"trigger": "offer_drafted"}, {"action": "require_human_approval"}),
                ],
                "new_hire_welcome": [
                    ("I-9 employment eligibility verification must complete within the legally required timeline for every new hire (I9).",
                     {"trigger": "new_hire_started"}, {"action": "enforce_i9_timeline"}),
                    ("New-hire personal data collected during onboarding is minimized and access-restricted (GDPR).",
                     {"trigger": "onboarding_data_collected", "has_pii": True}, {"action": "restrict_access"}),
                ],
                "open_enrollment": [
                    ("Benefits enrollment discloses only the minimum necessary protected health information (HIPAA).",
                     {"trigger": "enrollment_processing", "has_phi": True}, {"action": "minimum_necessary"}),
                    ("Qualifying life-event changes are processed within the ACA-compliant window with an audit record.",
                     {"trigger": "life_event", "within_window": True}, {"action": "process_and_audit"}),
                ],
            },
            "finance": {
                "invoice_matching": [
                    ("Vendor invoice matching PO amount and items within 2% variance is auto-approved.", {"trigger": "invoice_ingested"}, {"action": "auto_approve"}),
                    ("Invoices over $25,000 always require CFO approval.", {"trigger": "invoice_ingested", "amount_usd": "> 25000"}, {"action": "route_to_cfo"})
                ],
                "dunning_escalation": [
                    ("Unpaid customer invoice past due 15 days triggers standard reminder email.", {"trigger": "invoice_overdue", "days": 15}, {"action": "send_reminder"}),
                    ("Overdue receivables past 60 days are escalated to collections manager.", {"trigger": "invoice_overdue", "days": 60}, {"action": "escalate_manager"})
                ],
                "budget_variance_check": [
                    ("Line item variance exceeding 10% of budgeted threshold flags automatic warning to DH.", {"trigger": "variance_check", "variance_pct": "> 10"}, {"action": "alert_dh"}),
                ],
                "expense_audit": [
                    ("Reimbursements for meals under $50 with valid receipt auto-approve.", {"trigger": "expense_submitted", "amount": "< 50", "category": "meals"}, {"action": "auto_approve"}),
                ]
            },
            "legal": {
                "contracts": [
                    ("Standard mutual NDAs matching corporate template limits are auto-approved.", {"trigger": "contract_received", "type": "NDA"}, {"action": "approve"}),
                    ("Contract values exceeding $100K require external legal counsel review.", {"trigger": "contract_received", "value": "> 100000"}, {"action": "route_external_review"})
                ],
                "compliance": [
                    ("Any data transfer containing GDPR PII must undergo automated DPIA screening.", {"trigger": "data_transfer", "has_pii": True}, {"action": "run_dpia"}),
                ]
            },
            "support": {
                "tickets": [
                    ("P0 customer tickets alert support lead via emergency channel if unassigned for 10 min.", {"trigger": "ticket_created", "severity": "P0"}, {"action": "emergency_alert"}),
                    ("Standard ticket queries matching cached KB articles are resolved automatically.", {"trigger": "ticket_created", "kb_match": True}, {"action": "auto_resolve"})
                ]
            },
            "sales": {
                "pipeline": [
                    ("Deals remaining in stage 'Negotiation' for 30+ days flag AE manager review.", {"trigger": "deal_stage_duration", "stage": "negotiation", "days": 30}, {"action": "alert_manager"}),
                    ("Discount requests between 10% and 20% escalate to VP Sales.", {"trigger": "discount_requested", "pct": "> 10, <= 20"}, {"action": "escalate_vp"})
                ]
            },
            "operations": {
                "projects": [
                    ("Project tasks past due by 5 days trigger automated timeline re-calculation.", {"trigger": "task_delay", "days": 5}, {"action": "recalculate_timeline"}),
                ],
                "vendors": [
                    ("New vendor registrations without valid SOC2 certifications are routed to risk team.", {"trigger": "vendor_registered", "has_soc2": False}, {"action": "route_risk_review"}),
                ]
            }
        }
        domain_rules = rules_map.get(domain, {})
        return domain_rules.get(process_id, [
            (f"Standard {domain} {process_id} rule: default logic applies.", {"trigger": "event"}, {"action": "default"})
        ])
