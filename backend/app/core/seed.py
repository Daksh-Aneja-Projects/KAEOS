"""KAEOS - DB Seed: populates all 6 skills from skill.md + sample rules, employees, questions"""
from datetime import datetime, timezone, timedelta
import logging
import uuid
import hashlib
import json

logger = logging.getLogger(__name__)

from app.models.domain import (
    Rule, Skill, Employee, ElicitationQuestion, Workflow,
    SkillExecution, ConfidenceTier, Signal,
    Connector, ConflictCase, MarketplaceTemplate, SecurityAuditLog,
    DecayEvent, RedTeamScanResult,
)
from app.models.settings import TenantLLMConfig, MCPToolConfig, OntologyConfig, FederatedConfig
from app.models.agent_factory import AgentBlueprint, BlueprintStatus

T = "tenant_acme"
NOW = None  # Set at seed time by seed_database()


def _id():
    return str(uuid.uuid4())


def _hash(parent, payload):
    c = f"{parent}|{json.dumps(payload, sort_keys=True, default=str)}"
    return hashlib.sha256(c.encode()).hexdigest()


def seed_workflows():
    return [
        Workflow(id="wf_refund", tenant_id=T, name="Refund Processing", department="support", sla_hours=48, coverage_score=0.82),
        Workflow(id="wf_discount", tenant_id=T, name="Discount Approval", department="sales", sla_hours=24, coverage_score=0.58),
        Workflow(id="wf_incident", tenant_id=T, name="Incident Escalation", department="engineering", sla_hours=4, coverage_score=0.84),
        Workflow(id="wf_payment", tenant_id=T, name="Vendor Payment", department="finance", sla_hours=72, coverage_score=0.67),
        Workflow(id="wf_onboard", tenant_id=T, name="New Hire Onboarding", department="hr", sla_hours=120, coverage_score=0.76),
        Workflow(id="wf_qualify", tenant_id=T, name="Deal Qualification", department="sales", sla_hours=48, coverage_score=0.71),
    ]


def seed_departments():
    """
    Seed Department records for all 7 enterprise departments.

    NB: this silently returned [] for its entire life — it passed
    `sla_compliance_rate`/`automation_rate`/`last_active_at`, none of which are
    columns on Department, and a bare `except Exception: return []` swallowed the
    TypeError. Only ImportError is caught now (the genuine "workforce models not
    migrated yet" case); a schema mismatch must fail loudly.
    """
    try:
        from app.workforce.models.core import Department, DepartmentStatus
    except ImportError:
        return []  # Graceful: workforce models not yet migrated

    from datetime import timedelta
    return [
            Department(id="dept_hr", tenant_id=T, name="Human Resources", slug="hr",
                description="AI-powered HR department: recruiting, onboarding, benefits, performance.",
                icon="HR", status=DepartmentStatus.ACTIVE,
                employee_count=42, agent_count=7, capability_count=6, process_count=18,
                health_score=0.94, automation_coverage=0.78,
                deployed_at=NOW - timedelta(days=30),),
            Department(id="dept_finance", tenant_id=T, name="Finance", slug="finance",
                description="AI-powered Finance department: AP, AR, budgets, payroll, audit.",
                icon="FIN", status=DepartmentStatus.ACTIVE,
                employee_count=18, agent_count=5, capability_count=5, process_count=14,
                health_score=0.91, automation_coverage=0.71,
                deployed_at=NOW - timedelta(days=21),),
            Department(id="dept_legal", tenant_id=T, name="Legal", slug="legal",
                description="AI-powered Legal department: contracts, compliance, litigation, privacy.",
                icon="LGL", status=DepartmentStatus.ACTIVE,
                employee_count=8, agent_count=4, capability_count=4, process_count=11,
                health_score=0.96, automation_coverage=0.62,
                deployed_at=NOW - timedelta(days=14),),
            Department(id="dept_sales", tenant_id=T, name="Sales", slug="sales",
                description="AI-powered Sales department: pipeline, forecasting, account management.",
                icon="SLS", status=DepartmentStatus.ACTIVE,
                employee_count=55, agent_count=6, capability_count=5, process_count=12,
                health_score=0.88, automation_coverage=0.83,
                deployed_at=NOW - timedelta(days=45),),
            Department(id="dept_support", tenant_id=T, name="Customer Support", slug="support",
                description="AI-powered Support department: tickets, SLA, CSAT, escalations.",
                icon="SUP", status=DepartmentStatus.ACTIVE,
                employee_count=30, agent_count=5, capability_count=4, process_count=10,
                health_score=0.92, automation_coverage=0.86,
                deployed_at=NOW - timedelta(days=60),),
            Department(id="dept_ops", tenant_id=T, name="Operations", slug="operations",
                description="AI-powered Operations department: projects, procurement, vendors, QA.",
                icon="OPS", status=DepartmentStatus.ACTIVE,
                employee_count=24, agent_count=5, capability_count=5, process_count=13,
                health_score=0.89, automation_coverage=0.69,
                deployed_at=NOW - timedelta(days=10),),
            Department(id="dept_engineering", tenant_id=T, name="Engineering & IT Ops", slug="engineering",
                description="AI-powered Engineering department: code review, deployments, incidents, postmortems.",
                icon="ENG", status=DepartmentStatus.ACTIVE,
                employee_count=4, agent_count=3, capability_count=5, process_count=9,
                health_score=0.87, automation_coverage=0.74,
                deployed_at=NOW - timedelta(days=5),),
    ]


def seed_employees():
    return [
        Employee(id="emp_1", tenant_id=T, hashed_id="h1", display_name="Sarah Chen", role="Support Manager", department="support", tenure_months=36, authority_score=0.82, expertise_domains=["refunds","escalations"], response_rate=0.91, total_contributions=47, confirmed_contributions=42, rejected_contributions=2, reputation_score=0.88),
        Employee(id="emp_2", tenant_id=T, hashed_id="h2", display_name="Marcus Rivera", role="VP Sales", department="sales", tenure_months=48, authority_score=0.92, expertise_domains=["enterprise","discounts"], response_rate=0.78, total_contributions=31, confirmed_contributions=28, rejected_contributions=1, reputation_score=0.85),
        Employee(id="emp_3", tenant_id=T, hashed_id="h3", display_name="Priya Patel", role="SRE Lead", department="engineering", tenure_months=24, authority_score=0.85, expertise_domains=["incidents","monitoring"], response_rate=0.95, total_contributions=62, confirmed_contributions=58, rejected_contributions=3, reputation_score=0.91),
        Employee(id="emp_4", tenant_id=T, hashed_id="h4", display_name="James Mitchell", role="CFO", department="finance", tenure_months=60, authority_score=0.95, expertise_domains=["payments","budgets","compliance"], response_rate=0.65, total_contributions=18, confirmed_contributions=17, rejected_contributions=0, reputation_score=0.82),
        Employee(id="emp_5", tenant_id=T, hashed_id="h5", display_name="Lin Zhang", role="HR Director", department="hr", tenure_months=30, authority_score=0.88, expertise_domains=["onboarding","policy"], response_rate=0.87, total_contributions=25, confirmed_contributions=23, rejected_contributions=1, reputation_score=0.84),
        Employee(id="emp_6", tenant_id=T, hashed_id="h6", display_name="Alex Thompson", role="Account Executive", department="sales", tenure_months=18, authority_score=0.65, expertise_domains=["deals","negotiation"], response_rate=0.82, total_contributions=14, confirmed_contributions=11, rejected_contributions=2, reputation_score=0.72),
    ]


