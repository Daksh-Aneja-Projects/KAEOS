"""KAEOS — AI system inventory & model cards (EU-AI-Act-shaped governance).

Procurement and model-risk reviews ask two questions the product could not
answer from data before: WHICH AI systems run here, and WHAT models do they
use with what oversight? This endpoint derives both from the live registries -
the tenant's actual routed tier->model map, the probe-measured confidence
ceilings, and real oversight counts - instead of prose.

Risk tiers follow the EU AI Act's shape (Annex III employment decisions =
high risk, transparency-tier chat, minimal-risk mechanical text) as KAEOS's
self-classification aid. It is an inventory, not legal advice, and says so.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id

router = APIRouter(prefix="/governance", tags=["Governance — AI Inventory"])

# The AI systems in the product: purpose, the model tier each runs on, the EU-
# AI-Act-shaped risk class, and the oversight that applies. code_ref points at
# the enforcing code so a reviewer can verify the claim, not take it on faith.
_SYSTEMS = [
    {
        "id": "gate_pipeline",
        "name": "7-gate governed execution pipeline",
        "purpose": "Compliance, fairness, confidence/HITL, debate, execution, audit and provenance gates around every agent action",
        "model_tier": "reasoning",
        "risk_tier": "HIGH (governs employment- and finance-affecting decisions)",
        "human_oversight": "Gate 3 routes low-confidence and high-consequence actions to a human; approvals are durable and resumed through the same pipeline",
        "code_ref": "app/agents/runtime.py",
    },
    {
        "id": "fairness_gate",
        "name": "Fairness Gate (Gate 2)",
        "purpose": "Disparate-impact screening of people-affecting decisions",
        "model_tier": "reasoning",
        "risk_tier": "HIGH (Annex III employment shape)",
        "human_oversight": "Statistical four-fifths test when cohort outcomes are supplied (no model involved); LLM screening otherwise, labeled as screening; blocks are human-overridable with justification, audited",
        "code_ref": "app/services/fairness_engine.py + app/services/disparate_impact.py",
    },
    {
        "id": "debate_engine",
        "name": "Adversarial debate (Gate 4)",
        "purpose": "Multi-turn challenge of contested decisions before execution",
        "model_tier": "reasoning",
        "risk_tier": "LIMITED (advisory; strongest outcome is escalation to a human)",
        "human_oversight": "Escalations land in the HITL queue; skipped entirely for decisions a human already approved",
        "code_ref": "app/services/debate_engine.py",
    },
    {
        "id": "skill_executor",
        "name": "Skill execution engine (Gate 5)",
        "purpose": "Runs compiled skill contracts step by step",
        "model_tier": "reasoning",
        "risk_tier": "HIGH when actuating (writes are idempotent, reversible, approver-attributed)",
        "human_oversight": "High-consequence actuations always pause for approval; failures are fail-closed (FAILED_ACTUATION)",
        "code_ref": "app/services/skill_executor.py + Gate 5b in app/agents/runtime.py",
    },
    {
        "id": "extraction",
        "name": "Rule extraction / knowledge mining",
        "purpose": "Mines candidate rules from connected content",
        "model_tier": "classification",
        "risk_tier": "LIMITED (candidates only; maker-checker applies)",
        "human_oversight": "Extracted rules land non-executable; a different authenticated identity must validate before execution",
        "code_ref": "app/api/routes/rules.py (maker-checker)",
    },
    {
        "id": "regulatory_engine",
        "name": "Regulatory directive interpreter",
        "purpose": "Synthesizes candidate compliance rules from pasted directive text",
        "model_tier": "fast",
        "risk_tier": "HIGH (compliance-affecting), mitigated to DRAFT-only output",
        "human_oversight": "Output is never executable until a human validates it (four-eyes)",
        "code_ref": "app/services/regulatory_engine.py",
    },
    {
        "id": "copilot_chat",
        "name": "KAEOS Copilot chat",
        "purpose": "Grounded conversational answers over tenant knowledge",
        "model_tier": "reasoning",
        "risk_tier": "LIMITED (transparency: AI disclosed, citations shown, ungrounded answers admit it)",
        "human_oversight": "Read-only; cannot execute actions",
        "code_ref": "app/api/routes/chat.py",
    },
    {
        "id": "embeddings",
        "name": "Semantic embeddings",
        "purpose": "Vector representations for retrieval and memory recall",
        "model_tier": "embedding",
        "risk_tier": "MINIMAL",
        "human_oversight": "Routed through the LLM router: data-residency filter and cost metering apply to every call",
        "code_ref": "app/services/llm_router.py::embed",
    },
]


@router.get("/ai-inventory")
async def ai_inventory(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """The tenant's AI system inventory + model cards, derived from live state."""
    from app.models.domain import Rule, Skill, SkillExecution
    from app.services.llm_router import LLMRouter

    llm = await LLMRouter.for_tenant(tenant_id)
    tier_map = dict(getattr(llm, "MODEL_TIERS", {}) or {})
    profiles = dict(getattr(llm, "tenant_profiles", {}) or {})

    # Model cards: one per distinct routed model, with the probe-measured
    # ceiling where a probe has run (None = unprobed, honestly reported).
    cards: dict[str, dict] = {}
    for tier, model in tier_map.items():
        card = cards.setdefault(model, {
            "model": model,
            "provider": "local (ollama)" if str(model).startswith("ollama") else "cloud",
            "data_leaves_infrastructure": not str(model).startswith("ollama"),
            "tiers_served": [],
            "probed_confidence_ceiling": None,
        })
        card["tiers_served"].append(tier)
        profile = profiles.get(tier) or {}
        if profile.get("tier_ceiling") is not None:
            card["probed_confidence_ceiling"] = profile["tier_ceiling"]

    # Live oversight counts - the inventory's claims, backed by the tables.
    skills_total = (await db.execute(select(sqlfunc.count(Skill.id)).where(
        Skill.tenant_id == tenant_id))).scalar() or 0
    # Maker-checker queue: rules a second identity has not yet validated.
    rules_draft = (await db.execute(select(sqlfunc.count(Rule.id)).where(
        Rule.tenant_id == tenant_id,
        Rule.is_executable == False))).scalar() or 0  # noqa: E712
    pending_hitl = (await db.execute(select(sqlfunc.count(SkillExecution.id)).where(
        SkillExecution.tenant_id == tenant_id,
        SkillExecution.status == "PENDING_HITL"))).scalar() or 0
    executions = (await db.execute(select(sqlfunc.count(SkillExecution.id)).where(
        SkillExecution.tenant_id == tenant_id))).scalar() or 0
    hitl_routed = (await db.execute(select(sqlfunc.count(SkillExecution.id)).where(
        SkillExecution.tenant_id == tenant_id,
        SkillExecution.hitl_required == True))).scalar() or 0  # noqa: E712

    systems = [
        {**s, "routed_model": tier_map.get(s["model_tier"])}
        for s in _SYSTEMS
    ]
    return {
        "systems": systems,
        "model_cards": sorted(cards.values(), key=lambda c: c["model"]),
        "oversight": {
            "skills_total": skills_total,
            "rules_awaiting_validation": rules_draft,
            "executions_total": executions,
            "executions_routed_to_human": hitl_routed,
            "approvals_pending": pending_hitl,
        },
        "note": (
            "Self-classification aid derived from the live model routing, "
            "probe measurements and execution tables. It maps KAEOS's systems "
            "to EU-AI-Act-shaped risk tiers; it is an inventory, not legal "
            "advice, and an unprobed model reports an unknown ceiling rather "
            "than a flattering one."
        ),
    }
