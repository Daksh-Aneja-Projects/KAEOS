"""Company Skills File — the Company Brain, exported as an executable artifact.

Compiles a tenant's operating knowledge (validated rules + compiled skills,
with confidence, compliance tags, and governance context) into a portable
document any AI agent can consume: markdown for context windows, JSON for
programmatic use. Every skill listed here is executable ONLY through the
7-gate pipeline — the file inherits the platform's governance instead of
bypassing it.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Rule, Skill

GOVERNANCE_NOTE = (
    "Every skill in this file executes ONLY through the KAEOS 7-gate pipeline "
    "(compliance, fairness, confidence, human gate, debate, execute, provenance). "
    "Low-confidence and high-consequence actions pause for a human. "
    "Invoke skills via the MCP tool `execute_skill` or POST /skills/{id}/execute."
)


def _rule_entry(r: Rule) -> dict:
    return {
        "id": r.id,
        "domain": r.domain or "general",
        "statement": r.statement,
        "confidence": round(r.confidence_scalar or 0.0, 3),
        "tier": r.confidence_tier.value if r.confidence_tier else None,
        "is_executable": bool(r.is_executable),
        "compliance_tags": r.compliance_tags or [],
    }


def _skill_entry(s: Skill) -> dict:
    return {
        "skill_id": s.skill_id,
        "department": s.department or "general",
        "domain": s.domain,
        "status": s.status,
        "confidence": round(s.confidence or 0.0, 3),
        "confidence_tier": s.confidence_tier,
        "execution_count": s.execution_count or 0,
        "success_rate": round(s.success_rate or 0.0, 3),
        "triggers": len(s.triggers or []),
        "steps": len(s.steps or []),
        "compliance_tags": s.compliance_tags or [],
        "mcp_tool_bindings": s.mcp_tool_bindings or [],
    }


async def build_skills_file(db: AsyncSession, tenant_id: str) -> dict:
    """Collect the tenant's brain into a structured skills-file payload."""
    rules = (
        (await db.execute(
            select(Rule)
            .where(Rule.tenant_id == tenant_id, Rule.is_archived.is_(False))
            .order_by(Rule.confidence_scalar.desc())
        )).scalars().all()
    )
    skills = (
        (await db.execute(
            select(Skill)
            .where(Skill.tenant_id == tenant_id, Skill.status != "ARCHIVED")
            .order_by(Skill.confidence.desc())
        )).scalars().all()
    )
    return {
        "artifact": "kaeos-company-skills-file",
        "version": 1,
        "tenant_id": tenant_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "governance": GOVERNANCE_NOTE,
        "counts": {"rules": len(rules), "skills": len(skills)},
        "rules": [_rule_entry(r) for r in rules],
        "skills": [_skill_entry(s) for s in skills],
    }


def render_markdown(payload: dict) -> str:
    """Render the skills-file payload as agent-ready markdown."""
    lines = [
        "# KAEOS Company Skills File",
        "",
        f"> tenant: `{payload['tenant_id']}` · generated: {payload['generated_at']}",
        f"> rules: {payload['counts']['rules']} · skills: {payload['counts']['skills']}",
        "",
        "## How agents must use this file",
        "",
        f"{payload['governance']}",
        "",
        "Treat rules as hard constraints on any action you take for this",
        "organization. Treat skills as the ONLY sanctioned way to act: do not",
        "improvise a workflow that a listed skill already governs.",
        "",
        "## Operating rules",
        "",
    ]
    by_domain: dict[str, list] = {}
    for r in payload["rules"]:
        by_domain.setdefault(r["domain"], []).append(r)
    for domain in sorted(by_domain):
        lines.append(f"### {domain}")
        for r in by_domain[domain]:
            tags = f" (compliance: {', '.join(r['compliance_tags'])})" if r["compliance_tags"] else ""
            tier = r["tier"] or "UNSCORED"
            lines.append(f"- [{tier} · {r['confidence']:.2f}] {r['statement']}{tags}")
        lines.append("")

    lines += ["## Executable skills", ""]
    by_dept: dict[str, list] = {}
    for s in payload["skills"]:
        by_dept.setdefault(s["department"], []).append(s)
    for dept in sorted(by_dept):
        lines.append(f"### {dept}")
        for s in by_dept[dept]:
            lines.append(f"#### {s['skill_id']}")
            lines.append(
                f"- status {s['status']} · confidence {s['confidence']:.2f}"
                f" · executions {s['execution_count']} · success {s['success_rate']:.0%}"
            )
            lines.append(f"- triggers: {s['triggers']} · steps: {s['steps']}")
            if s["compliance_tags"]:
                lines.append(f"- compliance: {', '.join(s['compliance_tags'])}")
        lines.append("")
    return "\n".join(lines)
