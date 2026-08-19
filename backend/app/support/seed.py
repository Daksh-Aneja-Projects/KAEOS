"""
KAEOS Support Domain — Database Seed Script
Seeds the Support tables with a realistic queue: tickets spanning every
status/priority/channel with real response/resolution timestamps (so
/support/sla/metrics has real data to compute against), multi-turn
conversation threads, CSAT/NPS/feedback rows, a real escalation event, and
both published and draft knowledge base articles.
"""
import asyncio
from datetime import datetime, timedelta, timezone


from app.core.database import async_engine, AsyncSessionLocal
from app.core.domain_seed import SEED_TENANT as TENANT, already_seeded, new_id, run_standalone

# Models imports
from app.support.models.core import SupportAgent, SupportTeam, SupportChannel, ChannelType
from app.support.models.tickets import Ticket, TicketComment, TicketTag, TicketPriority, TicketStatus
from app.support.models.sla import SLAPolicy, SLAMetric
from app.support.models.knowledge import ArticleFeedback, KBArticle, KBCategory
from app.support.models.feedback import CustomerSatisfaction, FeedbackTheme, NPS_Survey
from app.support.models.escalation import EscalationEvent, EscalationRule


# Real customers seeded by app.finance.seed (Customer.customer_code) - reused
# here so the support queue resolves to real names, not orphan codes.
CUSTOMERS = ["CST001", "CST002"]


def _ago(days=0, hours=0, minutes=0):
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)