def seed_skills():
    return [
        Skill(id=_id(), skill_id="handle_refund_request", tenant_id=T, department="customer_support", domain="support_cx", version="2.7", status="ACTIVE", confidence=0.91, confidence_tier="VERIFIED_AGAINST_OUTCOMES", confidence_vector={"source_breadth":0.95,"source_authority":0.88,"temporal_freshness":0.79,"outcome_validation":0.92,"explicit_validation":0.85}, execution_count=1847, success_rate=0.966, half_life_days=90, last_validated=NOW-timedelta(days=45), mcp_tool_bindings=["crm_write","ticket_update","escalation_notify","customer_profile_read"], compliance_tags=["GDPR","CCPA"], triggers=["customer requests refund","ticket tagged: billing, refund"], steps=[{"id":"step_1","action":"fetch_customer_profile","tool":"crm_read"},{"id":"step_2","action":"check_order_age","condition":"order_age_days > 30"},{"id":"step_3","action":"check_customer_tier"},{"id":"step_4","action":"evaluate_refund_amount","thresholds":{"auto":50,"note":500,"manager":500}},{"id":"step_5","action":"log_decision_crm","tool":"crm_write"},{"id":"step_6","action":"notify_customer"}], exceptions=[{"id":"ltv_override","condition":"customer_ltv_usd > 10000","confidence":0.88},{"id":"fraud_block","condition":"fraud_flag == true","auto_apply":True}], guardrails={"pre_execution":["verify: agent_has_crm_write_permission","check: rate_limit < 20"],"post_execution":["assert: crm_record_updated","assert: customer_notified"]}, confidence_notes=["Base threshold ($500) validated by Sarah Chen, 2026-02-01","LTV override inferred from 47 decisions"], provenance={"primary_sources":["helpdesk_ticket_archive_2024","messaging_support_channel_decisions"]}, access_level="department"),
        Skill(id=_id(), skill_id="enterprise_discount_approval", tenant_id=T, department="sales", domain="commercial", version="4.1", status="ACTIVE", confidence=0.89, confidence_tier="VALIDATED_DEPARTMENT_HEAD", confidence_vector={"source_breadth":0.87,"source_authority":0.91,"temporal_freshness":0.85,"outcome_validation":0.88,"explicit_validation":0.85}, execution_count=412, success_rate=0.941, half_life_days=30, expires_at=NOW+timedelta(days=10), last_validated=NOW-timedelta(days=20), mcp_tool_bindings=["crm_opportunity_update","slack_notify","approval_workflow_trigger","pricing_engine_read"], compliance_tags=["SOX","INTERNAL_AUDIT"], triggers=["discount requested on enterprise deal","CRM field: discount_pct > 0"], steps=[{"id":"step_1","action":"fetch_opportunity_data"},{"id":"step_2","action":"apply_discount_authority_matrix"},{"id":"step_3","action":"check_competitive_pressure"},{"id":"step_4","action":"trigger_approval_workflow"},{"id":"step_5","action":"update_crm_opportunity"}], exceptions=[{"id":"strategic_account_override","condition":"strategic_account == true","confidence":0.83}], guardrails={"pre_execution":["verify: opportunity_exists_in_crm","check: rate_card_version_is_current"],"post_execution":["assert: approval_chain_documented"]}, confidence_notes=["Authority matrix confirmed by CRO office 2026-03-01"], provenance={"primary_sources":["crm_deal_history","slack_sales_channel"]}, access_level="role_specific"),
        Skill(id=_id(), skill_id="incident_escalation_p1", tenant_id=T, department="engineering", domain="incident_management", version="3.3", status="ACTIVE", confidence=0.94, confidence_tier="VERIFIED_AGAINST_OUTCOMES", confidence_vector={"source_breadth":0.96,"source_authority":0.92,"temporal_freshness":0.91,"outcome_validation":0.95,"explicit_validation":0.90}, execution_count=2204, success_rate=0.983, half_life_days=90, last_validated=NOW-timedelta(days=25), mcp_tool_bindings=["alerting_notify","messaging_incident_channel","statuspage_update","issue_tracker_create","war_room_spin_up"], compliance_tags=["SOC2","INTERNAL_SLA"], triggers=["error rate > 5% for > 3 minutes","service health check: CRITICAL"], steps=[{"id":"step_1","action":"classify_incident_severity"},{"id":"step_2","action":"spin_up_war_room"},{"id":"step_3","action":"page_on_call_engineer"},{"id":"step_4","action":"update_status_page"},{"id":"step_5","action":"create_incident_ticket"},{"id":"step_6","action":"start_incident_timer"}], exceptions=[{"id":"maintenance_window","condition":"active_maintenance_window == true","auto_apply":True}], guardrails={"pre_execution":["verify: incident_not_already_declared"],"post_execution":["assert: war_room_created","assert: on_call_notified"]}, confidence_notes=["Escalation timing validated by VP Engineering 2025-12-01"], provenance={"primary_sources":["alerting_history","postmortem_docs"]}, access_level="department"),
        Skill(id=_id(), skill_id="vendor_payment_approval", tenant_id=T, department="finance", domain="accounts_payable", version="2.1", status="ACTIVE", confidence=0.87, confidence_tier="VALIDATED_DEPARTMENT_HEAD", confidence_vector={"source_breadth":0.84,"source_authority":0.90,"temporal_freshness":0.82,"outcome_validation":0.86,"explicit_validation":0.85}, execution_count=893, success_rate=0.951, half_life_days=180, last_validated=NOW-timedelta(days=40), mcp_tool_bindings=["erp_payment_queue","vendor_master_read","budget_ledger_read","approval_workflow_trigger","audit_log_write"], compliance_tags=["SOX","GAAP","PCI_DSS"], triggers=["invoice submitted for payment","AP queue: payment_pending"], steps=[{"id":"step_1","action":"validate_invoice"},{"id":"step_2","action":"apply_payment_authority_matrix"},{"id":"step_3","action":"check_budget_availability"},{"id":"step_4","action":"trigger_approval_chain"},{"id":"step_5","action":"execute_payment"},{"id":"step_6","action":"write_audit_log"}], exceptions=[{"id":"emergency_vendor_payment","condition":"vendor_category == critical_infrastructure","confidence":0.82}], guardrails={"pre_execution":["verify: vendor_exists_in_master_list","verify: invoice_not_duplicate","verify: purchase_order_matches"],"post_execution":["assert: payment_logged_in_erp","assert: audit_trail_written"]}, confidence_notes=["Payment matrix approved by CFO 2026-01-15"], provenance={"primary_sources":["erp_payment_history","finance_slack"]}, access_level="role_specific"),
        Skill(id=_id(), skill_id="new_hire_onboarding_trigger", tenant_id=T, department="human_resources", domain="employee_lifecycle", version="1.9", status="ACTIVE", confidence=0.86, confidence_tier="VALIDATED_DEPARTMENT_HEAD", confidence_vector={"source_breadth":0.82,"source_authority":0.88,"temporal_freshness":0.80,"outcome_validation":0.84,"explicit_validation":0.85}, execution_count=341, success_rate=0.971, half_life_days=180, last_validated=NOW-timedelta(days=60), mcp_tool_bindings=["hris_read","it_provisioning_request","slack_workspace_invite","calendar_schedule","buddy_assignment_system","compliance_training_enrol"], compliance_tags=["I9","EEOC","SOC2"], triggers=["new hire record created in HRIS","offer_status = ACCEPTED"], steps=[{"id":"step_1","action":"verify_hire_record_completeness"},{"id":"step_2","action":"trigger_it_provisioning"},{"id":"step_3","action":"assign_onboarding_buddy"},{"id":"step_4","action":"schedule_onboarding_week"},{"id":"step_5","action":"enrol_mandatory_compliance_training"},{"id":"step_6","action":"create_30_60_90_day_plan"}], exceptions=[{"id":"executive_hire","condition":"job_level >= VP","auto_apply":True}], guardrails={"pre_execution":["verify: hire_record_complete"],"post_execution":["assert: it_provisioned","assert: buddy_assigned"]}, confidence_notes=["IT provisioning timeline from 341 executions - 97.1% on-time"], provenance={"primary_sources":["hris_records","hr_slack"]}, access_level="department"),
        # Deliberately below the 0.82 HITL confidence gate — exercises the
        # PENDING_HITL path in the L9 pipeline (and the e2e HITL tests).
        Skill(id=_id(), skill_id="marketing_campaign_review", tenant_id=T, department="marketing", domain="campaign_ops", version="0.4", status="ACTIVE", confidence=0.74, confidence_tier="VALIDATED_PEER", confidence_vector={"source_breadth":0.62,"source_authority":0.58,"temporal_freshness":0.92,"outcome_validation":0.55,"explicit_validation":0.60}, execution_count=38, success_rate=0.842, half_life_days=45, last_validated=NOW-timedelta(days=12), mcp_tool_bindings=["campaign_platform_read","brand_asset_check","slack_notify"], compliance_tags=["CAN_SPAM"], triggers=["campaign submitted for review","asset tagged: pre-launch"], steps=[{"id":"step_1","action":"fetch_campaign_brief"},{"id":"step_2","action":"check_brand_guidelines"},{"id":"step_3","action":"score_audience_fit"},{"id":"step_4","action":"flag_for_approval"}], exceptions=[], guardrails={"pre_execution":["verify: campaign_exists"],"post_execution":["assert: review_logged"]}, confidence_notes=["Only 38 executions — insufficient outcome validation for autonomy"], provenance={"primary_sources":["campaign_review_threads"]}, access_level="department"),
        Skill(id=_id(), skill_id="sales_deal_qualification", tenant_id=T, department="sales", domain="pipeline_management", version="3.0", status="ACTIVE", confidence=0.88, confidence_tier="VERIFIED_AGAINST_OUTCOMES", confidence_vector={"source_breadth":0.86,"source_authority":0.89,"temporal_freshness":0.83,"outcome_validation":0.91,"explicit_validation":0.85}, execution_count=678, success_rate=0.891, half_life_days=60, last_validated=NOW-timedelta(days=29), mcp_tool_bindings=["crm_opportunity_update","sales_intel_read","competitive_intel_read","slack_notify_sales_manager"], compliance_tags=[], triggers=["new opportunity created in CRM","sales rep requests deal qualification"], steps=[{"id":"step_1","action":"score_meddpicc"},{"id":"step_2","action":"classify_deal_quality"},{"id":"step_3","action":"identify_qualification_gaps"},{"id":"step_4","action":"update_crm_opportunity"},{"id":"step_5","action":"notify_sales_manager"}], exceptions=[{"id":"strategic_account_override","condition":"account_is_strategic == true","confidence":0.91}], guardrails={"pre_execution":["verify: opportunity_exists"],"post_execution":["assert: crm_updated"]}, confidence_notes=["MEDDPICC scoring validated by Sales Leadership 2026-02-15"], provenance={"primary_sources":["crm_deal_history","sales_call_recordings"]}, access_level="department"),
    ]


