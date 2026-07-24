"""AEOS Pioneer Layer API Routes
P1 External Intelligence + P2 Org Intelligence + L6 Simulation
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.services.external_intelligence import ExternalIntelligenceEngine
from app.services.org_intelligence import OrgIntelligenceEngine
from app.core.tenant import get_tenant_id, require_role
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["AEOS Pioneer Layers"])

ext_intel = ExternalIntelligenceEngine()
org_intel = OrgIntelligenceEngine()


# ─── P1: External Intelligence ───

class SignalIngestRequest(BaseModel):
    signal_type: str  # REGULATORY | VENDOR | MARKET | THREAT | ECONOMIC
    source: str
    title: str
    content: str
    severity: str = "MEDIUM"

class CorrelateRequest(BaseModel):
    signal_content: str


@router.post("/intelligence/signals")
async def ingest_signal(req: SignalIngestRequest, tenant: dict = Depends(require_role("operator"))):
    """P1 — Ingest an external signal (regulatory, vendor, market, threat). Requires operator role (persists a Signal that drives Brain decisions)."""
    tenant_id = tenant["tenant_id"]
    if req.signal_type not in ext_intel.SIGNAL_TYPES:
        raise HTTPException(400, f"Invalid signal_type. Must be one of: {ext_intel.SIGNAL_TYPES}")
    return await ext_intel.ingest_signal(
        req.signal_type, req.source, req.title, req.content, req.severity,
        tenant_id=tenant_id
    )

@router.post("/intelligence/correlate", dependencies=[Depends(require_role("operator"))])
async def correlate_signal(req: CorrelateRequest, tenant_id: str = Depends(get_tenant_id)):
    """P1 — Correlate an external signal with the Company Brain."""
    return await ext_intel.correlate_with_brain(req.signal_content, tenant_id=tenant_id)

@router.post("/intelligence/proactive-alert", dependencies=[Depends(require_role("operator"))])
async def generate_proactive_alert(req: SignalIngestRequest, tenant_id: str = Depends(get_tenant_id)):
    """P1 — Generate proactive alert from external signal."""
    return await ext_intel.generate_proactive_alert(req.signal_type, req.content, tenant_id=tenant_id)


# ─── P2: Org Intelligence ───

class ChangeReadinessRequest(BaseModel):
    department: str
    change_description: str

class InfluencePathRequest(BaseModel):
    target_outcome: str
    department: str


@router.post("/org-intelligence/change-readiness", dependencies=[Depends(require_role("operator"))])
async def score_change_readiness(req: ChangeReadinessRequest, tenant_id: str = Depends(get_tenant_id)):
    """P2 — Score change readiness for a department."""
    return await org_intel.score_change_readiness(req.department, req.change_description, tenant_id=tenant_id)

@router.post("/org-intelligence/influence-path", dependencies=[Depends(require_role("operator"))])
async def map_influence_path(req: InfluencePathRequest, tenant_id: str = Depends(get_tenant_id)):
    """P2 — Plan optimal stakeholder engagement path."""
    return await org_intel.map_influence_path(req.target_outcome, req.department, tenant_id=tenant_id)

@router.get("/org-intelligence/skills-topology")
async def get_skills_topology(tenant_id: str = Depends(get_tenant_id)):
    """P2 — Get skills topology map across departments."""
    return await org_intel.get_skills_topology(tenant_id=tenant_id)


# ─── L6: Simulation ───

class SimulationRequest(BaseModel):
    change_description: str
    target_domain: str
    risk_tolerance: str = "MEDIUM"  # LOW | MEDIUM | HIGH


@router.post("/simulation/what-if", dependencies=[Depends(require_role("operator"))])
async def run_simulation(
    req: SimulationRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L6 — What-if simulation before execution.

    The BLAST RADIUS is computed from the tenant's REAL data (how many executable
    rules and skills are actually in scope, and which departments) — not
    hallucinated. The LLM adds the qualitative layer (verdict, risk factors,
    mitigations, recommendation); if it is unavailable or sparse, a deterministic
    verdict/rollback is derived from the real scope so the result is never empty.
    """
    from app.services.llm_router import LLMRouter
    from sqlalchemy import select, func, distinct
    from app.models.domain import Rule, Skill
    import json

    domain = (req.target_domain or "all").strip().lower()
    all_domains = domain in ("", "all", "all domains")

    # ── Real blast radius from the tenant's data ──────────────────────────
    rule_q = select(func.count(Rule.id)).where(
        Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.is_executable == True  # noqa: E712
    )
    skill_q = select(func.count(Skill.id)).where(Skill.tenant_id == tenant_id)
    if not all_domains:
        rule_q = rule_q.where(func.lower(Rule.domain).like(f"%{domain}%"))
        skill_q = skill_q.where(
            (func.lower(Skill.department).like(f"%{domain}%"))
            | (func.lower(Skill.domain).like(f"%{domain}%"))
        )
    affected_rules = int((await db.execute(rule_q)).scalar() or 0)
    affected_skills = int((await db.execute(skill_q)).scalar() or 0)

    all_depts = [d for d in (await db.execute(
        select(distinct(Skill.department)).where(Skill.tenant_id == tenant_id)
    )).scalars().all() if d]
    if all_domains:
        affected_departments = all_depts
    else:
        affected_departments = [d for d in all_depts if domain in d.lower()] or [req.target_domain]

    real_blast = {
        "affected_rules": affected_rules,
        "affected_skills": affected_skills,
        "affected_departments": affected_departments,
    }
    scope = affected_rules + affected_skills

    # ── LLM narrative (verdict + risks + recommendation), best-effort ─────
    prompt = (
        f"You are the KAEOS Digital Twin Simulation Engine.\n"
        f"Proposed change: {req.change_description}\n"
        f"Target domain: {req.target_domain}\n"
        f"Risk tolerance: {req.risk_tolerance}\n"
        f"Real scope from the enterprise twin: {affected_rules} executable rules, "
        f"{affected_skills} skills, departments {affected_departments}.\n\n"
        f"Assess this change. Output ONLY JSON:\n"
        f"{{\"simulation_result\": \"SAFE|RISKY|BLOCKED\", "
        f"\"risk_factors\": [{{\"factor\": \"...\", \"severity\": \"HIGH|MEDIUM|LOW\", \"mitigation\": \"...\"}}], "
        f"\"estimated_rollback_time_hours\": int, \"recommendation\": \"...\"}}"
    )
    narrative: dict = {}
    try:
        res = await LLMRouter().complete(prompt=prompt, model_tier="reasoning")
        content = res if isinstance(res, str) else res.get("content", "{}")
        parsed = json.loads(content) if content else {}
        if isinstance(parsed, dict):
            narrative = parsed
    except Exception:
        narrative = {}

    # Deterministic verdict from real scope + risk tolerance when the LLM is sparse.
    verdict = str(narrative.get("simulation_result", "")).upper()
    if verdict not in ("SAFE", "RISKY", "BLOCKED"):
        if scope == 0:
            verdict = "SAFE"
        elif req.risk_tolerance == "conservative" or scope > 20:
            verdict = "RISKY"
        else:
            verdict = "RISKY" if scope > 8 else "SAFE"

    rollback = narrative.get("estimated_rollback_time_hours")
    if not isinstance(rollback, int):
        rollback = max(1, scope // 2)

    return {
        "status": "SIMULATED",
        "simulation_result": verdict,
        "blast_radius": real_blast,
        "risk_factors": narrative.get("risk_factors", []),
        "estimated_rollback_time_hours": rollback,
        "recommendation": narrative.get("recommendation", ""),
    }