async def seed_tenant(db, tenant: str) -> bool:
    # A second run must not duplicate rows or crash on the ticket_number
    # unique constraint.
    if await already_seeded(db, "Support", Ticket, tenant):
        return False

    # 1. Support Teams
    teams = [
        SupportTeam(id=new_id(), tenant_id=tenant, name="Tier 1 General Support", description="First level triage and password resets", tier=1),
        SupportTeam(id=new_id(), tenant_id=tenant, name="Tier 2 Technical Support", description="Database errors and API integrations", tier=2),
        SupportTeam(id=new_id(), tenant_id=tenant, name="Tier 3 Billing Support", description="Invoicing questions and refunds", tier=3),
    ]
    for t in teams:
        db.add(t)
    await db.flush()
    t1, t2, t3 = teams

    # 2. Support Agents
    agents = [
        SupportAgent(id=new_id(), tenant_id=tenant, name="Michael Scott", email="michael.scott@kaeos.io", team_id=t1.id, is_ai=False, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Triage Bot", email="triage.bot@kaeos.io", team_id=t1.id, is_ai=True, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Jim Halpert", email="jim.halpert@kaeos.io", team_id=t1.id, is_ai=False, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Pam Beesly", email="pam.beesly@kaeos.io", team_id=t2.id, is_ai=False, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Dwight Schrute", email="dwight.schrute@kaeos.io", team_id=t2.id, is_ai=False, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Holly Flax", email="holly.flax@kaeos.io", team_id=t3.id, is_ai=False, is_active=True),
        SupportAgent(id=new_id(), tenant_id=tenant, name="Toby Flenderson", email="toby.flenderson@kaeos.io", team_id=t3.id, is_ai=False, is_active=False),
    ]
    for a in agents:
        db.add(a)
    await db.flush()
    michael, triage_bot, jim, pam, dwight, holly, toby = agents

    # 3. Support Channels — one per ChannelType so routing config exercises all of them.
    channels = [
        SupportChannel(id=new_id(), tenant_id=tenant, channel_name="Email Ingress", channel_type=ChannelType.EMAIL, routing_team_id=t1.id, is_active=True),
        SupportChannel(id=new_id(), tenant_id=tenant, channel_name="Web Portal Widget", channel_type=ChannelType.PORTAL, routing_team_id=t1.id, is_active=True),
        SupportChannel(id=new_id(), tenant_id=tenant, channel_name="Live Chat Widget", channel_type=ChannelType.CHAT, routing_team_id=t2.id, is_active=True),
        SupportChannel(id=new_id(), tenant_id=tenant, channel_name="Billing Phone Line", channel_type=ChannelType.PHONE, routing_team_id=t3.id, is_active=True),
    ]
    for ch in channels:
        db.add(ch)
    await db.flush()
    email_ch, portal_ch, chat_ch, phone_ch = channels

    # 4. Tickets — every status × every priority, with real timestamps so
    # SLA compliance / MTTR / first-response are all computed from actual
    # data, never asserted. `response_min` / `resolution_hrs` are minutes
    # / hours AFTER created_at (resolution_hrs is measured from
    # created_at too, matching how the SLA endpoint measures it).
    specs = [
        # priority, status, customer, subject, description, agent, team, channel,
        # created_days_ago, response_min, resolution_hrs, tag
        (TicketPriority.URGENT, TicketStatus.RESOLVED, CUSTOMERS[0],
         "Production API returning 500s for all customers",
         "Every call to /v1/orders has returned HTTP 500 since 09:14 UTC. This is blocking checkout for our whole storefront.",
         triage_bot, t1, email_ch, 6, 10, 1.5, "api_outage"),
        (TicketPriority.URGENT, TicketStatus.RESOLVED, CUSTOMERS[1],
         "Data export job stuck at 0% for 3 hours",
         "Kicked off a full account export at 6am and it has not moved off 0% progress since. We need this for a board meeting today.",
         dwight, t2, chat_ch, 5, 40, 3.0, "export_stuck"),
        (TicketPriority.URGENT, TicketStatus.OPEN, CUSTOMERS[0],
         "SSO login broken for entire finance team",
         "Nobody on the finance team can log in via Okta SSO since this morning; they are locked out of the platform entirely.",
         pam, t2, portal_ch, 0, 5, None, "sso_outage"),
        (TicketPriority.URGENT, TicketStatus.NEW, CUSTOMERS[1],
         "Webhook signature verification suddenly failing",
         "Our integration started rejecting every inbound webhook about 20 minutes ago; the HMAC signature no longer matches.",
         None, None, email_ch, 0, None, None, "webhook_failure"),

        (TicketPriority.HIGH, TicketStatus.RESOLVED, CUSTOMERS[0],
         "Double charged for invoice INV-2026-04",
         "My card statement shows two charges of $1200 on June 10th. Please refund one.",
         michael, t3, phone_ch, 8, 45, 6.0, "billing_inquiry"),
        (TicketPriority.HIGH, TicketStatus.RESOLVED, CUSTOMERS[1],
         "Bulk import failing on rows with unicode characters",
         "Uploading our vendor CSV fails silently whenever a company name has an accented character. No error message, just a stalled job.",
         dwight, t2, portal_ch, 4, 90, 10.0, "import_bug"),
        (TicketPriority.HIGH, TicketStatus.PENDING_CUSTOMER, CUSTOMERS[0],
         "Report generation times out for our largest dataset",
         "The quarterly P&L report has timed out the last three times we generated it. Smaller reports work fine.",
         pam, t2, chat_ch, 1, 30, None, "performance"),
        (TicketPriority.HIGH, TicketStatus.ASSIGNED, CUSTOMERS[1],
         "Rate limiting kicked in during a legitimate bulk sync",
         "Our nightly sync job is being throttled at 429 even though we are well under the documented rate limit.",
         jim, t1, email_ch, 0, 15, None, "rate_limit"),

        (TicketPriority.MEDIUM, TicketStatus.CLOSED, CUSTOMERS[1],
         "How to export general ledger reports?",
         "Need instructions to pull GL P&L statements in CSV format.",
         pam, t2, portal_ch, 10, 100, 20.0, "reporting_question"),
        (TicketPriority.MEDIUM, TicketStatus.RESOLVED, CUSTOMERS[0],
         "Mobile app shows stale ticket counts",
         "The KAEOS mobile app dashboard has shown '3 open tickets' for two days even though we have closed most of them on desktop.",
         jim, t1, portal_ch, 6, 150, 30.0, "mobile_bug"),
        (TicketPriority.MEDIUM, TicketStatus.OPEN, CUSTOMERS[1],
         "Feature request: custom fields on tickets",
         "We would like to tag tickets with an internal project code. Is there a custom-fields option on the roadmap?",
         michael, t1, email_ch, 0, 60, None, "feature_request"),

        (TicketPriority.LOW, TicketStatus.CLOSED, CUSTOMERS[0],
         "Question about invoice PDF branding",
         "Can we add our own logo to the invoice PDFs KAEOS generates for our sub-tenants?",
         holly, t3, email_ch, 12, 200, 40.0, "billing_inquiry"),
        (TicketPriority.LOW, TicketStatus.RESOLVED, CUSTOMERS[1],
         "Typo in the onboarding checklist email",
         "Step 3 of the onboarding email says 'Invtie your team' instead of 'Invite your team'. Not urgent, just flagging it.",
         michael, t1, portal_ch, 9, 300, 60.0, "cosmetic"),
        (TicketPriority.LOW, TicketStatus.NEW, CUSTOMERS[0],
         "Where can I download my SOC 2 report?",
         "Looking for the latest SOC 2 Type II report for our vendor security review.",
         None, None, chat_ch, 0, None, None, "docs_request"),
    ]

    tickets = []
    tags = []
    for idx, (priority, status, cust, subject, desc, agent, team, channel,
              created_days_ago, response_min, resolution_hrs, tag) in enumerate(specs):
        created_at = _ago(days=created_days_ago, hours=idx % 5)  # spread within the day too
        first_response_at = created_at + timedelta(minutes=response_min) if response_min is not None else None
        resolved_at = created_at + timedelta(hours=resolution_hrs) if resolution_hrs is not None else None
        tk = Ticket(
            id=new_id(), tenant_id=tenant, ticket_number=f"TCK-{99020 + idx}",
            customer_id=cust, subject=subject, description=desc,
            status=status, priority=priority,
            assigned_agent_id=agent.id if agent else None,
            assigned_team_id=team.id if team else None,
            channel_id=channel.id,
            first_response_at=first_response_at, resolved_at=resolved_at,
            created_at=created_at, updated_at=resolved_at or first_response_at or created_at,
        )
        db.add(tk)
        tickets.append(tk)
        tags.append(TicketTag(id=new_id(), tenant_id=tenant, ticket_id=tk.id, tag=tag))
    await db.flush()
    for tg in tags:
        db.add(tg)

    # Multi-turn conversation threads on a handful of tickets - the
    # actual point of TicketComment, never shown anywhere before this.
    api_outage, export_stuck = tickets[0], tickets[1]
    billing_dup, gl_export = tickets[4], tickets[8]

    def _c(ticket, author_type, author_id, body, minutes_after, internal="No"):
        return TicketComment(
            id=new_id(), tenant_id=tenant, ticket_id=ticket.id,
            author_type=author_type, author_id=author_id, body=body,
            is_internal=internal, created_at=ticket.created_at + timedelta(minutes=minutes_after),
        )

    comments = [
        _c(api_outage, "CUSTOMER", CUSTOMERS[0],
           "Every call to /v1/orders is returning 500. This is blocking checkout right now.", 0),
        _c(api_outage, "AGENT", "resolution_agent",
           "Matched against KB article 'Diagnosing 5xx spikes on /v1/orders' - restarting the order-service pool clears a stuck connection leak.", 4, internal="Yes"),
        _c(api_outage, "AGENT", triage_bot.id,
           "We found a connection pool leak on the order service and restarted the affected pods. Please retry now.", 8),
        _c(api_outage, "CUSTOMER", CUSTOMERS[0],
           "Confirmed, checkout is working again. Thank you for the fast turnaround.", 85),

        _c(export_stuck, "CUSTOMER", CUSTOMERS[1],
           "The export job has been stuck at 0% for three hours now. We need this for a board meeting today.", 0),
        _c(export_stuck, "AGENT", dwight.id,
           "Apologies for the delay - I can see the job queued behind a larger tenant's backfill. Escalating it to the front of the queue now.", 30),
        _c(export_stuck, "AGENT", dwight.id,
           "The export completed and the download link has been emailed to you. We are also adding fair-queueing so this cannot happen again.", 175),

        _c(billing_dup, "CUSTOMER", CUSTOMERS[0],
           "My card statement shows two charges of $1200 on June 10th for the same invoice.", 0),
        _c(billing_dup, "AGENT", michael.id,
           "You are right, INV-2026-04 was submitted twice by our billing job. I have refunded the duplicate charge; it should post in 3-5 business days.", 40),

        _c(gl_export, "AGENT", pam.id,
           "You can export files directly in the Reports tab by clicking the export button.", 95),
        _c(gl_export, "CUSTOMER", CUSTOMERS[1],
           "Perfect, thank you! It resolved my question.", 400),
    ]
    for cm in comments:
        db.add(cm)

    # 5. SLA Policies — one per priority level, so every row the SLA
    # endpoint returns has matching ticket data to compute against.
    policies = [
        SLAPolicy(id=new_id(), tenant_id=tenant, name="Standard Response SLA", priority_level="LOW", response_target_mins=240, resolution_target_hrs=48, is_active=True),
        SLAPolicy(id=new_id(), tenant_id=tenant, name="Priority Response SLA", priority_level="MEDIUM", response_target_mins=120, resolution_target_hrs=24, is_active=True),
        SLAPolicy(id=new_id(), tenant_id=tenant, name="Tier 1 Response SLA", priority_level="HIGH", response_target_mins=60, resolution_target_hrs=8, is_active=True),
        SLAPolicy(id=new_id(), tenant_id=tenant, name="Urgent Escalation SLA", priority_level="URGENT", response_target_mins=15, resolution_target_hrs=2, is_active=True),
    ]
    for p in policies:
        db.add(p)
    await db.flush()

    # Daily aggregate snapshot (historical trend row - not read by the
    # per-policy /sla/metrics endpoint, which computes live from tickets).
    breached_count = 4  # matches the deliberately-late tickets among the specs above
    metric = SLAMetric(
        id=new_id(), tenant_id=tenant, date_label=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        total_tickets=len(tickets), breached_tickets=breached_count,
        compliance_rate=round((len(tickets) - breached_count) / len(tickets) * 100, 2),
    )
    db.add(metric)

    # 6. Knowledge Base — categories, and a mix of published + AI-drafted
    # (unpublished) articles so the new publish action has something to do.
    cat_security = KBCategory(id=new_id(), tenant_id=tenant, name="Account Access & Security", slug="account-security", description="FAQs on credentials and resets")
    cat_billing = KBCategory(id=new_id(), tenant_id=tenant, name="Billing & Invoicing", slug="billing-invoicing", description="FAQs on invoices, refunds, and payment methods")
    db.add(cat_security)
    db.add(cat_billing)
    await db.flush()

    articles = [
        KBArticle(id=new_id(), tenant_id=tenant, category_id=cat_security.id,
                  title="Resetting your KAEOS Password",
                  content_md="To reset your password, visit the login screen, click 'Forgot Password', enter your work email, and click the confirmation link sent to you.",
                  is_published=True, views=128, helpfulness_score=4.80),
        KBArticle(id=new_id(), tenant_id=tenant, category_id=cat_security.id,
                  title="Setting up SSO with your identity provider",
                  content_md="KAEOS supports SAML 2.0 SSO with Okta, Azure AD, and Google Workspace. Ask your KAEOS admin for the SP metadata URL and configure it as a new app in your IdP.",
                  is_published=True, views=76, helpfulness_score=4.50),
        KBArticle(id=new_id(), tenant_id=tenant, category_id=cat_billing.id,
                  title="Understanding your monthly invoice",
                  content_md="Your invoice breaks down usage by department: seats, agent executions, and storage. Line items map 1:1 to the Billing tab in your admin console.",
                  is_published=True, views=210, helpfulness_score=4.20),
        # AI-authored drafts (KBAgent.document_resolution always writes
        # is_published=False) — realistic stand-ins until someone clicks Publish.
        KBArticle(id=new_id(), tenant_id=tenant, category_id=cat_security.id,
                  title="Troubleshooting webhook signature verification failures",
                  content_md="# Troubleshooting webhook signatures\n\n## Issue\nInbound webhooks are rejected because the HMAC signature no longer matches.\n\n## Resolution\nRegenerate the webhook signing secret from Settings > Webhooks and update it in your integration; secrets rotate automatically every 90 days.",
                  is_published=False, views=0, helpfulness_score=0.00, author_id="kb_agent"),
        KBArticle(id=new_id(), tenant_id=tenant, category_id=cat_billing.id,
                  title="How to export general ledger reports as CSV",
                  content_md="# Exporting GL reports\n\n## Issue\nCustomers ask how to pull GL P&L statements in CSV format.\n\n## Resolution\nOpen the Reports tab, select General Ledger, choose a date range, and click Export - the CSV downloads immediately.",
                  is_published=False, views=0, helpfulness_score=0.00, author_id="kb_agent"),
    ]
    for art in articles:
        db.add(art)
    await db.flush()
    pw_article, sso_article, invoice_article = articles[0], articles[1], articles[2]

    feedback_rows = [
        ArticleFeedback(id=new_id(), tenant_id=tenant, article_id=pw_article.id, is_helpful=True, comment="Fixed it in two minutes, thanks."),
        ArticleFeedback(id=new_id(), tenant_id=tenant, article_id=pw_article.id, is_helpful=True, comment=None),
        ArticleFeedback(id=new_id(), tenant_id=tenant, article_id=sso_article.id, is_helpful=True, comment="Would help to link the exact Okta app template."),
        ArticleFeedback(id=new_id(), tenant_id=tenant, article_id=sso_article.id, is_helpful=False, comment="Our IdP is Azure AD and the steps did not quite match."),
        ArticleFeedback(id=new_id(), tenant_id=tenant, article_id=invoice_article.id, is_helpful=True, comment="Clear breakdown, exactly what I needed."),
    ]
    for f in feedback_rows:
        db.add(f)

    # 7. Customer Satisfaction — tied to resolved/closed tickets so the
    # per-agent leaderboard has real ratings to average.
    resolved_like = [t for t in tickets if t.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)]
    csat_specs = [
        (resolved_like[0], 5, "Incredibly fast turnaround on a production outage. Impressed.", "POSITIVE"),
        (resolved_like[1], 4, "Took a while to get escalated but the fix worked.", "POSITIVE"),
        (resolved_like[2], 5, "Refund processed exactly as promised.", "POSITIVE"),
        (resolved_like[3], 3, "Got there in the end but the import bug took two tries to fix.", "NEUTRAL"),
        (resolved_like[4], 2, "Report timeout is still slow even after the fix.", "NEGATIVE"),
        (resolved_like[5], 5, "Pam was extremely helpful and resolved my question in 5 minutes.", "POSITIVE"),
        (resolved_like[6], 4, "Good response, minor delay before the stale-count bug was found.", "POSITIVE"),
    ]
    csats = [
        CustomerSatisfaction(id=new_id(), tenant_id=tenant, ticket_id=t.id, rating=r, comment=c, sentiment=s,
                             completed_at=t.resolved_at + timedelta(hours=2) if t.resolved_at else t.created_at)
        for t, r, c, s in csat_specs
    ]
    for c in csats:
        db.add(c)

    nps_rows = [
        NPS_Survey(id=new_id(), tenant_id=tenant, customer_id=CUSTOMERS[0], score=9,
                   feedback_text="KAEOS saves our HR and Finance teams a lot of hours.", created_at=_ago(days=3)),
        NPS_Survey(id=new_id(), tenant_id=tenant, customer_id=CUSTOMERS[1], score=8,
                   feedback_text="Support is responsive but the export tooling needs polish.", created_at=_ago(days=7)),
        NPS_Survey(id=new_id(), tenant_id=tenant, customer_id=CUSTOMERS[0], score=6,
                   feedback_text="Good product, occasional slowness on large reports.", created_at=_ago(days=14)),
        NPS_Survey(id=new_id(), tenant_id=tenant, customer_id=CUSTOMERS[1], score=10,
                   feedback_text="Best support team we have worked with.", created_at=_ago(days=20)),
        NPS_Survey(id=new_id(), tenant_id=tenant, customer_id=CUSTOMERS[0], score=4,
                   feedback_text="The production outage last month was concerning even though it was resolved quickly.", created_at=_ago(days=25)),
    ]
    for n in nps_rows:
        db.add(n)

    themes = [
        FeedbackTheme(id=new_id(), tenant_id=tenant, theme_name="Fast response on technical questions", volume_percentage=35.50, severity_rating="LOW"),
        FeedbackTheme(id=new_id(), tenant_id=tenant, theme_name="Confusing billing cycle explanations", volume_percentage=22.00, severity_rating="MEDIUM"),
        FeedbackTheme(id=new_id(), tenant_id=tenant, theme_name="Slow report generation on large datasets", volume_percentage=18.30, severity_rating="HIGH"),
        FeedbackTheme(id=new_id(), tenant_id=tenant, theme_name="Positive onboarding experience", volume_percentage=24.20, severity_rating="LOW"),
    ]
    for th in themes:
        db.add(th)

    # 8. Escalation Rules + a real Escalation Event
    rules = [
        EscalationRule(id=new_id(), tenant_id=tenant, rule_name="VIP Ticket SLA Breach",
                       trigger_condition="SLA_BREACH_RESPONSE", escalate_to_team_id=t2.id,
                       time_threshold_mins=15, is_active=True),
        EscalationRule(id=new_id(), tenant_id=tenant, rule_name="Repeated Urgent Contact",
                       trigger_condition="REPEAT_URGENT_CONTACT", escalate_to_agent_id=holly.id,
                       time_threshold_mins=30, is_active=True),
    ]
    for r in rules:
        db.add(r)
    await db.flush()

    # export_stuck (ticket[1]) missed its 15-minute URGENT response target
    # by 25 minutes — a real breach that the VIP rule above would fire on.
    escalation = EscalationEvent(
        id=new_id(), tenant_id=tenant, ticket_id=export_stuck.id, rule_id=rules[0].id,
        escalated_from_agent_id=triage_bot.id, escalated_to_agent_id=dwight.id,
        reason="First response missed the 15-minute URGENT SLA target by 25 minutes; escalated to Tier 2 for senior review.",
        created_at=export_stuck.created_at + timedelta(minutes=45),
    )
    db.add(escalation)

    await db.commit()
    print("[SUCCESS] Seeded Support database:")
    print(f"   - {len(teams)} support teams, {len(agents)} agents, {len(channels)} channels")
    print(f"   - {len(tickets)} tickets, {len(tags)} tags, {len(comments)} comments")
    print(f"   - {len(policies)} SLA policies")
    print(f"   - {len(articles)} KB articles ({sum(1 for a in articles if a.is_published)} published), {len(feedback_rows)} article feedback rows")
    print(f"   - {len(csats)} CSAT surveys, {len(nps_rows)} NPS surveys, {len(themes)} feedback themes")
    print(f"   - {len(rules)} escalation rules, 1 escalation event")
    return True


async def seed(tenant: str | None = None) -> bool:
    return await run_standalone(async_engine, AsyncSessionLocal, seed_tenant, tenant or TENANT)


if __name__ == "__main__":
    asyncio.run(seed())