def seed_rules():
    rules = []
    defs = [
        ("Refunds under $50 auto-approve without manager review", "support", "wf_refund", {"condition":"refund_amount < 50"}, {"action":"auto_approve"}, 0.91, ConfidenceTier.VERIFIED, ["GDPR","CCPA"]),
        ("Refunds $50-$500 require support agent note", "support", "wf_refund", {"condition":"50 <= refund_amount < 500"}, {"action":"approve_with_note"}, 0.89, ConfidenceTier.VALIDATED_DH, ["GDPR"]),
        ("Refunds over $500 require manager approval", "support", "wf_refund", {"condition":"refund_amount >= 500"}, {"action":"escalate_to_manager"}, 0.87, ConfidenceTier.VALIDATED_DH, ["GDPR"]),
        ("Orders over 30 days old require senior support review", "support", "wf_refund", {"condition":"order_age_days > 30"}, {"action":"route_to_senior"}, 0.85, ConfidenceTier.VALIDATED_MANAGER, []),
        ("Enterprise/strategic customers require account manager notification", "support", "wf_refund", {"condition":"customer_tier in ['enterprise','strategic']"}, {"action":"notify_account_manager"}, 0.83, ConfidenceTier.VALIDATED_MANAGER, []),
        ("Discounts up to 5% auto-approved by AE", "sales", "wf_discount", {"condition":"discount_pct <= 5"}, {"action":"auto_approve"}, 0.92, ConfidenceTier.VERIFIED, ["SOX"]),
        ("Discounts 5-10% require sales manager approval", "sales", "wf_discount", {"condition":"5 < discount_pct <= 10"}, {"action":"escalate_sales_manager"}, 0.88, ConfidenceTier.VALIDATED_DH, ["SOX"]),
        ("Discounts 10-15% require VP Sales approval", "sales", "wf_discount", {"condition":"10 < discount_pct <= 15"}, {"action":"escalate_vp_sales"}, 0.87, ConfidenceTier.VALIDATED_DH, ["SOX"]),
        ("Discounts over 15% require CRO approval", "sales", "wf_discount", {"condition":"discount_pct > 15"}, {"action":"escalate_cro"}, 0.85, ConfidenceTier.VALIDATED_DH, ["SOX"]),
        ("P1 incidents: page on-call within 5 minutes", "engineering", "wf_incident", {"condition":"severity == P1"}, {"action":"page_oncall","timeout":5}, 0.94, ConfidenceTier.VERIFIED, ["SOC2"]),
        ("P1 not ack'd in 5min: escalate to secondary", "engineering", "wf_incident", {"condition":"p1_no_ack_5min"}, {"action":"escalate_secondary"}, 0.93, ConfidenceTier.VERIFIED, ["SOC2"]),
        ("VP Engineering notified if P1 not mitigated in 30min", "engineering", "wf_incident", {"condition":"p1_unmitigated_30min"}, {"action":"notify_vp_eng"}, 0.91, ConfidenceTier.VERIFIED, []),
        ("Invoices under $5K auto-approved by AP specialist", "finance", "wf_payment", {"condition":"invoice_amount < 5000"}, {"action":"auto_approve"}, 0.87, ConfidenceTier.VALIDATED_DH, ["SOX","GAAP"]),
        ("Invoices $5K-$25K require finance manager", "finance", "wf_payment", {"condition":"5000 <= invoice_amount < 25000"}, {"action":"escalate_finance_manager"}, 0.85, ConfidenceTier.VALIDATED_DH, ["SOX","GAAP"]),
        ("Invoices over $100K require CFO approval", "finance", "wf_payment", {"condition":"invoice_amount >= 100000"}, {"action":"escalate_cfo"}, 0.83, ConfidenceTier.VALIDATED_MANAGER, ["SOX"]),
        ("IT provisioning must start 5 days before hire start date", "hr", "wf_onboard", {"condition":"days_to_start <= 5"}, {"action":"trigger_it_provisioning"}, 0.86, ConfidenceTier.VALIDATED_DH, []),
        ("Executive hires (VP+) get CHRO-led onboarding", "hr", "wf_onboard", {"condition":"job_level >= VP"}, {"action":"chro_onboarding"}, 0.84, ConfidenceTier.VALIDATED_DH, []),
        ("MEDDPICC score below 6 = recommend no-pursue", "sales", "wf_qualify", {"condition":"meddpicc_score < 6"}, {"action":"recommend_no_pursue"}, 0.88, ConfidenceTier.VERIFIED, []),
        ("Weak deals (score 6-12) flagged for manager review", "sales", "wf_qualify", {"condition":"6 <= meddpicc_score < 12"}, {"action":"flag_manager_review"}, 0.86, ConfidenceTier.VALIDATED_DH, []),
        ("LTV > $10K customers: always approve refunds", "support", "wf_refund", {"condition":"customer_ltv > 10000"}, {"action":"auto_approve_override"}, 0.71, ConfidenceTier.VALIDATED_PEER, ["GDPR"]),
        ("Fraud-flagged accounts: block all refunds immediately", "support", "wf_refund", {"condition":"fraud_flag == true"}, {"action":"block_and_alert_trust_safety"}, 0.95, ConfidenceTier.VERIFIED, []),
        ("Competitive pressure allows +5% above standard authority", "sales", "wf_discount", {"condition":"competitive_flag == true"}, {"action":"competitive_override_plus_5"}, 0.74, ConfidenceTier.VALIDATED_PEER, []),
        ("Duplicate invoices must be blocked immediately", "finance", "wf_payment", {"condition":"duplicate_detected == true"}, {"action":"block_and_alert"}, 0.93, ConfidenceTier.VERIFIED, ["SOX"]),
        ("Maintenance window suppresses P1 alerts", "engineering", "wf_incident", {"condition":"active_maintenance_window"}, {"action":"suppress_log_notify_lead"}, 0.92, ConfidenceTier.VERIFIED, []),
    ]
    for stmt, domain, wf, trigger, action, conf, tier, tags in defs:
        vec = {"source_breadth": min(conf+0.04, 1.0), "source_authority": min(conf+0.02, 1.0), "temporal_freshness": 0.85, "outcome_validation": conf, "explicit_validation": 0.85 if tier in [ConfidenceTier.VALIDATED_DH, ConfidenceTier.VERIFIED] else 0.6}
        rules.append(Rule(
            id=_id(), tenant_id=T, statement=stmt, trigger_json=trigger,
            action_json=action, domain=domain, workflow_id=wf,
            confidence_vector=vec, confidence_scalar=conf, confidence_tier=tier,
            half_life_days=90 if domain == "support" else 60 if domain == "sales" else 180,
            is_executable=conf >= 0.60, compliance_tags=tags,
            validated_at=NOW - timedelta(days=15), access_level="department",
        ))
    return rules


