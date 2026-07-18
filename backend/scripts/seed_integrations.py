"""
KAEOS — External Intelligence & Integrations Seeder
Seeds signals, proactive alerts, and external intelligence data
for Company Brain → Extraction → Pioneer layers.
"""
import asyncio
import uuid
import random
from datetime import datetime, timezone, timedelta

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base, Signal

TENANT = "tenant_acme"
NOW = datetime.now(timezone.utc)



def _id():
    return str(uuid.uuid4())


SIGNAL_DEFS = [
    # Communication signals (Slack, Teams)
    ("COMMUNICATION", "slack_support", "decision_pattern", "support",
     "Agent Sarah approved 3 refunds over $200 for enterprise customers without manager sign-off, citing LTV override", 0.88, 0.72),
    ("COMMUNICATION", "slack_sales", "competitive_intel", "sales",
     "Competitor X just launched a 15% discount campaign targeting our mid-market segment — discussed in #sales-strategy", 0.75, 0.95),
    ("COMMUNICATION", "teams_engineering", "incident_pattern", "engineering",
     "P1 incidents involving the payment gateway have 3x faster escalation to CTO than other services", 0.92, 0.45),
    ("COMMUNICATION", "slack_hr", "policy_update", "hr",
     "HR Director announced new remote-first policy for international hires — requires local legal review before onboarding", 0.91, 0.88),
    # CRM signals
    ("CRM", "salesforce_opportunities", "deal_pattern", "sales",
     "Deals with champion-level contacts close 2.3x faster than those without — pattern detected across 847 closed-won deals", 0.94, 0.67),
    ("CRM", "salesforce_accounts", "churn_risk", "sales",
     "Account Acme Corp shows declining engagement: -40% login frequency, 3 open support tickets, no QBR in 90 days", 0.86, 0.81),
    # HRIS signals
    ("HRIS", "workday_events", "attrition_risk", "hr",
     "Engineering team attrition rate spiked to 18% in Q2 — exit interviews cite compensation and remote policy as top factors", 0.89, 0.73),
    ("HRIS", "bamboohr_onboarding", "process_gap", "hr",
     "12 of last 20 international hires had IT provisioning delays exceeding 5 business days — SLA breach", 0.93, 0.82),
    # Helpdesk signals
    ("HELPDESK", "zendesk_tickets", "escalation_pattern", "support",
     "Tickets tagged 'billing-error' have 4x higher escalation rate than average — root cause may be payment gateway integration", 0.87, 0.76),
    ("HELPDESK", "intercom_chat", "sentiment_shift", "support",
     "Customer sentiment in live chat dropped 12 points this week — correlates with new pricing tier rollout", 0.79, 0.91),
    # Engineering signals
    ("CODE_REPO", "github_prs", "knowledge_gap", "engineering",
     "PR reviews in the payments module take 3x longer than other modules — only 2 engineers have deep context", 0.85, 0.68),
    ("ALERTING", "pagerduty_incidents", "sla_drift", "engineering",
     "Mean time to acknowledge P2 incidents has drifted from 8 min to 14 min over the last 30 days", 0.91, 0.55),
    # Finance signals
    ("ERP", "sap_invoices", "fraud_pattern", "finance",
     "3 invoices from vendor V-2847 show round-number amounts ($10,000 exactly) and same-day submission — possible duplicate billing", 0.83, 0.94),
    ("WIKI", "confluence_policies", "policy_update", "finance",
     "CFO updated the vendor payment authority matrix — threshold for auto-approval raised from $5K to $7.5K effective Q3", 0.96, 0.78),
    # Legal signals
    ("DOCUMENT", "docusign_contracts", "clause_risk", "legal",
     "New vendor contract contains unlimited liability clause not present in our standard template — flagged for legal review", 0.88, 0.86),
    ("REGULATORY", "regulatory_feed", "compliance_change", "legal",
     "EU AI Act Article 6 enforcement begins Jan 2027 — impacts 4 of our deployed AI agents classified as high-risk", 0.95, 0.97),
]

async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        signals = []

        for i, (src_type, src_entity, sig_type, domain, payload, authority, novelty) in enumerate(SIGNAL_DEFS):
            signals.append(Signal(
                id=_id(),
                tenant_id=TENANT,
                source_type=src_type,
                source_entity=src_entity,
                signal_type=sig_type,
                domain=domain,
                clean_payload=payload,
                authority_score=authority,
                novelty_score=novelty,
                pii_present=random.random() < 0.15,
                created_at=NOW - timedelta(hours=i * 4 + random.randint(0, 6)),
            ))

        for obj in signals:
            db.add(obj)

        await db.commit()
        print(f"[Integrations Seed] Created {len(signals)} signals")



if __name__ == "__main__":
    asyncio.run(seed())
