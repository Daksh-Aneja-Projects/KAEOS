"""
KAEOS — Agent Factory Data Seeder
Seeds AgentBlueprint, DeployedAgent, ActivityFeedEvent records
so the Agent Factory UI renders live data out of the box.
"""
import asyncio
import uuid
import random
from datetime import datetime, timezone, timedelta

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

from app.models.agent_factory import (
    AgentBlueprint, BlueprintStatus,
    DeployedAgent, AgentStatus, AgentType,
    ActivityFeedEvent, ActivityEventType, ActivitySeverity,
)

TENANT = "tenant_acme"
NOW = datetime.now(timezone.utc)


def _id():
    return str(uuid.uuid4())


BLUEPRINT_DEFS = [
    {
        "name": "Compliance Review Agent",
        "description": "Create a compliance review agent that checks all new hire contracts against employment policies, flags GDPR issues, and notifies Legal via Slack.",
        "department": "legal",
        "domain": "legal",
        "status": BlueprintStatus.DEPLOYED,
        "compliance_tags": ["GDPR", "SOX"],
        "graph": {
            "nodes": [
                {"id": "fetch_contract", "type": "DATA_SOURCE", "label": "Fetch Contract from HRIS", "config": {"tool": "hris_read"}},
                {"id": "check_gdpr", "type": "DECISION_GATE", "label": "Check GDPR Compliance", "config": {"tool": "compliance_engine"}},
                {"id": "flag_issues", "type": "ACTION", "label": "Flag Policy Violations", "config": {"tool": "rules_engine"}},
                {"id": "notify_legal", "type": "OUTPUT", "label": "Notify Legal Team", "config": {"tool": "slack_notify"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_contract", "target": "check_gdpr", "type": "DATA_FLOW"},
                {"id": "e2", "source": "check_gdpr", "target": "flag_issues", "type": "DATA_FLOW"},
                {"id": "e3", "source": "flag_issues", "target": "notify_legal", "type": "DATA_FLOW"},
            ],
        },
    },
    {
        "name": "Invoice Matcher Agent",
        "description": "Build an agent that matches incoming invoices to purchase orders, validates three-way match (PO, receipt, invoice), and auto-approves under $7,500.",
        "department": "finance",
        "domain": "finance",
        "status": BlueprintStatus.COMPILED,
        "compliance_tags": ["SOX"],
        "graph": {
            "nodes": [
                {"id": "fetch_invoice", "type": "DATA_SOURCE", "label": "Fetch Invoice", "config": {"tool": "erp_read"}},
                {"id": "match_po", "type": "DECISION_GATE", "label": "Three-Way Match", "config": {"tool": "erp_match"}},
                {"id": "check_amount", "type": "DECISION_GATE", "label": "Check Approval Threshold", "config": {}},
                {"id": "approve", "type": "ACTION", "label": "Auto-Approve or Escalate", "config": {"tool": "erp_write"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_invoice", "target": "match_po", "type": "DATA_FLOW"},
                {"id": "e2", "source": "match_po", "target": "check_amount", "type": "DATA_FLOW"},
                {"id": "e3", "source": "check_amount", "target": "approve", "type": "CONDITIONAL_TRUE"},
            ],
        },
    },
    {
        "name": "Candidate Screening Agent",
        "description": "Create an agent that screens job candidates by analyzing resumes against job requirements, scoring fit, and flagging red flags for recruiter review.",
        "department": "hr",
        "domain": "hr",
        "status": BlueprintStatus.DEPLOYED,
        "compliance_tags": ["EEOC", "GDPR"],
        "graph": {
            "nodes": [
                {"id": "fetch_resume", "type": "DATA_SOURCE", "label": "Fetch Candidate Resume", "config": {"tool": "ats_read"}},
                {"id": "extract_skills", "type": "TRANSFORM", "label": "Extract Skills", "config": {"tool": "llm_extract"}},
                {"id": "score_fit", "type": "DECISION_GATE", "label": "Score Candidate Fit", "config": {}},
                {"id": "flag_issues", "type": "DECISION_GATE", "label": "Detect Red Flags", "config": {}},
                {"id": "notify", "type": "OUTPUT", "label": "Send Screening Summary", "config": {"tool": "slack_notify"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_resume", "target": "extract_skills", "type": "DATA_FLOW"},
                {"id": "e2", "source": "extract_skills", "target": "score_fit", "type": "DATA_FLOW"},
                {"id": "e3", "source": "score_fit", "target": "flag_issues", "type": "DATA_FLOW"},
                {"id": "e4", "source": "flag_issues", "target": "notify", "type": "DATA_FLOW"},
            ],
        },
    },
    {
        "name": "Deal Coaching Agent",
        "description": "Build a sales coaching agent that analyzes deal pipeline, identifies stalled opportunities, suggests next best actions, and updates CRM automatically.",
        "department": "sales",
        "domain": "sales",
        "status": BlueprintStatus.APPROVED,
        "compliance_tags": [],
        "graph": {
            "nodes": [
                {"id": "fetch_pipeline", "type": "DATA_SOURCE", "label": "Fetch Pipeline Data", "config": {"tool": "crm_read"}},
                {"id": "analyze_stalls", "type": "DECISION_GATE", "label": "Detect Stalled Deals", "config": {}},
                {"id": "suggest", "type": "TRANSFORM", "label": "Generate Coaching Tips", "config": {"tool": "llm_reason"}},
                {"id": "update_crm", "type": "ACTION", "label": "Update Opportunity Notes", "config": {"tool": "crm_write"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_pipeline", "target": "analyze_stalls", "type": "DATA_FLOW"},
                {"id": "e2", "source": "analyze_stalls", "target": "suggest", "type": "DATA_FLOW"},
                {"id": "e3", "source": "suggest", "target": "update_crm", "type": "DATA_FLOW"},
            ],
        },
    },
    {
        "name": "Ticket Triage Agent",
        "description": "Create an agent that automatically triages incoming support tickets, classifies severity, assigns to the right team, and sends initial customer acknowledgment.",
        "department": "support",
        "domain": "support",
        "status": BlueprintStatus.DEPLOYED,
        "compliance_tags": ["SLA"],
        "graph": {
            "nodes": [
                {"id": "fetch_ticket", "type": "DATA_SOURCE", "label": "Fetch Ticket", "config": {"tool": "helpdesk_read"}},
                {"id": "classify", "type": "DECISION_GATE", "label": "Classify Severity", "config": {"tool": "llm_classify"}},
                {"id": "assign", "type": "ACTION", "label": "Assign to Team", "config": {"tool": "helpdesk_write"}},
                {"id": "acknowledge", "type": "OUTPUT", "label": "Send Acknowledgment", "config": {"tool": "email_send"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_ticket", "target": "classify", "type": "DATA_FLOW"},
                {"id": "e2", "source": "classify", "target": "assign", "type": "DATA_FLOW"},
                {"id": "e3", "source": "assign", "target": "acknowledge", "type": "DATA_FLOW"},
            ],
        },
    },
    {
        "name": "Vendor Risk Assessment Agent",
        "description": "Build an agent that periodically assesses vendor risk by analyzing financial health, compliance certifications, delivery performance, and geopolitical exposure.",
        "department": "operations",
        "domain": "operations",
        "status": BlueprintStatus.DRAFTING,
        "compliance_tags": ["ISO27001"],
        "graph": {
            "nodes": [
                {"id": "fetch_vendor", "type": "DATA_SOURCE", "label": "Fetch Vendor Profile", "config": {"tool": "vendor_db_read"}},
                {"id": "check_financials", "type": "TRANSFORM", "label": "Analyze Financial Health", "config": {}},
                {"id": "score_risk", "type": "DECISION_GATE", "label": "Calculate Risk Score", "config": {}},
                {"id": "alert", "type": "OUTPUT", "label": "Alert Procurement Team", "config": {"tool": "slack_notify"}},
            ],
            "edges": [
                {"id": "e1", "source": "fetch_vendor", "target": "check_financials", "type": "DATA_FLOW"},
                {"id": "e2", "source": "check_financials", "target": "score_risk", "type": "DATA_FLOW"},
                {"id": "e3", "source": "score_risk", "target": "alert", "type": "CONDITIONAL_TRUE"},
            ],
        },
    },
]


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        blueprints = []
        deployed_agents = []
        feed_events = []

        for i, bp_def in enumerate(BLUEPRINT_DEFS):
            bp_id = _id()
            created = NOW - timedelta(days=30 - i * 4)
            approved_at = created + timedelta(hours=6) if bp_def["status"] != BlueprintStatus.DRAFTING else None

            bp = AgentBlueprint(
                id=bp_id,
                tenant_id=TENANT,
                name=bp_def["name"],
                description=bp_def["description"],
                department=bp_def["department"],
                domain=bp_def["domain"],
                status=bp_def["status"],
                blueprint_graph=bp_def["graph"],
                compliance_tags=bp_def["compliance_tags"],
                created_by="admin",
                approved_by="admin" if approved_at else None,
                created_at=created,
                approved_at=approved_at,
                deployed_at=created + timedelta(days=2) if bp_def["status"] == BlueprintStatus.DEPLOYED else None,
            )
            blueprints.append(bp)

            # Feed event for blueprint creation
            feed_events.append(ActivityFeedEvent(
                id=_id(),
                tenant_id=TENANT,
                event_type=ActivityEventType.BLUEPRINT_CREATED,
                severity=ActivitySeverity.INFO,
                title=f"Blueprint created: {bp_def['name']}",
                description=f"Blueprint '{bp_def['name']}' created from natural language prompt for {bp_def['department']} department.",
                event_metadata={"department": bp_def["department"], "domain": bp_def["domain"]},
                source_type="blueprint",
                source_id=bp_id,
                is_read=True,
                requires_action=False,
                created_at=created,
            ))

            # Create deployed agent for DEPLOYED blueprints
            if bp_def["status"] == BlueprintStatus.DEPLOYED:
                agent_id = _id()
                total_execs = random.randint(50, 500)
                success_count = int(total_execs * random.uniform(0.88, 0.98))
                avg_latency = random.randint(200, 3000)

                agent = DeployedAgent(
                    id=agent_id,
                    tenant_id=TENANT,
                    blueprint_id=bp_id,
                    agent_name=bp_def["name"],
                    agent_type=AgentType.PERSISTENT,
                    status=AgentStatus.RUNNING,
                    trigger_config={"type": "event", "config": {"source": bp_def["department"]}},
                    execution_count=total_execs,
                    success_count=success_count,
                    last_executed_at=NOW - timedelta(minutes=random.randint(5, 120)),
                    health_status={
                        "uptime_pct": round(random.uniform(97, 99.9), 2),
                        "avg_latency_ms": avg_latency,
                        "error_rate": round((total_execs - success_count) / max(total_execs, 1), 4),
                        "last_error": None,
                    },
                    created_at=created + timedelta(days=2),
                )
                deployed_agents.append(agent)

                # Activity feed events for this running agent
                event_defs = [
                    (ActivityEventType.AGENT_COMPLETED, ActivitySeverity.INFO, False,
                     f"{bp_def['name']} completed task", f"Successfully processed execution #{total_execs}"),
                    (ActivityEventType.HITL_REQUIRED, ActivitySeverity.ACTION_REQUIRED, True,
                     f"Human review required — {bp_def['name']}",
                     "Confidence score 0.71 fell below threshold 0.80. Awaiting operator decision."),
                    (ActivityEventType.DEBATE_ESCALATED, ActivitySeverity.WARNING, False,
                     f"Debate escalated for {bp_def['name']}",
                     "Proposer/advocate debate concluded — escalated to HITL for final decision."),
                ]
                for j, (etype, severity, requires_action, title, desc) in enumerate(event_defs):
                    feed_events.append(ActivityFeedEvent(
                        id=_id(),
                        tenant_id=TENANT,
                        event_type=etype,
                        severity=severity,
                        title=title,
                        description=desc,
                        event_metadata={"agent_name": bp_def["name"], "department": bp_def["department"]},
                        source_type="agent",
                        source_id=agent_id,
                        is_read=j > 0,
                        requires_action=requires_action,
                        created_at=NOW - timedelta(hours=j * 6 + random.randint(0, 3)),
                    ))

            if bp_def["status"] == BlueprintStatus.APPROVED:
                feed_events.append(ActivityFeedEvent(
                    id=_id(),
                    tenant_id=TENANT,
                    event_type=ActivityEventType.BLUEPRINT_APPROVED,
                    severity=ActivitySeverity.INFO,
                    title=f"Blueprint approved: {bp_def['name']}",
                    description="Blueprint ready for compilation and deployment.",
                    event_metadata={"department": bp_def["department"]},
                    source_type="blueprint",
                    source_id=bp_id,
                    is_read=False,
                    requires_action=False,
                    created_at=created + timedelta(hours=6),
                ))

        for obj in blueprints + deployed_agents + feed_events:
            db.add(obj)

        await db.commit()
        print(
            f"[AgentFactory Seed] ✓ {len(blueprints)} blueprints, "
            f"{len(deployed_agents)} deployed agents, {len(feed_events)} feed events"
        )


if __name__ == "__main__":
    asyncio.run(seed())