def seed_questions():
    return [
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_1", question_text="Hey Sarah 👋 In ticket #4821 you approved a refund for an order outside the 30-day window. What was the deciding factor?", question_type="ARTICULATION", context_ref="ticket_4821", priority="HIGH", delivery_channel="slack", specificity=0.92, groundedness=0.95, answerability=0.88, status="PENDING"),
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_2", question_text="Hey Marcus 👋 You approved a 22% discount for a 6-year customer last week. Is there an unwritten rule about tenure-based discount authority?", question_type="GAP_FILL", context_ref="deal_CRM_8834", priority="HIGH", delivery_channel="slack", specificity=0.89, groundedness=0.91, answerability=0.85, status="PENDING"),
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_3", question_text="Hey Priya 👋 During last Tuesday's P1 you escalated to CTO at 45 minutes instead of the standard 60. What triggered the earlier escalation?", question_type="CONTRADICTION", context_ref="incident_INC_2241", priority="NORMAL", delivery_channel="slack", specificity=0.94, groundedness=0.93, answerability=0.87, status="ANSWERED", answer_text="The service affected was the payment gateway which has a stricter SLA. Any payment-related P1 gets CTO visibility at 45 min, not 60.", answered_at=NOW-timedelta(days=2)),
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_4", question_text="Hey James 👋 Three recent vendor payments over $50K were approved by finance manager instead of VP Finance. Has the authority threshold changed?", question_type="DECAY_REVALIDATION", context_ref="payment_batch_Q1", priority="HIGH", delivery_channel="slack", specificity=0.88, groundedness=0.90, answerability=0.82, status="PENDING"),
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_5", question_text="Hey Lin 👋 The onboarding for the last 3 remote international hires included an extra legal review step not in the standard process. Should this be a permanent rule?", question_type="GAP_FILL", context_ref="onboard_batch_apr", priority="NORMAL", delivery_channel="slack", specificity=0.91, groundedness=0.89, answerability=0.90, status="ANSWERED", answer_text="Yes - any hire outside the HQ country needs local employment law review. Legal mandated this in January.", answered_at=NOW-timedelta(days=5)),
        ElicitationQuestion(id=_id(), tenant_id=T, employee_id="emp_6", question_text="Hey Alex 👋 You marked deal #9912 as STRONG qualification despite missing the economic buyer dimension. What made you confident?", question_type="ARTICULATION", context_ref="deal_CRM_9912", priority="NORMAL", delivery_channel="slack", specificity=0.87, groundedness=0.92, answerability=0.83, status="PENDING"),
    ]


