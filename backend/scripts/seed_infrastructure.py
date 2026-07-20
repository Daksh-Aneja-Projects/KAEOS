"""
KAEOS — Infrastructure Layer Seeder (N1-N4)
Seeds model registry, cost events, token budgets, agent registry,
agent messages, and tenant onboarding for the Infrastructure Dashboard.
"""
import asyncio
import uuid
import random
from datetime import datetime, timezone, timedelta

# Seeding is maintenance: run as the table OWNER. The app role is subject to RLS
# and a script has no request tenant context, so its writes fail closed.
from app.core.database import (
    maintenance_engine as async_engine,
    MaintenanceSessionLocal as AsyncSessionLocal,
)
from app.models.domain import Base
from app.models.infrastructure import (
    ModelRegistryEntry, ModelTier,
    PromptTemplate,
    TokenBudget, AgentMessage, AgentMessageStatus, AgentRegistryEntry,
    TenantOnboarding, OnboardingStage,
)

TENANT = "tenant_acme"
NOW = datetime.now(timezone.utc)


def _id():
    return str(uuid.uuid4())


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, func as sqlfunc
        # Idempotency: skip if already seeded
        existing = (await db.execute(select(sqlfunc.count()).select_from(ModelRegistryEntry))).scalar() or 0
        if existing > 0:
            print(f"[Infrastructure Seed] Already seeded ({existing} models) — skipping")
            return


        # ── N1: Model Registry ──
        models = [
            ModelRegistryEntry(
                id=_id(), tenant_id=TENANT,
                model_name="phi4-mini:latest", provider="ollama",
                tier=ModelTier.FAST, is_active=True,
                avg_latency_ms=120, success_rate=0.97,
                cost_per_1k_input=0.0, cost_per_1k_output=0.0,
                avg_tokens_per_task=300,
                use_cases=["classification", "extraction", "fast"],
            ),
            ModelRegistryEntry(
                id=_id(), tenant_id=TENANT,
                model_name="qwen2.5-coder:7b", provider="ollama",
                tier=ModelTier.STANDARD, is_active=True,
                avg_latency_ms=800, success_rate=0.94,
                cost_per_1k_input=0.0, cost_per_1k_output=0.0,
                avg_tokens_per_task=600,
                use_cases=["reasoning", "debate", "blueprints"],
            ),
            ModelRegistryEntry(
                id=_id(), tenant_id=TENANT,
                model_name="nomic-embed-text:latest", provider="ollama",
                tier=ModelTier.FAST, is_active=True,
                avg_latency_ms=50, success_rate=0.99,
                cost_per_1k_input=0.0, cost_per_1k_output=0.0,
                avg_tokens_per_task=100,
                use_cases=["embedding", "rag", "search"],
            ),
        ]

        # ── N1: Prompt Templates ──
        prompts = [
            PromptTemplate(
                id=_id(), tenant_id=TENANT,
                template_key="compliance.violation_scan",
                version=2, is_active=True,
                system_prompt=(
                    "You are a compliance engine. Analyze the action for regulatory violations. "
                    "Return a JSON list of violation objects with: rule_id, severity, explanation."
                ),
                user_template="Action: {{action}}\nDomain: {{domain}}\nActive rules: {{rules}}",
                model_tier=ModelTier.FAST,
                max_tokens=1024, temperature=0.0,
                usage_count=1240, avg_quality_score=0.92,
            ),
            PromptTemplate(
                id=_id(), tenant_id=TENANT,
                template_key="fairness.assessment",
                version=1, is_active=True,
                system_prompt=(
                    "You are a fairness assessor. Evaluate this decision for bias across protected attributes. "
                    "Return JSON with: overall_score (0-1), attribute_scores, flagged_attributes, rationale."
                ),
                user_template="Decision: {{decision}}\nContext: {{context}}\nProtected attributes: {{attributes}}",
                model_tier=ModelTier.STANDARD,
                max_tokens=2048, temperature=0.1,
                usage_count=890, avg_quality_score=0.88,
            ),
            PromptTemplate(
                id=_id(), tenant_id=TENANT,
                template_key="routing.intent_classify",
                version=3, is_active=True,
                system_prompt=(
                    "You are a skill router. Classify the request to the most appropriate skill. "
                    "Return JSON: {selected_skill_id, confidence}."
                ),
                user_template="Request: {{request}}\nAvailable skills: {{skills}}",
                model_tier=ModelTier.FAST,
                max_tokens=256, temperature=0.0,
                usage_count=5670, avg_quality_score=0.95,
            ),
            PromptTemplate(
                id=_id(), tenant_id=TENANT,
                template_key="debate.proposer",
                version=1, is_active=True,
                system_prompt=(
                    "You are the Proposer Agent in a structured debate. "
                    "Build evidence-backed arguments to support proceeding with the action. "
                    "Return JSON: {evidence, conclusion, confidence, grounded_in}."
                ),
                user_template="Action: {{action}}\nContext: {{context}}\nKnowledge base: {{kb_rules}}",
                model_tier=ModelTier.STANDARD,
                max_tokens=2048, temperature=0.3,
                usage_count=312, avg_quality_score=0.87,
            ),
        ]

        # ── N2: Token Budget ──
        budgets = [
            TokenBudget(
                id=_id(), tenant_id=TENANT,
                scope="tenant", scope_id=TENANT,
                period="monthly",
                token_limit=5_000_000, token_used=1_850_000,
                cost_limit_usd=500.0, cost_used_usd=0.0,
                soft_limit_pct=0.80, hard_limit_pct=0.95,
                enforcement_action="DEGRADE",
                period_start=NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            ),
        ]

        # ── N2: Cost Events ──
        # Deliberately NOT seeded.
        #
        # This used to invent 24h of telemetry with random.randint - and
        # /billing described its output as "derived from CostEvent rows written
        # by the LLM router". The router had no cost code at all, so every cost
        # figure the product reported was fiction dressed as measurement.
        #
        # The router now meters real calls (see LLMRouter._record_cost), so
        # these rows accumulate from actual work. An empty cost history on a
        # fresh install is the truth: nothing has run yet.
        cost_events = []

        # ── N3: Agent Registry ──
        agent_entries = [
            AgentRegistryEntry(
                id=_id(), tenant_id=TENANT,
                agent_name="Compliance Review Agent",
                agent_type="specialized",
                capabilities=["contract_review", "gdpr_check", "policy_validation"],
                model_tier_preference=ModelTier.STANDARD,
                health_status="HEALTHY", current_load=3, max_concurrent=10,
                circuit_state="CLOSED", failure_count=0,
                last_heartbeat=NOW - timedelta(seconds=30),
            ),
            AgentRegistryEntry(
                id=_id(), tenant_id=TENANT,
                agent_name="Invoice Matcher Agent",
                agent_type="specialized",
                capabilities=["invoice_matching", "three_way_match", "payment_approval"],
                model_tier_preference=ModelTier.FAST,
                health_status="HEALTHY", current_load=1, max_concurrent=15,
                circuit_state="CLOSED", failure_count=0,
                last_heartbeat=NOW - timedelta(seconds=45),
            ),
            AgentRegistryEntry(
                id=_id(), tenant_id=TENANT,
                agent_name="Ticket Triage Agent",
                agent_type="specialized",
                capabilities=["ticket_classification", "severity_assessment", "team_assignment"],
                model_tier_preference=ModelTier.FAST,
                health_status="HEALTHY", current_load=7, max_concurrent=20,
                circuit_state="CLOSED", failure_count=2,
                last_heartbeat=NOW - timedelta(seconds=60),
            ),
            AgentRegistryEntry(
                id=_id(), tenant_id=TENANT,
                agent_name="Debate Arbitrator",
                agent_type="debate",
                capabilities=["arbitration", "fairness_check", "decision_synthesis"],
                model_tier_preference=ModelTier.STANDARD,
                health_status="HEALTHY", current_load=0, max_concurrent=5,
                circuit_state="CLOSED", failure_count=0,
                last_heartbeat=NOW - timedelta(seconds=15),
            ),
            AgentRegistryEntry(
                id=_id(), tenant_id=TENANT,
                agent_name="Candidate Screening Agent",
                agent_type="specialized",
                capabilities=["resume_analysis", "skill_extraction", "fit_scoring"],
                model_tier_preference=ModelTier.STANDARD,
                health_status="DEGRADED", current_load=0, max_concurrent=10,
                circuit_state="HALF_OPEN", failure_count=5,
                last_heartbeat=NOW - timedelta(minutes=5),
            ),
        ]

        # ── N3: Agent Messages ──
        agent_names = [e.agent_name for e in agent_entries]
        messages = []
        for i in range(10):
            sender = random.choice(agent_names)
            receiver = random.choice([a for a in agent_names if a != sender])
            messages.append(AgentMessage(
                id=_id(), tenant_id=TENANT,
                sender_agent_id=sender.lower().replace(" ", "_"),
                receiver_agent_id=receiver.lower().replace(" ", "_"),
                correlation_id=_id(),
                message_type=random.choice(["request", "response", "broadcast", "context_pass"]),
                payload={"task": f"cross_check_{i}", "priority": random.choice(["HIGH", "NORMAL", "LOW"])},
                context_envelope={"trace_id": _id()},
                status=random.choice([
                    AgentMessageStatus.DELIVERED,
                    AgentMessageStatus.PROCESSED,
                    AgentMessageStatus.DELIVERED,
                ]),
                priority=random.randint(1, 7),
                created_at=NOW - timedelta(hours=i * 2, minutes=random.randint(0, 30)),
            ))

        # ── N4: Tenant Onboarding ──
        onboarding = TenantOnboarding(
            id=_id(),
            tenant_id=TENANT,
            tenant_name="Acme Corp",
            industry_vertical="Technology",
            current_stage=OnboardingStage.FULLY_ONBOARDED,
            stage_progress_pct=1.0,
            stages_completed=[
                {"stage": "INITIATED", "completed_at": (NOW - timedelta(days=60)).isoformat()},
                {"stage": "CONNECTORS_CONFIGURED", "completed_at": (NOW - timedelta(days=58)).isoformat()},
                {"stage": "SCHEMA_MAPPED", "completed_at": (NOW - timedelta(days=57)).isoformat()},
                {"stage": "PII_CLASSIFIED", "completed_at": (NOW - timedelta(days=56)).isoformat()},
                {"stage": "KG_POPULATED", "completed_at": (NOW - timedelta(days=55)).isoformat()},
                {"stage": "AGENTS_ACTIVATED", "completed_at": (NOW - timedelta(days=50)).isoformat()},
                {"stage": "FULLY_ONBOARDED", "completed_at": (NOW - timedelta(days=45)).isoformat()},
            ],
            connectors_configured=7,
            entities_discovered=1248,
            mappings_confirmed=94,
            pii_fields_detected=23,
            rules_extracted=68,
            kg_nodes_created=512,
            model_pack_requested=True,
            model_pack_delivered=True,
            model_pack_id="pack_tech_v2",
            initiated_at=NOW - timedelta(days=60),
            completed_at=NOW - timedelta(days=45),
            estimated_completion_hours=48,
        )

        all_objects = models + prompts + budgets + cost_events + agent_entries + messages + [onboarding]
        for obj in all_objects:
            db.add(obj)

        await db.commit()
        print(
            f"[Infrastructure Seed] OK {len(models)} models, {len(prompts)} prompts, "
            f"{len(budgets)} budgets, {len(cost_events)} cost events, "
            f"{len(agent_entries)} agents, {len(messages)} messages, 1 onboarding"
        )


if __name__ == "__main__":
    asyncio.run(seed())
