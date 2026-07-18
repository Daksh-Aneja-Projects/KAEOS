"""
KAEOS Support Domain — Database Seed Script
Seeds the Support tables with realistic queues, SLA guidelines, articles, and surveys.
"""
import asyncio
import uuid
from datetime import date

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.support.models.core import SupportAgent, SupportTeam, SupportChannel, ChannelType
from app.support.models.tickets import Ticket, TicketComment, TicketTag, TicketPriority, TicketStatus
from app.support.models.sla import SLAPolicy, SLAMetric
from app.support.models.knowledge import KBArticle, KBCategory
from app.support.models.feedback import CustomerSatisfaction, NPS_Survey, FeedbackTheme
from app.support.models.escalation import EscalationRule

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())

async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Support Teams
        teams = [
            SupportTeam(id=_id(), tenant_id=TENANT, name="Tier 1 General Support", description="First level triage and password resets", tier=1),
            SupportTeam(id=_id(), tenant_id=TENANT, name="Tier 2 Technical Support", description="Database errors and API integrations", tier=2),
            SupportTeam(id=_id(), tenant_id=TENANT, name="Tier 3 Billing Support", description="Invoicing questions and refunds", tier=3),
        ]
        for t in teams:
            db.add(t)
        await db.flush()

        # 2. Support Agents
        agents = [
            SupportAgent(id=_id(), tenant_id=TENANT, name="Michael Scott", email="michael.scott@kaeos.io", team_id=teams[0].id, is_ai=False, is_active=True),
            SupportAgent(id=_id(), tenant_id=TENANT, name="Triage Bot", email="triage.bot@kaeos.io", team_id=teams[0].id, is_ai=True, is_active=True),
            SupportAgent(id=_id(), tenant_id=TENANT, name="Pam Beesly", email="pam.beesly@kaeos.io", team_id=teams[1].id, is_ai=False, is_active=True),
        ]
        for a in agents:
            db.add(a)
        await db.flush()

        # 3. Support Channels
        channels = [
            SupportChannel(id=_id(), tenant_id=TENANT, channel_name="Email Ingress", channel_type=ChannelType.EMAIL, routing_team_id=teams[0].id, is_active=True),
            SupportChannel(id=_id(), tenant_id=TENANT, channel_name="Web Portal Widget", channel_type=ChannelType.PORTAL, routing_team_id=teams[0].id, is_active=True),
        ]
        for ch in channels:
            db.add(ch)
        await db.flush()

        # 4. Tickets
        tickets = [
            Ticket(id=_id(), tenant_id=TENANT, ticket_number="TCK-99012", customer_id="CST001", subject="Password reset link fails with 500 error", description="Clicking the recovery link redirected to a blank white screen with error 500.", status=TicketStatus.NEW, priority=TicketPriority.HIGH, assigned_agent_id=agents[1].id, assigned_team_id=teams[0].id, channel_id=channels[1].id),
            Ticket(id=_id(), tenant_id=TENANT, ticket_number="TCK-99013", customer_id="CST002", subject="Double charged for invoice INV-2026-04", description="My card statement shows two charges of $1200 on June 10th. Please refund one.", status=TicketStatus.OPEN, priority=TicketPriority.URGENT, assigned_agent_id=agents[0].id, assigned_team_id=teams[2].id, channel_id=channels[0].id),
            Ticket(id=_id(), tenant_id=TENANT, ticket_number="TCK-99014", customer_id="CST001", subject="How to export general ledger reports?", description="Need instructions to pull GL P&L statements in CSV format.", status=TicketStatus.RESOLVED, priority=TicketPriority.LOW, assigned_agent_id=agents[2].id, assigned_team_id=teams[1].id, channel_id=channels[1].id),
        ]
        for tk in tickets:
            db.add(tk)
        await db.flush()

        # Tags
        tags = [
            TicketTag(id=_id(), tenant_id=TENANT, ticket_id=tickets[0].id, tag="login_error"),
            TicketTag(id=_id(), tenant_id=TENANT, ticket_id=tickets[1].id, tag="billing_inquiry"),
            TicketTag(id=_id(), tenant_id=TENANT, ticket_id=tickets[2].id, tag="reporting_question"),
        ]
        for tg in tags:
            db.add(tg)

        # Comments
        comments = [
            TicketComment(id=_id(), tenant_id=TENANT, ticket_id=tickets[2].id, author_type="AGENT", author_id=agents[2].id, body="You can export files directly in the Reports tab by clicking the export button.", is_internal="No"),
            TicketComment(id=_id(), tenant_id=TENANT, ticket_id=tickets[2].id, author_type="CUSTOMER", author_id="CST001", body="Perfect, thank you! It resolved my question.", is_internal="No")
        ]
        for cm in comments:
            db.add(cm)

        # 5. SLA Policies
        policies = [
            SLAPolicy(id=_id(), tenant_id=TENANT, name="Tier 1 Response SLA", priority_level="HIGH", response_target_mins=60, resolution_target_hrs=8, is_active=True),
            SLAPolicy(id=_id(), tenant_id=TENANT, name="Urgent Escalation SLA", priority_level="URGENT", response_target_mins=15, resolution_target_hrs=2, is_active=True),
        ]
        for p in policies:
            db.add(p)
        await db.flush()

        # SLA Metrics
        metric = SLAMetric(
            id=_id(), tenant_id=TENANT, date_label=date.today().strftime("%Y-%m-%d"),
            total_tickets=14, breached_tickets=1, compliance_rate=92.80
        )
        db.add(metric)

        # 6. Knowledge Base
        category = KBCategory(id=_id(), tenant_id=TENANT, name="Account Access & Security", slug="account-security", description="FAQs on credentials and resets")
        db.add(category)
        await db.flush()

        article = KBArticle(
            id=_id(), tenant_id=TENANT, category_id=category.id,
            title="Resetting your KAEOS Password",
            content_md="To reset your password, visit the login screen, click 'Forgot Password', enter your work email, and click the confirmation link sent to you.",
            is_published=True, views=128, helpfulness_score=4.80
        )
        db.add(article)

        # 7. Customer Satisfaction & NPS
        csat = CustomerSatisfaction(
            id=_id(), tenant_id=TENANT, ticket_id=tickets[2].id,
            rating=5, comment="Pam was extremely helpful and resolved my question in 5 minutes.",
            sentiment="POSITIVE"
        )
        db.add(csat)

        nps = NPS_Survey(
            id=_id(), tenant_id=TENANT, customer_id="CST001",
            score=9, feedback_text="KAEOS saves our HR and Finance teams a lot of hours."
        )
        db.add(nps)

        theme = FeedbackTheme(
            id=_id(), tenant_id=TENANT, theme_name="Fast response on technical questions",
            volume_percentage=35.50, severity_rating="LOW"
        )
        db.add(theme)

        # 8. Escalation Rules
        rule = EscalationRule(
            id=_id(), tenant_id=TENANT, rule_name="VIP Ticket SLA Breach",
            trigger_condition="SLA_BREACH_RESPONSE", escalate_to_team_id=teams[1].id,
            time_threshold_mins=15, is_active=True
        )
        db.add(rule)

        await db.commit()
        print("[SUCCESS] Seeded Support database:")
        print(f"   - {len(teams)} support teams")
        print(f"   - {len(agents)} agents")
        print(f"   - {len(tickets)} tickets")
        print(f"   - {len(policies)} SLA policies")
        print(f"   - {len(tags)} tags")

if __name__ == "__main__":
    asyncio.run(seed())