def seed_executions(skills):
    """Generate sample execution history for each skill."""
    import random
    random.seed(42)
    execs = []
    {s.skill_id: s for s in skills}
    statuses = ["SUCCESS_CLEAN", "SUCCESS_CLEAN", "SUCCESS_CLEAN", "SUCCESS_CLEAN",
                 "SUCCESS_CLEAN", "SUCCESS_WITH_EDIT", "HUMAN_OVERRIDDEN", "FAILED_RULE_MISMATCH"]
    intents = {
        "handle_refund_request": ["Process refund for order #ORD-{}", "Customer requesting refund on order #{}", "Refund ticket #{} needs processing"],
        "enterprise_discount_approval": ["20% discount requested on deal #{}", "Enterprise discount for opportunity #{}", "Pricing exception for account #{}"],
        "incident_escalation_p1": ["P1: Error rate spike on service-{}", "Critical: Payment gateway down #{}", "P1 declared: latency > 5s on api-{}"],
        "vendor_payment_approval": ["Invoice #{} submitted for payment", "Vendor payment request #{}", "AP queue: payment pending #{}"],
        "new_hire_onboarding_trigger": ["New hire starting: Employee #{}", "Onboarding trigger for #{}", "Offer accepted: start date in {} days"],
        "sales_deal_qualification": ["Qualify opportunity #{}", "New deal qualification #{}", "Pipeline review: deal #{}"],
    }
    for skill in skills:
        templates = intents.get(skill.skill_id, ["Task #{}"])
        for _i in range(min(20, skill.execution_count)):
            status = random.choice(statuses)
            dur = random.randint(50, 2000)
            delta = 0.02 if "SUCCESS" in status else -0.05
            started = NOW - timedelta(hours=random.randint(1, 168))
            execs.append(SkillExecution(
                id=_id(), skill_db_id=skill.id, skill_id_name=skill.skill_id,
                tenant_id=T, status=status, route_type="SKILL_EXEC",
                agent_state="COMPLETED",
                task_intent=random.choice(templates).format(random.randint(1000, 9999)),
                reasoning_chain=[{"step": j+1, "action": s.get("action","step"), "status": "EXECUTED"} for j, s in enumerate(skill.steps[:3])],
                started_at=started, completed_at=started+timedelta(milliseconds=dur),
                duration_ms=dur, hitl_required=skill.confidence < 0.82,
                outcome_type=status, confidence_delta=delta,
            ))
    return execs


def seed_connectors():
    NOW_L = datetime.now(timezone.utc)
    connectors_data = [
        ("Team Messaging", "communications", "NATIVE", "CONNECTED", "💬", "Real-time messaging signals from team channels", "oauth2", "REAL_TIME", 48210, 3841, 0, 42, NOW_L-timedelta(minutes=3)),
        ("Video Conferencing", "communications", "NATIVE", "CONNECTED", "🟦", "Video meetings, recordings, and channel activity", "oauth2", "REAL_TIME", 31450, 2190, 0, 58, NOW_L-timedelta(minutes=7)),
        ("Email Platform", "communications", "API", "CONNECTED", "📧", "Email threads, calendar events, and meeting notes", "oauth2", "HOURLY", 22180, 1540, 0, 120, NOW_L-timedelta(hours=1)),
        ("CRM Platform", "crm", "NATIVE", "CONNECTED", "☁️", "CRM opportunities, accounts, contacts, and deal activity", "oauth2", "REAL_TIME", 18920, 4210, 0, 85, NOW_L-timedelta(minutes=5)),
        ("Marketing CRM", "crm", "API", "AVAILABLE", "🟠", "Marketing and sales CRM data, deal pipelines", "api_key", "HOURLY", 0, 0, 0, 0, None),
        ("HRIS Platform", "hris", "NATIVE", "CONNECTED", "🏢", "HR records, org charts, compensation, and performance data", "service_account", "DAILY", 8450, 920, 0, 340, NOW_L-timedelta(hours=6)),
        ("Support Helpdesk", "support", "NATIVE", "CONNECTED", "🎫", "Support tickets, resolution patterns, and CSAT data", "oauth2", "REAL_TIME", 52800, 6130, 2, 38, NOW_L-timedelta(minutes=2)),
        ("Issue Tracker", "engineering", "NATIVE", "CONNECTED", "🔷", "Engineering issues, sprint velocity, and incident tracking", "oauth2", "REAL_TIME", 29340, 2870, 1, 55, NOW_L-timedelta(minutes=8)),
        ("Code Repository", "engineering", "WEBHOOK", "CONNECTED", "🐙", "Code reviews, PR decisions, and deployment events", "oauth2", "REAL_TIME", 15200, 1240, 0, 31, NOW_L-timedelta(minutes=12)),
        ("ITSM Platform", "support", "API", "CONNECTED", "🟢", "ITSM incidents, change requests, and CMDB updates", "service_account", "HOURLY", 11800, 1580, 0, 145, NOW_L-timedelta(hours=1)),
        ("Wiki Platform", "knowledge", "API", "CONNECTED", "📘", "Wiki pages, SOPs, and decision documentation", "oauth2", "DAILY", 6200, 890, 0, 280, NOW_L-timedelta(hours=12)),
        ("Call Recording", "commercial", "API", "AVAILABLE", "🎙️", "Sales call recordings, talk patterns, and competitive intel", "api_key", "DAILY", 0, 0, 0, 0, None),
        ("Alerting Platform", "engineering", "WEBHOOK", "CONNECTED", "🔔", "Incident alerts, on-call schedules, and escalation data", "api_key", "REAL_TIME", 7800, 1120, 0, 22, NOW_L-timedelta(minutes=1)),
        ("Team Wiki", "knowledge", "API", "AVAILABLE", "📓", "Team wikis, project docs, and meeting notes", "oauth2", "HOURLY", 0, 0, 0, 0, None),
        ("Productivity Suite", "communications", "API", "AVAILABLE", "🔵", "Email, Drive, Calendar, and Meet signals", "oauth2", "HOURLY", 0, 0, 0, 0, None),
        ("ERP System", "finance", "API", "AVAILABLE", "◾", "ERP financial transactions, procurement, and vendor data", "service_account", "DAILY", 0, 0, 0, 0, None),
        ("Chat Support", "support", "API", "CONNECTED", "💜", "Customer conversations, bot interactions, and support metrics", "api_key", "REAL_TIME", 14300, 1890, 0, 44, NOW_L-timedelta(minutes=4)),
        ("HR Management", "hris", "API", "AVAILABLE", "🎋", "Employee records, time-off, and onboarding workflows", "api_key", "DAILY", 0, 0, 0, 0, None),
        # Engineering & IT Ops — the largest slice of enterprise AI spend. These
        # map onto real live adapters (see app/services/vendor_adapters.py), so a
        # tenant can attach credentials and sync immediately.
        ("Source Control", "engineering", "API", "AVAILABLE", "🐙", "GitHub pull requests, reviews, and merge activity", "api_key", "REAL_TIME", 0, 0, 0, 0, None),
        ("Observability", "observability", "API", "AVAILABLE", "🐶", "Datadog monitors, alert states, and service health", "api_key", "HOURLY", 0, 0, 0, 0, None),
        ("Error Tracking", "engineering", "API", "AVAILABLE", "🛡️", "Sentry unresolved issues, error volume, and culprits", "api_key", "REAL_TIME", 0, 0, 0, 0, None),
        ("Incident Management", "incident", "API", "AVAILABLE", "📟", "PagerDuty incidents, urgency, and on-call escalation", "api_key", "REAL_TIME", 0, 0, 0, 0, None),
        # Other domains with live adapters but no connector row until now.
        ("Recruiting ATS", "ats", "API", "AVAILABLE", "🌱", "Greenhouse candidates and pipeline stages", "api_key", "DAILY", 0, 0, 0, 0, None),
        ("Payments", "payments", "API", "AVAILABLE", "💳", "Stripe invoices, charges, and settlement status", "api_key", "HOURLY", 0, 0, 0, 0, None),
        ("E-Signature", "legal", "API", "AVAILABLE", "✍️", "DocuSign envelopes and signature completion status", "oauth2", "HOURLY", 0, 0, 0, 0, None),
    ]
    result = []
    for name, cat, ctype, status, icon, desc, auth, freq, events, signals, errors, latency, sync_at in connectors_data:
        result.append(Connector(
            id=_id(), tenant_id=T, name=name, category=cat, connector_type=ctype,
            status=status, icon=icon, description=desc, auth_method=auth,
            sync_frequency=freq, last_sync_at=sync_at, events_ingested=events,
            signals_extracted=signals, error_count=errors, avg_latency_ms=latency,
            pii_scrub_enabled=True, pii_entities_found=events // 12 if events else 0,
            connected_at=sync_at - timedelta(days=30) if sync_at else None,
        ))
    return result


