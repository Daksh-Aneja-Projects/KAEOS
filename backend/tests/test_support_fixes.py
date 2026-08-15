"""
Support department fixes: real per-policy SLA compliance (no fabrication),
customer-name resolution on CSAT/NPS, KB publish/unpublish, the newly exposed
read endpoints (teams/channels/comments/tags/escalation/leaderboard), and
EscalationAgent grounding in real EscalationRule rows.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


async def _customer(db, code="CST900", name="Acme Test Co", tenant=TENANT):
    from app.finance.models.accounts_receivable import Customer
    c = Customer(tenant_id=tenant, customer_code=code, name=name)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _ticket(db, priority, created_at, first_response_at=None, resolved_at=None,
                   customer_id=None, assigned_agent_id=None, tenant=TENANT, number=None):
    import uuid
    from app.support.models.tickets import Ticket, TicketStatus
    t = Ticket(
        tenant_id=tenant, ticket_number=number or f"T-{uuid.uuid4().hex[:10]}",
        subject="s", description="d", priority=priority,
        status=TicketStatus.RESOLVED if resolved_at else TicketStatus.OPEN,
        customer_id=customer_id, assigned_agent_id=assigned_agent_id,
        created_at=created_at, first_response_at=first_response_at, resolved_at=resolved_at,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


# --- SLA metrics: real computation, honest nulls -----------------------------

@pytest.mark.asyncio
async def test_sla_metrics_computed_from_real_ticket_timestamps(async_client: AsyncClient, db):
    from app.support.models.sla import SLAPolicy
    from app.support.models.tickets import TicketPriority

    db.add(SLAPolicy(tenant_id=TENANT, name="High SLA", priority_level="HIGH",
                      response_target_mins=60, resolution_target_hrs=8, is_active=True))
    await db.commit()

    created = _ago(days=2)
    # Within target on both response and resolution.
    await _ticket(db, TicketPriority.HIGH, created,
                  first_response_at=created + timedelta(minutes=30),
                  resolved_at=created + timedelta(hours=5))
    # Breaches both response and resolution targets.
    await _ticket(db, TicketPriority.HIGH, created,
                  first_response_at=created + timedelta(minutes=90),
                  resolved_at=created + timedelta(hours=10))

    r = await async_client.get("/api/v1/support/sla/metrics")
    assert r.status_code == 200, r.text
    row = next(m for m in r.json() if m["priority"] == "HIGH")

    assert row["target_hours"] == 1.0
    assert row["actual_hours"] == pytest.approx(1.0, abs=0.01)  # avg(0.5h, 1.5h)
    assert row["breached_count"] == 1
    assert row["compliance_pct"] == 50.0
    assert row["status"] == "BREACHED"


@pytest.mark.asyncio
async def test_sla_metrics_honest_null_when_no_matching_tickets(async_client: AsyncClient, db):
    from app.support.models.sla import SLAPolicy

    db.add(SLAPolicy(tenant_id=TENANT, name="Low SLA", priority_level="LOW",
                      response_target_mins=240, resolution_target_hrs=48, is_active=True))
    await db.commit()

    r = await async_client.get("/api/v1/support/sla/metrics")
    assert r.status_code == 200, r.text
    row = next(m for m in r.json() if m["priority"] == "LOW")

    assert row["status"] == "NO_DATA"
    assert row["actual_hours"] is None
    assert row["compliance_pct"] is None
    assert row["breached_count"] is None
    assert "note" in row and row["note"]


@pytest.mark.asyncio
async def test_sla_metrics_no_policies_returns_empty_list(async_client: AsyncClient, db):
    r = await async_client.get("/api/v1/support/sla/metrics")
    assert r.status_code == 200
    assert r.json() == []


# --- CSAT / NPS: resolve customer codes to names -----------------------------

@pytest.mark.asyncio
async def test_csat_surveys_resolve_customer_name(async_client: AsyncClient, db):
    from app.support.models.feedback import CustomerSatisfaction
    from app.support.models.tickets import TicketPriority

    cust = await _customer(db, code="CST901", name="Globex Corporation")
    t = await _ticket(db, TicketPriority.LOW, _ago(days=1), customer_id=cust.customer_code)
    db.add(CustomerSatisfaction(tenant_id=TENANT, ticket_id=t.id, rating=5, sentiment="POSITIVE"))
    # Anonymous: no ticket_id.
    await db.commit()

    r = await async_client.get("/api/v1/support/csat/surveys")
    assert r.status_code == 200, r.text
    row = next(s for s in r.json() if s["ticket_id"] == t.id)
    assert row["customer"] == "Globex Corporation"
    assert "CST901" not in row["customer"]


@pytest.mark.asyncio
async def test_nps_surveys_resolve_customer_name_and_anonymous_fallback(async_client: AsyncClient, db):
    from app.support.models.feedback import NPS_Survey

    cust = await _customer(db, code="CST902", name="Initech LLC")
    db.add(NPS_Survey(tenant_id=TENANT, customer_id=cust.customer_code, score=9, feedback_text="great"))
    db.add(NPS_Survey(tenant_id=TENANT, customer_id="", score=3, feedback_text="unhappy"))
    await db.commit()

    r = await async_client.get("/api/v1/support/nps/surveys")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["customer"] == "Initech LLC" and s["score"] == 9 for s in body)
    assert any(s["customer"] == "Anonymous" for s in body)


# --- KB publish / unpublish ---------------------------------------------------

@pytest.mark.asyncio
async def test_kb_article_publish_and_unpublish(async_client: AsyncClient, db):
    from app.support.models.knowledge import KBArticle

    art = KBArticle(tenant_id=TENANT, title="Draft article", content_md="body", is_published=False)
    db.add(art)
    await db.commit()
    await db.refresh(art)

    r = await async_client.patch(f"/api/v1/support/kb/articles/{art.id}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PUBLISHED"

    listed = await async_client.get("/api/v1/support/kb/articles")
    assert next(a for a in listed.json() if a["id"] == art.id)["status"] == "PUBLISHED"

    r2 = await async_client.patch(f"/api/v1/support/kb/articles/{art.id}/unpublish")
    assert r2.status_code == 200
    assert r2.json()["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_kb_article_publish_unknown_id_404(async_client: AsyncClient):
    r = await async_client.patch("/api/v1/support/kb/articles/does-not-exist/publish")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_kb_article_feedback_endpoint(async_client: AsyncClient, db):
    from app.support.models.knowledge import ArticleFeedback, KBArticle

    art = KBArticle(tenant_id=TENANT, title="Helpful?", content_md="body", is_published=True)
    db.add(art)
    await db.commit()
    await db.refresh(art)
    db.add(ArticleFeedback(tenant_id=TENANT, article_id=art.id, is_helpful=True, comment="thanks"))
    db.add(ArticleFeedback(tenant_id=TENANT, article_id=art.id, is_helpful=False, comment=None))
    await db.commit()

    r = await async_client.get(f"/api/v1/support/kb/articles/{art.id}/feedback")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    assert {row["is_helpful"] for row in rows} == {True, False}

    r404 = await async_client.get("/api/v1/support/kb/articles/nope/feedback")
    assert r404.status_code == 404


# --- Ticket conversation thread (TicketComment / TicketTag) -----------------

@pytest.mark.asyncio
async def test_ticket_comments_resolve_author_names(async_client: AsyncClient, db):
    from app.support.models.core import SupportAgent
    from app.support.models.tickets import TicketComment, TicketPriority, TicketTag

    cust = await _customer(db, code="CST903", name="Umbrella Corp")
    agent = SupportAgent(tenant_id=TENANT, name="Real Agent", email="real.agent@kaeos.io")
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    t = await _ticket(db, TicketPriority.MEDIUM, _ago(days=1), customer_id=cust.customer_code)
    db.add(TicketComment(tenant_id=TENANT, ticket_id=t.id, author_type="CUSTOMER",
                         author_id=cust.customer_code, body="Help please", is_internal="No"))
    db.add(TicketComment(tenant_id=TENANT, ticket_id=t.id, author_type="AGENT",
                         author_id=agent.id, body="On it", is_internal="No"))
    db.add(TicketComment(tenant_id=TENANT, ticket_id=t.id, author_type="AGENT",
                         author_id="resolution_agent", body="Matched KB article X", is_internal="Yes"))
    db.add(TicketComment(tenant_id=TENANT, ticket_id=t.id, author_type="SYSTEM",
                         author_id=None, body="Ticket auto-assigned", is_internal="No"))
    db.add(TicketTag(tenant_id=TENANT, ticket_id=t.id, tag="billing_inquiry"))
    await db.commit()

    r = await async_client.get(f"/api/v1/support/tickets/{t.id}/comments")
    assert r.status_code == 200, r.text
    comments = r.json()
    assert len(comments) == 4
    by_body = {c["body"]: c for c in comments}
    assert by_body["Help please"]["author"] == "Umbrella Corp"
    assert by_body["On it"]["author"] == "Real Agent"
    assert by_body["Matched KB article X"]["author"] == "KAEOS Resolution Agent"
    assert by_body["Matched KB article X"]["is_internal"] is True
    assert by_body["Ticket auto-assigned"]["author"] == "System"
    # No raw ids/codes leaked into the human-facing "author" field.
    assert all("CST903" not in c["author"] and agent.id not in c["author"] for c in comments)

    r2 = await async_client.get(f"/api/v1/support/tickets/{t.id}/tags")
    assert r2.status_code == 200
    assert [tg["tag"] for tg in r2.json()] == ["billing_inquiry"]

    r404 = await async_client.get("/api/v1/support/tickets/does-not-exist/comments")
    assert r404.status_code == 404


# --- Teams / channels / leaderboard ------------------------------------------

@pytest.mark.asyncio
async def test_teams_and_channels_endpoints(async_client: AsyncClient, db):
    from app.support.models.core import ChannelType, SupportAgent, SupportChannel, SupportTeam

    team = SupportTeam(tenant_id=TENANT, name="Tier 9 Ninjas", tier=9)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    db.add(SupportAgent(tenant_id=TENANT, name="Ninja One", email="ninja1@kaeos.io", team_id=team.id))
    db.add(SupportAgent(tenant_id=TENANT, name="Ninja Two", email="ninja2@kaeos.io", team_id=team.id))
    db.add(SupportChannel(tenant_id=TENANT, channel_name="Carrier Pigeon", channel_type=ChannelType.EMAIL,
                          routing_team_id=team.id, is_active=True))
    await db.commit()

    r = await async_client.get("/api/v1/support/teams")
    assert r.status_code == 200, r.text
    row = next(t for t in r.json() if t["name"] == "Tier 9 Ninjas")
    assert row["agent_count"] == 2

    r2 = await async_client.get("/api/v1/support/channels")
    assert r2.status_code == 200
    ch = next(c for c in r2.json() if c["name"] == "Carrier Pigeon")
    assert ch["routing_team"] == "Tier 9 Ninjas"
    assert ch["type"] == "EMAIL"


@pytest.mark.asyncio
async def test_agent_leaderboard_computes_and_persists_avg_csat(async_client: AsyncClient, db):
    from app.support.models.core import SupportAgent
    from app.support.models.feedback import CustomerSatisfaction
    from app.support.models.tickets import TicketPriority

    agent = SupportAgent(tenant_id=TENANT, name="Leaderboard Agent", email="leader@kaeos.io")
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    assert agent.avg_csat is None  # column is Numeric now, not the ChannelType enum

    t1 = await _ticket(db, TicketPriority.LOW, _ago(days=3), assigned_agent_id=agent.id,
                       resolved_at=_ago(days=2))
    t2 = await _ticket(db, TicketPriority.LOW, _ago(days=3), assigned_agent_id=agent.id,
                       resolved_at=_ago(days=2))
    db.add(CustomerSatisfaction(tenant_id=TENANT, ticket_id=t1.id, rating=5, sentiment="POSITIVE"))
    db.add(CustomerSatisfaction(tenant_id=TENANT, ticket_id=t2.id, rating=3, sentiment="NEUTRAL"))
    await db.commit()

    r = await async_client.get("/api/v1/support/agents/leaderboard")
    assert r.status_code == 200, r.text
    row = next(a for a in r.json() if a["id"] == agent.id)
    assert row["avg_csat"] == 4.0
    assert row["survey_count"] == 2
    assert row["ticket_count"] == 2

    # Persisted onto the agent row, not just returned in the response.
    await db.refresh(agent)
    assert float(agent.avg_csat) == 4.0


@pytest.mark.asyncio
async def test_agent_leaderboard_null_when_no_surveys(async_client: AsyncClient, db):
    from app.support.models.core import SupportAgent

    agent = SupportAgent(tenant_id=TENANT, name="No Surveys Agent", email="nosurveys@kaeos.io")
    db.add(agent)
    await db.commit()

    r = await async_client.get("/api/v1/support/agents/leaderboard")
    assert r.status_code == 200
    row = next(a for a in r.json() if a["name"] == "No Surveys Agent")
    assert row["avg_csat"] is None
    assert row["survey_count"] == 0


# --- Escalation rules / events ------------------------------------------------

@pytest.mark.asyncio
async def test_escalation_rules_and_events_endpoints(async_client: AsyncClient, db):
    from app.support.models.core import SupportAgent, SupportTeam
    from app.support.models.escalation import EscalationEvent, EscalationRule
    from app.support.models.tickets import TicketPriority

    team = SupportTeam(tenant_id=TENANT, name="Escalation Team", tier=2)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    a1 = SupportAgent(tenant_id=TENANT, name="From Agent", email="from@kaeos.io")
    a2 = SupportAgent(tenant_id=TENANT, name="To Agent", email="to@kaeos.io")
    db.add(a1); db.add(a2)
    await db.commit()
    await db.refresh(a1); await db.refresh(a2)

    rule = EscalationRule(tenant_id=TENANT, rule_name="Test Rule", trigger_condition="SLA_BREACH_RESPONSE",
                          escalate_to_team_id=team.id, time_threshold_mins=15, is_active=True)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    t = await _ticket(db, TicketPriority.URGENT, _ago(days=1), number="TCK-ESC-1")
    db.add(EscalationEvent(tenant_id=TENANT, ticket_id=t.id, rule_id=rule.id,
                           escalated_from_agent_id=a1.id, escalated_to_agent_id=a2.id,
                           reason="Missed SLA"))
    await db.commit()

    r = await async_client.get("/api/v1/support/escalation-rules")
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["name"] == "Test Rule")
    assert row["escalate_to_team"] == "Escalation Team"

    r2 = await async_client.get("/api/v1/support/escalation-events")
    assert r2.status_code == 200, r2.text
    ev = next(x for x in r2.json() if x["ticket_id"] == t.id)
    assert ev["ticket_number"] == "TCK-ESC-1"
    assert ev["from_agent"] == "From Agent"
    assert ev["to_agent"] == "To Agent"
    assert ev["rule"] == "Test Rule"


@pytest.mark.asyncio
async def test_feedback_themes_endpoint(async_client: AsyncClient, db):
    from app.support.models.feedback import FeedbackTheme

    db.add(FeedbackTheme(tenant_id=TENANT, theme_name="Slow exports", volume_percentage=42.5, severity_rating="HIGH"))
    await db.commit()

    r = await async_client.get("/api/v1/support/feedback/themes")
    assert r.status_code == 200, r.text
    row = next(t for t in r.json() if t["theme"] == "Slow exports")
    assert row["volume_pct"] == 42.5
    assert row["severity"] == "HIGH"


# --- EscalationAgent grounds in real EscalationRule rows ---------------------

@pytest.mark.asyncio
async def test_escalation_agent_grounds_in_active_tenant_rules(db, monkeypatch):
    from app.support.agents.escalation_agent import EscalationAgent
    from app.support.models.escalation import EscalationRule
    from app.support.models.tickets import TicketPriority

    t = await _ticket(db, TicketPriority.URGENT, _ago(hours=1))
    db.add(EscalationRule(tenant_id=TENANT, rule_name="Active VIP Rule",
                          trigger_condition="SLA_BREACH_RESPONSE", time_threshold_mins=15, is_active=True))
    db.add(EscalationRule(tenant_id=TENANT, rule_name="Inactive Rule",
                          trigger_condition="OTHER", time_threshold_mins=30, is_active=False))
    db.add(EscalationRule(tenant_id="tenant_other", rule_name="Foreign Rule",
                          trigger_condition="SLA_BREACH_RESPONSE", time_threshold_mins=15, is_active=True))
    await db.commit()

    captured = {}

    async def _fake_run_gated_support_skill(**kwargs):
        captured.update(kwargs)
        return {"status": "PENDING_HITL"}

    import app.support.agents.escalation_agent as escalation_agent_module
    monkeypatch.setattr(escalation_agent_module, "run_gated_support_skill", _fake_run_gated_support_skill)

    result = await EscalationAgent().escalate_ticket(db, t.id, TENANT)
    assert result == {"status": "PENDING_HITL"}

    policy = captured["context"]["escalation_policy"]
    assert len(policy) == 1
    assert policy[0]["rule"] == "Active VIP Rule"
    assert policy[0]["trigger_condition"] == "SLA_BREACH_RESPONSE"
    assert policy[0]["time_threshold_mins"] == 15


@pytest.mark.asyncio
async def test_escalation_agent_unknown_ticket_raises(db):
    from app.support.agents.escalation_agent import EscalationAgent
    with pytest.raises(ValueError):
        await EscalationAgent().escalate_ticket(db, "does-not-exist", TENANT)