def seed_conflicts(rules):
    if len(rules) < 4:
        return []
    NOW_L = datetime.now(timezone.utc)
    return [
        ConflictCase(id=_id(), tenant_id=T, rule_a_id=rules[5].id, rule_b_id=rules[8].id,
                     conflict_type="SCOPE_OVERLAP", severity="CRITICAL", status="OPEN",
                     assigned_to="Marcus Rivera", deadline=NOW_L+timedelta(days=5),
                     detected_at=NOW_L-timedelta(days=2)),
        ConflictCase(id=_id(), tenant_id=T, rule_a_id=rules[12].id, rule_b_id=rules[14].id,
                     conflict_type="DIRECT_CONTRADICTION", severity="MODERATE", status="IN_REVIEW",
                     assigned_to="James Mitchell", deadline=NOW_L+timedelta(days=3),
                     detected_at=NOW_L-timedelta(days=4)),
        ConflictCase(id=_id(), tenant_id=T, rule_a_id=rules[0].id, rule_b_id=rules[19].id,
                     conflict_type="SCOPE_OVERLAP", severity="MINOR", status="RESOLVED",
                     resolution_type="MERGE", resolution_note="LTV override applies as exception to auto-approve rule",
                     detected_at=NOW_L-timedelta(days=10), resolved_at=NOW_L-timedelta(days=7)),
        ConflictCase(id=_id(), tenant_id=T, rule_a_id=rules[9].id, rule_b_id=rules[23].id,
                     conflict_type="TEMPORAL_SUPERSESSION", severity="MODERATE", status="OPEN",
                     assigned_to="Priya Patel", deadline=NOW_L+timedelta(days=4),
                     detected_at=NOW_L-timedelta(days=1)),
    ]


def seed_marketplace():
    return [
        MarketplaceTemplate(id=_id(), name="Customer Support Starter Kit", category="Support", description="47 pre-seeded rules covering refund processing, escalation paths, SLA workflows, and CSAT optimization.", author="KAEOS Labs", version="2.3", rating=4.9, installs=1240, rules_count=47, skills_count=6, tags=["refunds","escalation","sla","csat"], compliance_frameworks=["GDPR","CCPA"], certified=True, preview_data={"sample_rules": 3, "avg_confidence": 0.88}),
        MarketplaceTemplate(id=_id(), name="Sales Playbook Foundation", category="Sales", description="61 rules for discount approval, competitive response, deal qualification, and renewal management.", author="KAEOS Labs", version="3.1", rating=4.7, installs=892, rules_count=61, skills_count=8, tags=["discounts","deals","qualification","pricing"], compliance_frameworks=["SOX"], certified=True, preview_data={"sample_rules": 4, "avg_confidence": 0.85}),
        MarketplaceTemplate(id=_id(), name="SOX Compliance Controls", category="Finance", description="34 compliance-tagged rules for financial approval chains, audit trail requirements, and segregation of duties.", author="ComplianceFirst Inc.", version="1.8", rating=4.9, installs=312, rules_count=34, skills_count=4, tags=["sox","audit","approval","controls"], compliance_frameworks=["SOX","GAAP"], certified=True, preview_data={"sample_rules": 2, "avg_confidence": 0.91}),
        MarketplaceTemplate(id=_id(), name="Engineering On-Call Runbook", category="Engineering", description="29 rules for incident escalation, severity classification, SLA targets, and postmortem triggers.", author="KAEOS Labs", version="2.0", rating=4.6, installs=567, rules_count=29, skills_count=5, tags=["incidents","oncall","sla","postmortem"], compliance_frameworks=["SOC2"], certified=True, preview_data={"sample_rules": 3, "avg_confidence": 0.92}),
        MarketplaceTemplate(id=_id(), name="GDPR Data Handling Pack", category="Legal", description="22 rules for consent management, data retention, right-to-erasure workflows, and DPA compliance.", author="PrivacyShield Co.", version="1.5", rating=4.8, installs=445, rules_count=22, skills_count=3, tags=["gdpr","privacy","consent","erasure"], compliance_frameworks=["GDPR","CCPA"], certified=True, preview_data={"sample_rules": 2, "avg_confidence": 0.87}),
        MarketplaceTemplate(id=_id(), name="HR Onboarding Accelerator", category="HR", description="18 rules for new hire provisioning, buddy assignment, compliance training, and 30/60/90 day plans.", author="PeopleOps Hub", version="1.2", rating=4.4, installs=289, rules_count=18, skills_count=3, tags=["onboarding","provisioning","training"], compliance_frameworks=["EEOC","I9"], certified=False, preview_data={"sample_rules": 2, "avg_confidence": 0.84}),
        MarketplaceTemplate(id=_id(), name="Vendor Risk Management", category="Finance", description="15 rules for vendor assessment, payment authority matrices, and third-party risk scoring.", author="RiskIQ Partners", version="1.0", rating=4.3, installs=156, rules_count=15, skills_count=2, tags=["vendor","risk","payments","authority"], compliance_frameworks=["SOX","PCI_DSS"], certified=False, preview_data={"sample_rules": 2, "avg_confidence": 0.82}),
        MarketplaceTemplate(id=_id(), name="Customer Success Playbook", category="Support", description="25 rules for churn prediction triggers, health scoring, QBR preparation, and expansion signals.", author="CSM Academy", version="1.1", rating=4.5, installs=201, rules_count=25, skills_count=4, tags=["churn","health","qbr","expansion"], compliance_frameworks=[], certified=False, preview_data={"sample_rules": 2, "avg_confidence": 0.80}),
    ]


def seed_security_logs():
    NOW_L = datetime.now(timezone.utc)
    logs = []
    events = [
        ("ACCESS", "h1", "Support Manager", "RULE", "READ", "ALLOWED", {"query": "refund rules", "count": 5}),
        ("MODIFICATION", "h2", "VP Sales", "RULE", "WRITE", "ALLOWED", {"field": "discount threshold", "old": "15%", "new": "20%"}),
        ("AGENT_EXEC", "agent_runtime", "system", "SKILL", "EXECUTE", "ALLOWED", {"skill": "handle_refund_request", "duration_ms": 450}),
        ("AUTH_FAILURE", "unknown", "anonymous", "SKILL", "EXECUTE", "BLOCKED", {"reason": "invalid_token", "ip": "192.168.1.100"}),
        ("QUERY", "h3", "SRE Lead", "PROVENANCE", "READ", "ALLOWED", {"rule_id": "rule_123", "chain_depth": 4}),
        ("EXPORT", "h4", "CFO", "RULE", "EXPORT", "ALLOWED", {"format": "csv", "rules_count": 24, "domain": "finance"}),
        ("ACCESS", "h5", "HR Director", "SKILL", "READ", "ALLOWED", {"skill": "new_hire_onboarding_trigger"}),
        ("MODIFICATION", "h3", "SRE Lead", "RULE", "WRITE", "ALLOWED", {"action": "archived stale rule"}),
        ("AGENT_EXEC", "agent_runtime", "system", "SKILL", "EXECUTE", "ALLOWED", {"skill": "incident_escalation_p1", "duration_ms": 120}),
        ("AUTH_FAILURE", "unknown", "anonymous", "RULE", "WRITE", "BLOCKED", {"reason": "insufficient_permissions"}),
        ("ACCESS", "h6", "Account Executive", "RULE", "READ", "ALLOWED", {"query": "discount authority", "count": 3}),
        ("AGENT_EXEC", "agent_runtime", "system", "SKILL", "EXECUTE", "ESCALATED", {"skill": "vendor_payment_approval", "reason": "low_confidence"}),
    ]
    for i, (etype, actor, role, rtype, action, result, details) in enumerate(events):
        logs.append(SecurityAuditLog(
            id=_id(), tenant_id=T, event_type=etype, actor_hash=actor,
            actor_role=role, resource_type=rtype, resource_id=None,
            action=action, result=result, ip_address=f"10.0.{i//4}.{100+i}",
            details=details, timestamp=NOW_L-timedelta(hours=i*2),
        ))
    return logs


def seed_decay_events(rules):
    NOW_L = datetime.now(timezone.utc)
    events = []
    for i, r in enumerate(rules[:8]):
        conf_before = r.confidence_scalar
        conf_after = round(conf_before * 0.95, 4)
        events.append(DecayEvent(
            id=_id(), tenant_id=T, rule_id=r.id,
            event_type="SCHEDULED_DECAY", confidence_before=conf_before,
            confidence_after=conf_after, half_life_days=r.half_life_days,
            days_since_validation=15+i*5, action_taken="DECAY_APPLIED",
            timestamp=NOW_L-timedelta(hours=i*6),
        ))
    # Add some trigger-based events
    if len(rules) > 6:
        events.append(DecayEvent(
            id=_id(), tenant_id=T, rule_id=rules[6].id,
            event_type="TRIGGER_INVALIDATION", trigger_source="pricing_sheet_updated",
            confidence_before=0.88, confidence_after=0.44,
            half_life_days=60, days_since_validation=0,
            action_taken="ELICITATION_TRIGGERED",
            timestamp=NOW_L-timedelta(days=1),
        ))
    return events


def seed_redteam_scans(skills):
    NOW_L = datetime.now(timezone.utc)
    scans = []
    scan_types = ["BOUNDARY", "ADVERSARIAL", "CONFIDENCE_CALIBRATION", "STALE_DATA", "CROSS_SKILL"]
    for s in skills:
        for j, stype in enumerate(scan_types):
            vuln_count = 0
            status = "PASSED"
            details = []
            if s.confidence < 0.90 and stype == "ADVERSARIAL":
                vuln_count = 1
                status = "WARNING"
                details = [{"type": "LOW_CONFIDENCE_BYPASS", "severity": "MEDIUM", "description": f"Skill {s.skill_id} confidence {s.confidence} below autonomous threshold during adversarial input"}]
            if s.confidence < 0.85 and stype == "BOUNDARY":
                vuln_count = 1
                status = "FAILED"
                details = [{"type": "THRESHOLD_EDGE_CASE", "severity": "HIGH", "description": "Boundary condition at threshold produced undefined behavior"}]
            scans.append(RedTeamScanResult(
                id=_id(), tenant_id=T, skill_id=s.skill_id,
                skill_department=s.department, scan_type=stype,
                status=status, vulnerabilities_found=vuln_count,
                details=details, confidence_at_scan=s.confidence,
                duration_ms=120+j*80,
                scanned_at=NOW_L-timedelta(hours=j*4),
            ))
    return scans


def seed_llm_routing():
    """
    Seed the local-first BYOK defaults. No API keys are seeded — a tenant
    supplies their own via PUT /config/llm-routing, which encrypts them.
    """
    return [
        TenantLLMConfig(id=_id(), tenant_id=T, layer="TIER_1_COMPLEX",
                        model_name="ollama/qwen2.5-coder:7b", provider="ollama"),
        TenantLLMConfig(id=_id(), tenant_id=T, layer="TIER_2_STANDARD",
                        model_name="ollama/phi4-mini:latest", provider="ollama"),
        TenantLLMConfig(id=_id(), tenant_id=T, layer="TIER_3_FAST",
                        model_name="ollama/phi4-mini:latest", provider="ollama"),
    ]


def seed_mcp_tools():
    # No api_key here: the column is `api_key_encrypted` (Fernet, write-only) since
    # the plaintext-key security fix. Demo tools seed WITHOUT a key; a real key is
    # set via the write-only API. Passing api_key= crashed fresh-DB boot at seeding.
    return [
        MCPToolConfig(id=_id(), tenant_id=T, tool_id="crm_bulk_api", is_active=True, rate_limit_per_hour=200),
        MCPToolConfig(id=_id(), tenant_id=T, tool_id="payment_gateway", is_active=True, rate_limit_per_hour=100),
        MCPToolConfig(id=_id(), tenant_id=T, tool_id="helpdesk_connector", is_active=True, rate_limit_per_hour=500),
        MCPToolConfig(id=_id(), tenant_id=T, tool_id="issue_tracker", is_active=True, rate_limit_per_hour=300),
    ]


def seed_ontology_config():
    return [
        OntologyConfig(id=_id(), tenant_id=T, department="customer_support", default_half_life_days=90),
        OntologyConfig(id=_id(), tenant_id=T, department="engineering", default_half_life_days=120),
        OntologyConfig(id=_id(), tenant_id=T, department="sales", default_half_life_days=30),
        OntologyConfig(id=_id(), tenant_id=T, department="human_resources", default_half_life_days=180),
        OntologyConfig(id=_id(), tenant_id=T, department="finance", default_half_life_days=180),
        OntologyConfig(id=_id(), tenant_id=T, department="legal", default_half_life_days=365),
    ]


def seed_federated_config():
    return [
        FederatedConfig(id=_id(), tenant_id=T, department="customer_support", opt_in=True),
        FederatedConfig(id=_id(), tenant_id=T, department="engineering", opt_in=True),
        FederatedConfig(id=_id(), tenant_id=T, department="sales", opt_in=False),
        FederatedConfig(id=_id(), tenant_id=T, department="human_resources", opt_in=False),
        FederatedConfig(id=_id(), tenant_id=T, department="finance", opt_in=False),
        FederatedConfig(id=_id(), tenant_id=T, department="legal", opt_in=False),
    ]


async def top_up_new_entities(db_session) -> dict:
    """
    Add rows for things that shipped after this tenant was first seeded.

    seed_database() short-circuits entirely once the KB is seeded, so without
    this an existing tenant would never see a newly supported integration or a
    newly added department — the code would exist with no row to hang off.
    Idempotent: matches on natural keys and only inserts what's missing.
    """
    from sqlalchemy import select

    added = {"connectors": 0, "departments": 0}

    existing_names = set((await db_session.execute(
        select(Connector.name).where(Connector.tenant_id == T)
    )).scalars().all())
    for conn in seed_connectors():
        if conn.name not in existing_names:
            db_session.add(conn)
            added["connectors"] += 1

    try:
        from app.workforce.models.core import Department

        existing_slugs = set((await db_session.execute(
            select(Department.slug).where(Department.tenant_id == T)
        )).scalars().all())
        for dept in seed_departments():
            if dept.slug not in existing_slugs:
                db_session.add(dept)
                added["departments"] += 1
    except Exception as e:
        logger.warning(f"[Seed] Department top-up skipped: {e}")

    # Payroll runs shipped with the HR vertical but were never seeded, leaving
    # the finance payroll-audit agent with no entity to ever run against.
    try:
        from datetime import date, timedelta

        from app.hr.models.payroll import PayrollRun

        added["payroll_runs"] = 0
        existing_runs = (await db_session.execute(
            select(PayrollRun).where(PayrollRun.tenant_id == T).limit(1)
        )).scalars().first()
        if not existing_runs:
            today = NOW.date() if NOW else date.today()
            for months_back in (2, 1):
                start = (today.replace(day=1) - timedelta(days=months_back * 30)).replace(day=1)
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                db_session.add(PayrollRun(
                    tenant_id=T,
                    period_start=start,
                    period_end=end,
                    pay_date=end,
                    total_gross=412_500.00,
                    total_net=298_430.75,
                    total_taxes=87_190.25,
                    total_deductions=26_879.00,
                ))
                added["payroll_runs"] += 1
    except Exception as e:
        logger.warning(f"[Seed] Payroll top-up skipped: {e}")

    if any(added.values()):
        await db_session.commit()
    return added


def seed_blueprints():
    """A few representative Agent Factory blueprints so a fresh deploy's Agent
    Factory is not empty (blueprints otherwise only accrue from live use)."""
    defs = [
        ("Contract Compliance Reviewer", "Review new-hire contracts against employment policy, flag GDPR issues, notify Legal.", "legal", "Legal", BlueprintStatus.DEPLOYED),
        ("Invoice Anomaly Auditor", "Scan incoming invoices for duplicate charges and out-of-policy amounts before AP approval.", "finance", "Finance", BlueprintStatus.APPROVED),
        ("Churn-Risk Watchdog", "Score at-risk accounts nightly and draft a save-play for the owning rep.", "sales", "Sales", BlueprintStatus.COMPILED),
        ("Incident Triage Copilot", "Classify P1 incidents, correlate to recent deploys, and page the on-call engineer.", "engineering", "Engineering", BlueprintStatus.DEPLOYED),
    ]
    out = []
    for name, desc, domain, dept, status in defs:
        out.append(AgentBlueprint(
            id=_id(), tenant_id=T, name=name, description=desc,
            domain=domain, department=dept, status=status,
            blueprint_graph={"nodes": [{"id": "n1", "type": "trigger"}, {"id": "n2", "type": "reason"}, {"id": "n3", "type": "act"}], "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}]},
            compliance_tags=["SOX"] if domain == "finance" else (["GDPR"] if domain == "legal" else []),
            confidence_floor=0.82, created_by="seed",
        ))
    return out


def seed_signals():
    """Representative enterprise signals so the Extraction/Company-Brain surfaces
    have live-looking data on a fresh deploy (signals otherwise only arrive from
    connector syncs)."""
    defs = [
        ("helpdesk", "TICKET-4821", "EXCEPTION", "support", "Customer escalated: refund not processed after 5 days despite policy.", 0.7, 0.6),
        ("messaging", "slack:#finance", "APPROVAL", "finance", "CFO approved Q3 vendor payment batch over $50k threshold.", 0.9, 0.4),
        ("issue_tracker", "JIRA-1290", "DECISION", "engineering", "Decided to roll back payments-api v2.3 after error-rate spike.", 0.85, 0.7),
        ("crm", "ACC-556", "EXCEPTION", "sales", "Enterprise account flagged at-risk: usage down 40% MoM.", 0.75, 0.65),
        ("hris", "REQ-77", "DECISION", "hr", "Approved backfill for Senior Engineer role in Platform squad.", 0.8, 0.3),
        ("messaging", "slack:#legal", "APPROVAL", "legal", "GC approved standard MSA redlines for mid-market tier.", 0.88, 0.35),
    ]
    out = []
    for src, entity, stype, domain, payload, auth, nov in defs:
        out.append(Signal(
            id=_id(), tenant_id=T, source_type=src, source_entity=entity,
            signal_type=stype, domain=domain, clean_payload=payload,
            authority_score=auth, novelty_score=nov, temporal_class="CURRENT",
            entities=[], pii_present=False,
        ))
    return out


async def seed_database(db_session):
    """Main seed function - call on startup."""
    global NOW
    NOW = datetime.now(timezone.utc)

    from sqlalchemy import select
    existing = await db_session.execute(select(Skill).limit(1))
    if existing.scalar_one_or_none():
        # Already seeded, but things shipped since then still need their rows.
        try:
            added = await top_up_new_entities(db_session)
            if any(added.values()):
                logger.info(f"[Seed] Top-up added {added['connectors']} connector(s), "
                            f"{added['departments']} department(s)")
        except Exception as e:
            logger.warning(f"[Seed] Top-up failed (non-fatal): {e}")
        return False  # Already seeded

    workflows = seed_workflows()
    employees = seed_employees()
    skills = seed_skills()
    rules = seed_rules()
    questions = seed_questions()
    executions = seed_executions(skills)
    connectors = seed_connectors()
    conflicts = seed_conflicts(rules)
    templates = seed_marketplace()
    sec_logs = seed_security_logs()
    decay_evts = seed_decay_events(rules)
    rt_scans = seed_redteam_scans(skills)
    llm_configs = seed_llm_routing()
    mcp_tools = seed_mcp_tools()
    ontology_cfgs = seed_ontology_config()
    federated_cfgs = seed_federated_config()

    departments = seed_departments()
    blueprints = seed_blueprints()
    signals = seed_signals()

    all_objects = (departments + workflows + employees + skills + rules + questions +
                   executions + connectors + conflicts + templates +
                   sec_logs + decay_evts + rt_scans +
                   llm_configs + mcp_tools + ontology_cfgs + federated_cfgs +
                   blueprints + signals)
    for obj in all_objects:
        db_session.add(obj)

    await db_session.commit()
    return True
