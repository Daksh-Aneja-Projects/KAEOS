"""KAEOS — Neural Map API.

Composite read layer that powers the Neural Map experience: the org-level
radial map (departments around the company brain), per-department network
graphs (integrations → agents → tasks → hub → brain), derived agent/skill
dossiers (autonomy ladder, what it replaces, SOP), the operator → conductor →
departments hierarchy, and the brain's ingest/search/stats surface.

Everything here is COMPOSED from existing stores (workforce models, connectors,
skills, the polystore vector+graph stores). No new tables: the dossier is
derived live from real fields (always_hitl, AutonomyPolicy, confidence,
execution history), so it can never drift from what the runtime actually does.
"""
import logging
from datetime import datetime, timezone
from statistics import fmean
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.tenant import check_department_scope, get_tenant, get_tenant_id
from app.models.auth import User, UserRole
from app.models.domain import Connector, Rule, Signal, Skill, SkillExecution
from app.models.agent_factory import DeployedAgent
from app.models.infrastructure import AgentMessage
from app.models.settings import AutonomyPolicy
from app.workforce.models.core import (
    BusinessProcess, Capability, Department, DepartmentAgent, DepartmentStatus,
)
from app.workforce.models.integration import IntegrationMapping

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/neural", tags=["Neural Map"])

# Ingest guardrails: a dropped file becomes tenant knowledge, so bound what we
# accept rather than trusting the browser.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_MAX_STORED_CHARS = 20_000

# The three rungs of the autonomy ladder, in escalation order. Names are
# user-facing; keep them plain English.
_LADDER = ("human_led", "human_assisted", "fully_autonomous")


_ACRONYMS = {"hr", "it", "ap", "ar", "sla", "kb", "qa", "csat", "cpq", "ip", "pmo", "crm", "sop"}


def _human(identifier: str) -> str:
    """Machine token → plain-English label (skill_ids, agent_types, slugs)."""
    words = (identifier or "").replace("_", " ").replace("-", " ").strip().split()
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w.title() for w in words)


# What each agent archetype replaces, in the operator's language. Keyed by
# substring of agent_type; first match wins. Fallback derives from the role.
_REPLACES: list[tuple[str, str]] = [
    ("recruiting", "A recruiter screening every resume and scheduling every interview by hand"),
    ("onboarding", "An HR coordinator chasing paperwork and access requests for every new hire"),
    ("offboarding", "A checklist owner making sure departures never leave access behind"),
    ("benefits", "A benefits admin answering the same enrollment questions all year"),
    ("compensation", "An analyst rebuilding pay-band spreadsheets every review cycle"),
    ("performance", "A manager compiling review packets from scattered notes"),
    ("employee_relations", "A case worker triaging sensitive employee issues from a shared inbox"),
    ("ap", "An accounts-payable clerk keying invoices and chasing approvals"),
    ("ar", "A collections analyst manually chasing overdue receivables"),
    ("budget", "A finance partner reconciling budget-vs-actuals in spreadsheets"),
    ("expense", "An expense auditor reviewing every report line by line"),
    ("tax", "A tax preparer assembling filings from exported ledgers"),
    ("lead", "An SDR qualifying inbound leads one by one"),
    ("pipeline", "A sales manager scrubbing the pipeline before every forecast call"),
    ("forecast", "An analyst rebuilding the forecast model every Monday"),
    ("churn", "A CS lead spotting at-risk accounts only after they go quiet"),
    ("account_health", "An account manager manually compiling health scorecards"),
    ("proposal", "A deal desk drafting proposals from stale templates"),
    ("cpq", "A pricing desk hand-checking every quote against discount policy"),
    ("commission", "A comp analyst calculating commissions in a spreadsheet"),
    ("triage", "A support lead reading every ticket to route it"),
    ("auto_resolve", "A tier-1 agent answering the same known issues daily"),
    ("escalation", "A duty manager watching the queue for tickets about to breach"),
    ("sla", "An ops analyst auditing SLA timers after the fact"),
    ("kb", "A knowledge manager updating help articles when someone remembers"),
    ("csat", "An analyst reading survey comments for themes once a quarter"),
    ("resolution", "A senior agent writing root-cause summaries by hand"),
    ("contract", "A paralegal red-lining routine contracts clause by clause"),
    ("compliance", "A compliance officer sampling records to check policy adherence"),
    ("privacy", "A privacy analyst fulfilling data-subject requests by hand"),
    ("litigation", "A case clerk tracking deadlines across active matters"),
    ("ip", "A docket clerk watching renewal dates for the IP portfolio"),
    ("procurement", "A buyer processing purchase requests through email chains"),
    ("vendor", "A vendor manager updating supplier scorecards quarterly"),
    ("project", "A PMO analyst compiling project status decks every week"),
    ("resource", "A resource manager balancing allocations in a spreadsheet"),
    ("qa", "A quality inspector sampling output after problems ship"),
    ("facility", "A facilities coordinator logging and dispatching work orders"),
    ("code_review", "A senior engineer doing first-pass review on every pull request"),
    ("deploy", "A release manager eyeballing risk before every deployment"),
    ("incident", "An on-call lead assembling incident timelines from chat scrollback"),
]


def _task_label(skill_id: str) -> str:
    """Skill id → task label, dropping trailing machine suffixes (hex ids)."""
    stem = (skill_id or "").split("/")[-1]
    parts = stem.replace("-", "_").split("_")
    while len(parts) > 1 and len(parts[-1]) >= 4 and all(c in "0123456789abcdef" for c in parts[-1].lower()):
        parts = parts[:-1]
    return _human("_".join(parts))


def _match_skills(agent: "DepartmentAgent", dept_skills: list["Skill"]) -> list["Skill"]:
    """Skills an agent owns: the explicit list when present, else a token match
    on the agent_type stem (recruiting_agent → *_recruiting_*). Real seed data
    ships empty skill lists, so the fallback is what makes dossiers and
    agent → task edges light up."""
    explicit = [s for s in dept_skills if s.skill_id in (agent.skills or [])]
    if explicit:
        return explicit
    stem = (agent.agent_type or "").lower()
    if stem.endswith("_agent"):
        stem = stem[: -len("_agent")]
    tokens = [t for t in stem.split("_") if t]
    if not tokens:
        return []
    out = []
    for s in dept_skills:
        bag = set((s.skill_id or "").lower().replace("-", "_").split("_"))
        bag |= set((s.domain or "").lower().replace("-", "_").split("_"))
        if all(t in bag for t in tokens):
            out.append(s)
    return out


def _sop_steps(steps: list) -> list[dict]:
    """Skill steps → operator-readable SOP. Machine tokens become plain English."""
    out: list[dict] = []
    for i, step in enumerate(steps or [], start=1):
        if isinstance(step, dict):
            action = step.get("action") or step.get("description") or str(step.get("id", f"step {i}"))
            tool = step.get("tool")
        else:
            action, tool = str(step), None
        if " " not in action and ("_" in action or "-" in action):
            action = _human(action)
        out.append({"order": i, "action": action, "tool": tool})
    return out


def _replaces_text(agent_type: str, role: Optional[str]) -> str:
    at = (agent_type or "").lower()
    for key, text in _REPLACES:
        if key in at:
            return text
    return f"A specialist handling {(role or _human(agent_type) or 'this work').lower()} manually"


async def _resolve_department(db: AsyncSession, ref: str, tenant_id: str) -> Optional[Department]:
    result = await db.execute(
        select(Department)
        .where((Department.id == ref) | (Department.slug == ref))
        .where(Department.tenant_id == tenant_id)
    )
    return result.scalars().first()


async def _brain_stats(db: AsyncSession, tenant_id: str) -> dict:
    """Live knowledge-core stats: what the brain holds and how it clusters."""
    async def _count(q):
        return (await db.execute(q)).scalar() or 0

    rules = await _count(select(sqlfunc.count(Rule.id)).where(
        Rule.tenant_id == tenant_id, Rule.is_archived == False))  # noqa: E712
    skills = await _count(select(sqlfunc.count(Skill.id)).where(Skill.tenant_id == tenant_id))
    signals = await _count(select(sqlfunc.count(Signal.id)).where(Signal.tenant_id == tenant_id))
    executions = await _count(select(sqlfunc.count(SkillExecution.id)).where(
        SkillExecution.tenant_id == tenant_id))

    graph_nodes, graph_edges = 0, 0
    try:
        from app.core.polystore import get_graph_store
        nodes_by_id, edges = await get_graph_store().snapshot(tenant_id)
        graph_nodes, graph_edges = len(nodes_by_id), len(edges)
    except Exception as e:  # pragma: no cover - store outage should not kill the map
        logger.warning(f"[Neural] graph snapshot unavailable: {e}")

    # Domain clusters: how the brain's knowledge distributes across departments.
    cluster_counts: dict[str, int] = {}
    for row in (await db.execute(
        select(Rule.domain, sqlfunc.count(Rule.id))
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.domain.isnot(None))  # noqa: E712
        .group_by(Rule.domain)
    )).all():
        cluster_counts[row[0]] = cluster_counts.get(row[0], 0) + int(row[1])
    for row in (await db.execute(
        select(Skill.department, sqlfunc.count(Skill.id))
        .where(Skill.tenant_id == tenant_id, Skill.department.isnot(None))
        .group_by(Skill.department)
    )).all():
        cluster_counts[row[0]] = cluster_counts.get(row[0], 0) + int(row[1])
    top = max(cluster_counts.values(), default=1)
    clusters = sorted(
        (
            {"domain": d, "label": _human(d), "count": c, "weight": round(c / top, 3)}
            for d, c in cluster_counts.items()
        ),
        key=lambda x: -x["count"],
    )

    return {
        "notes": rules + signals,
        "rules": rules,
        "skills": skills,
        "signals": signals,
        "executions": executions,
        "graph_nodes": graph_nodes,
        "links": graph_edges,
        "clusters": clusters,
    }


@router.get("/map")
async def neural_map(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Org-level radial map: every department around the company brain."""
    result = await db.execute(
        select(Department)
        .where(Department.tenant_id == tenant_id)
        .order_by(Department.created_at)
    )
    departments = result.scalars().all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brain": await _brain_stats(db, tenant_id),
        "departments": [
            {
                "id": d.id,
                "slug": d.slug,
                "name": d.name,
                "status": d.status.value if isinstance(d.status, DepartmentStatus) else d.status,
                "agent_count": d.agent_count,
                "health_score": d.health_score,
                "automation_coverage": d.automation_coverage,
                "tasks_completed_total": d.tasks_completed_total,
            }
            for d in departments
        ],
    }


@router.get("/brain/stats")
async def brain_stats(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    return await _brain_stats(db, tenant_id)


async def _build_cluster(db: AsyncSession, tenant_id: str, dept: Department) -> tuple[list[dict], list[dict]]:
    """One department's cluster: hub + connectors + agents + tasks + capabilities
    + processes, with tiered edges. Shared by the single-department graph and
    the org-wide free-flow world."""
    agents = (await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.department_id == dept.id, DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )).scalars().all()

    skills = (await db.execute(
        select(Skill)
        .where(Skill.tenant_id == tenant_id)
        .where((Skill.department == dept.slug) | (Skill.domain == dept.slug))
        .order_by(Skill.skill_id)
    )).scalars().all()

    # Integrations: explicit mappings and connected_systems are LINKED; beyond
    # those, tenant connectors whose category serves this department appear as
    # feeds (the video-wall top tier is only honest if it shows real systems).
    mapped = (await db.execute(
        select(IntegrationMapping.connector_id)
        .where(IntegrationMapping.department_id == dept.id, IntegrationMapping.tenant_id == tenant_id)
    )).scalars().all()
    linked_ids = set([*mapped, *(dept.connected_systems or [])])
    dept_categories = {
        "hr": {"hris", "communications"},
        "finance": {"commercial"},
        "sales": {"crm", "commercial"},
        "support": {"support", "communications"},
        "engineering": {"engineering"},
        "operations": {"commercial"},
        "legal": set(),
    }.get(dept.slug, set())
    all_connectors = (await db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id)
    )).scalars().all()
    connectors = [
        c for c in all_connectors
        if c.id in linked_ids or ((c.category or "") in dept_categories and c.status != "AVAILABLE")
    ]

    capabilities = (await db.execute(
        select(Capability)
        .where(Capability.department_id == dept.id, Capability.tenant_id == tenant_id)
        .order_by(Capability.name)
    )).scalars().all()
    processes = (await db.execute(
        select(BusinessProcess)
        .where(BusinessProcess.department_id == dept.id, BusinessProcess.tenant_id == tenant_id)
        .order_by(BusinessProcess.name)
    )).scalars().all()

    nodes: list[dict] = [
        {
            "id": dept.id, "type": "department", "label": dept.name, "slug": dept.slug,
            "dept": dept.slug,
            "status": dept.status.value if isinstance(dept.status, DepartmentStatus) else dept.status,
            "health_score": dept.health_score, "agent_count": dept.agent_count,
        },
    ]
    edges: list[dict] = []

    for c in connectors:
        nodes.append({
            "id": c.id, "type": "connector", "label": c.name,
            "category": c.category, "status": c.status, "dept": dept.slug,
        })

    # Collapse duplicate task labels (test artifacts, repeated compiles) into
    # one node with an instance count, so the map shows the work, not the noise.
    task_groups: dict[str, dict] = {}
    for s in skills:
        label = _task_label(s.skill_id)
        g = task_groups.setdefault(label, {"skill": s, "instances": 0, "ids": set()})
        g["instances"] += 1
        g["ids"].add(s.skill_id)

    # agent → task adjacency: explicit skill list, else token match on type.
    claimed: set[str] = set()
    for a in agents:
        nodes.append({
            "id": a.id, "type": "agent", "label": a.agent_name,
            "agent_type": a.agent_type, "dept": dept.slug,
            "role": a.role_in_department, "status": a.status,
            "health_score": a.health_score, "tasks_handled": a.tasks_handled,
        })
        edges.append({"source": a.id, "target": dept.id, "tier": "agent-hub"})
        for s in _match_skills(a, skills):
            label = _task_label(s.skill_id)
            rep = task_groups[label]["skill"].skill_id
            if rep not in claimed:
                claimed.add(rep)
                edges.append({"source": a.id, "target": f"task-{rep}", "tier": "agent-task"})

    # Connectors feed agents that share the connector's capability; when the
    # mapping is not that precise, they feed the department hub.
    cap_agents: dict[str, list[str]] = {}
    for a in agents:
        if a.capability_id:
            cap_agents.setdefault(a.capability_id, []).append(a.id)
    mapping_rows = (await db.execute(
        select(IntegrationMapping)
        .where(IntegrationMapping.department_id == dept.id, IntegrationMapping.tenant_id == tenant_id)
    )).scalars().all()
    wired_connectors: set[str] = set()
    for m in mapping_rows:
        for agent_id in cap_agents.get(m.capability_id or "", []):
            wired_connectors.add(m.connector_id)
            edges.append({"source": m.connector_id, "target": agent_id, "tier": "connector-agent"})
    for c in connectors:
        if c.id not in wired_connectors:
            edges.append({"source": c.id, "target": dept.id, "tier": "connector-hub"})

    for label, g in task_groups.items():
        s = g["skill"]
        hint = ""
        if s.steps:
            first = s.steps[0]
            hint = (first.get("action") or first.get("description") or "") if isinstance(first, dict) else str(first)
            if " " not in hint and ("_" in hint or "-" in hint):
                hint = _human(hint)
        nodes.append({
            "id": f"task-{s.skill_id}", "type": "task", "skill_id": s.skill_id,
            "label": label, "instances": g["instances"], "hint": hint[:60],
            "dept": dept.slug, "status": s.status, "confidence": s.confidence,
            "always_hitl": bool(s.always_hitl), "execution_count": s.execution_count,
        })
        if s.skill_id not in claimed:
            edges.append({"source": f"task-{s.skill_id}", "target": dept.id, "tier": "task-hub"})

    for cap in capabilities:
        nodes.append({
            "id": cap.id, "type": "capability", "label": cap.name, "dept": dept.slug,
            "status": cap.status.value if hasattr(cap.status, "value") else cap.status,
            "automation_pct": cap.automation_pct,
        })
        edges.append({"source": dept.id, "target": cap.id, "tier": "hub-capability"})
    for p in processes:
        nodes.append({
            "id": p.id, "type": "process", "label": p.name, "dept": dept.slug,
            "automation_pct": p.automation_pct, "execution_count": p.execution_count,
            "success_rate": p.success_rate,
        })
        parent = p.capability_id if p.capability_id else dept.id
        edges.append({"source": parent, "target": p.id, "tier": "capability-process"})

    return nodes, edges


@router.get("/departments/{dept_ref}/graph")
async def department_graph(
    dept_ref: str,
    tenant: dict = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """One department as a network: integrations → agents → tasks → hub → brain."""
    tenant_id = tenant["tenant_id"]
    dept = await _resolve_department(db, dept_ref, tenant_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    check_department_scope(tenant, dept.slug)

    nodes, edges = await _build_cluster(db, tenant_id, dept)
    nodes.append({"id": "brain", "type": "brain", "label": "Company Brain"})
    edges.append({"source": dept.id, "target": "brain", "tier": "hub-brain"})

    # Prev/next department for navigation, in creation order.
    all_depts = (await db.execute(
        select(Department.slug)
        .where(Department.tenant_id == tenant_id)
        .order_by(Department.created_at)
    )).scalars().all()
    prev_slug = next_slug = None
    if dept.slug in all_depts and len(all_depts) > 1:
        i = all_depts.index(dept.slug)
        prev_slug = all_depts[i - 1]
        next_slug = all_depts[(i + 1) % len(all_depts)]

    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    return {
        "department": {"id": dept.id, "slug": dept.slug, "name": dept.name},
        "nodes": nodes,
        "edges": edges,
        "prev": prev_slug,
        "next": next_slug,
        "counts": {
            "connectors": by_type.get("connector", 0),
            "agents": by_type.get("agent", 0),
            "tasks": by_type.get("task", 0),
        },
    }


@router.get("/world")
async def neural_world(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """The whole organization as ONE living graph: every department cluster,
    the connectors that bridge departments (a shared CRM links Sales and
    Finance structurally, not decoratively), and the company brain at the
    center that every department feeds. Rendered as a free-flow force layout.
    """
    departments = (await db.execute(
        select(Department).where(Department.tenant_id == tenant_id).order_by(Department.created_at)
    )).scalars().all()

    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []
    hub_ids: list[str] = []
    agents_by_dept: dict[str, list[dict]] = {}
    for dept in departments:
        n, e = await _build_cluster(db, tenant_id, dept)
        for node in n:
            nodes_by_id.setdefault(node["id"], node)
            if node["type"] == "agent":
                agents_by_dept.setdefault(dept.slug, []).append(node)
        edges.extend(e)
        hub_ids.append(dept.id)

    # Every department's memory rolls into the shared company brain.
    nodes_by_id["brain"] = {"id": "brain", "type": "brain", "label": "Company Brain"}
    for h in hub_ids:
        edges.append({"source": h, "target": "brain", "tier": "hub-brain"})
    # Departments connect in sequence - one organization, laid out as a line.
    for i in range(len(hub_ids) - 1):
        edges.append({"source": hub_ids[i], "target": hub_ids[i + 1], "tier": "hub-hub"})

    # Agents that work the same department are peers.
    for peers in agents_by_dept.values():
        for i in range(len(peers) - 1):
            edges.append({"source": peers[i]["id"], "target": peers[i + 1]["id"], "tier": "agent-peer"})

    # Agents that have actually MESSAGED each other (AgentMessage log) get a
    # comms link - matched by shared name tokens, because the protocol log
    # records logical agent names, not DepartmentAgent row ids.
    def _tokens(name: str) -> set[str]:
        stop = {"agent", "worker", "the", "review"}
        return {t for t in (name or "").lower().replace("-", "_").split("_") if t and t not in stop}

    all_agents = [a for peers in agents_by_dept.values() for a in peers]
    msg_pairs = (await db.execute(
        select(AgentMessage.sender_agent_id, AgentMessage.receiver_agent_id)
        .where(AgentMessage.tenant_id == tenant_id)
        .group_by(AgentMessage.sender_agent_id, AgentMessage.receiver_agent_id)
    )).all()
    for sender, receiver in msg_pairs:
        if sender == receiver:
            continue
        src = next((a for a in all_agents if _tokens(sender) & _tokens(a.get("agent_type") or a["label"])), None)
        dst = next((a for a in all_agents if _tokens(receiver) & _tokens(a.get("agent_type") or a["label"])), None)
        if src and dst and src["id"] != dst["id"]:
            edges.append({"source": src["id"], "target": dst["id"], "tier": "agent-comms"})

    seen: set[tuple] = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"])
        if key not in seen and (key[1], key[0]) not in seen:
            seen.add(key)
            unique_edges.append(e)

    return {
        "nodes": list(nodes_by_id.values()),
        "edges": unique_edges,
        "departments": [
            {"id": d.id, "slug": d.slug, "name": d.name,
             "status": d.status.value if isinstance(d.status, DepartmentStatus) else d.status,
             "agent_count": d.agent_count, "health_score": d.health_score}
            for d in departments
        ],
        "brain": await _brain_stats(db, tenant_id),
    }


async def _policy_min_confidence(db: AsyncSession, tenant_id: str, domain: Optional[str]) -> float:
    if domain:
        row = (await db.execute(
            select(AutonomyPolicy)
            .where(AutonomyPolicy.tenant_id == tenant_id, AutonomyPolicy.domain == domain)
        )).scalars().first()
        if row:
            return float(row.min_confidence)
    return float(get_settings().CONFIDENCE_AUTONOMOUS_EXEC)


def _ladder(current: str, subject: str) -> list[dict]:
    """The three-rung autonomy ladder with plain-English rung descriptions."""
    rungs = [
        {
            "level": "human_led",
            "label": "Human led",
            "description": f"You do the work; {subject} drafts and suggests. Nothing happens without you.",
        },
        {
            "level": "human_assisted",
            "label": "Human assisted",
            "description": f"{subject} does the work and queues anything consequential for your approval.",
        },
        {
            "level": "fully_autonomous",
            "label": "Fully autonomous",
            "description": f"{subject} runs end to end inside its guardrails and reports what it did.",
        },
    ]
    for r in rungs:
        r["current"] = r["level"] == current
    return rungs


def _derive_level(avg_confidence: float, min_confidence: float,
                  execution_count: int, any_always_hitl: bool) -> str:
    if execution_count <= 0:
        return "human_led"
    if any_always_hitl or avg_confidence < min_confidence:
        return "human_assisted"
    return "fully_autonomous"


async def _skill_exec_stats(db: AsyncSession, tenant_id: str, skill_ids: list[str]) -> dict:
    if not skill_ids:
        return {"executions": 0, "succeeded": 0, "hitl_reviews": 0, "last_run": None}
    rows = (await db.execute(
        select(
            sqlfunc.count(SkillExecution.id),
            sqlfunc.sum(case((SkillExecution.status == "COMPLETED", 1), else_=0)),
            sqlfunc.sum(case((SkillExecution.hitl_required == True, 1), else_=0)),  # noqa: E712
            sqlfunc.max(SkillExecution.started_at),
        ).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.skill_id_name.in_(skill_ids),
        )
    )).one()
    return {
        "executions": int(rows[0] or 0),
        "succeeded": int(rows[1] or 0),
        "hitl_reviews": int(rows[2] or 0),
        "last_run": str(rows[3]) if rows[3] else None,
    }


@router.get("/agents/{agent_id}/dossier")
async def agent_dossier(
    agent_id: str,
    tenant: dict = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Everything an operator needs to trust one agent, on one card."""
    tenant_id = tenant["tenant_id"]
    agent = (await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.id == agent_id, DepartmentAgent.tenant_id == tenant_id)
    )).scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    dept = (await db.execute(
        select(Department).where(Department.id == agent.department_id)
    )).scalars().first()
    if dept:
        check_department_scope(tenant, dept.slug)

    dept_skills = []
    if dept:
        dept_skills = (await db.execute(
            select(Skill)
            .where(Skill.tenant_id == tenant_id)
            .where((Skill.department == dept.slug) | (Skill.domain == dept.slug))
        )).scalars().all()
    linked = _match_skills(agent, dept_skills)

    min_conf = await _policy_min_confidence(db, tenant_id, dept.slug if dept else None)
    avg_conf = fmean([s.confidence or 0.0 for s in linked]) if linked else 0.0
    any_hitl = any(s.always_hitl for s in linked)
    exec_stats = await _skill_exec_stats(db, tenant_id, [s.skill_id for s in linked])
    level = _derive_level(avg_conf, min_conf, exec_stats["executions"], any_hitl)

    # SOP: the first linked skill with concrete steps speaks for the agent.
    sop: list[dict] = []
    tools: list[str] = []
    for s in linked:
        for t in (s.mcp_tool_bindings or []):
            name = t.get("tool") if isinstance(t, dict) else str(t)
            if name and name not in tools:
                tools.append(name)
        if not sop and s.steps:
            sop = _sop_steps(s.steps)

    schedule = "Continuous - reacts to live department signals"
    if agent.deployed_agent_id:
        deployed = (await db.execute(
            select(DeployedAgent).where(DeployedAgent.id == agent.deployed_agent_id)
        )).scalars().first()
        trig = (deployed.trigger_config or {}) if deployed else {}
        if trig.get("schedule"):
            schedule = str(trig["schedule"])
        elif trig.get("trigger_type"):
            schedule = f"Triggered by {_human(str(trig['trigger_type']))}"

    if any_hitl:
        human_role = "You approve every consequential action before it lands. The agent prepares, you decide."
    elif level == "fully_autonomous":
        human_role = "You set the guardrails and review the digest. It escalates anything unusual to you."
    else:
        human_role = "You review its queue and approve or redirect. Each decision teaches it your judgment."

    return {
        "id": agent.id,
        "name": agent.agent_name,
        "agent_type": agent.agent_type,
        "department": {"id": dept.id, "slug": dept.slug, "name": dept.name} if dept else None,
        "role": agent.role_in_department,
        "persona": agent.persona,
        "status": agent.status,
        "health_score": agent.health_score,
        "tasks_handled": agent.tasks_handled,
        "last_active_at": str(agent.last_active_at) if agent.last_active_at else None,
        "autonomy": {
            "level": level,
            "ladder": _ladder(level, "the agent"),
            "avg_confidence": round(avg_conf, 3),
            "required_confidence": min_conf,
            "always_hitl": any_hitl,
        },
        "replaces": _replaces_text(agent.agent_type, agent.role_in_department),
        "human_role": human_role,
        "schedule": schedule,
        "sop": sop,
        "breaks_into": [
            {"skill_id": s.skill_id, "label": _task_label(s.skill_id),
             "confidence": s.confidence, "status": s.status}
            for s in linked
        ],
        "builds_on": tools,
        "execution_stats": exec_stats,
        "compliance_tags": agent.compliance_tags or [],
    }


@router.get("/skills/{skill_id}/dossier")
async def skill_dossier(
    skill_id: str,
    tenant: dict = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Task-node dossier: the skill contract, framed for an operator."""
    tenant_id = tenant["tenant_id"]
    skill = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.skill_id == skill_id)
    )).scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.department:
        check_department_scope(tenant, skill.department)

    min_conf = await _policy_min_confidence(db, tenant_id, skill.department or skill.domain)
    exec_stats = await _skill_exec_stats(db, tenant_id, [skill.skill_id])
    level = _derive_level(skill.confidence or 0.0, min_conf,
                          exec_stats["executions"], bool(skill.always_hitl))

    # Who runs this task: the department agent that owns it (explicit or matched).
    owner = (await db.execute(
        select(DepartmentAgent).where(DepartmentAgent.tenant_id == tenant_id)
    )).scalars().all()
    done_by = next(
        ({"id": a.id, "name": a.agent_name, "role": a.role_in_department}
         for a in owner if _match_skills(a, [skill])),
        None,
    )

    sop = _sop_steps(skill.steps)

    return {
        "skill_id": skill.skill_id,
        "label": _task_label(skill.skill_id),
        "department": skill.department,
        "domain": skill.domain,
        "status": skill.status,
        "version": skill.version,
        "confidence": skill.confidence,
        "confidence_tier": skill.confidence_tier,
        "autonomy": {
            "level": level,
            "ladder": _ladder(level, "this task"),
            "required_confidence": min_conf,
            "always_hitl": bool(skill.always_hitl),
        },
        "done_by": done_by,
        "sop": sop,
        "triggers": skill.triggers or [],
        "guardrails": skill.guardrails or {},
        "builds_on": [
            (t.get("tool") if isinstance(t, dict) else str(t))
            for t in (skill.mcp_tool_bindings or [])
        ],
        "execution_stats": exec_stats,
        "compliance_tags": skill.compliance_tags or [],
    }


@router.get("/hierarchy")
async def hierarchy(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Operator → Conductor → departments → agents, for the org chart."""
    operator = (await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.role == UserRole.ADMIN)
        .order_by(User.created_at).limit(1)
    )).scalars().first()

    departments = (await db.execute(
        select(Department).where(Department.tenant_id == tenant_id).order_by(Department.created_at)
    )).scalars().all()
    agents = (await db.execute(
        select(DepartmentAgent).where(DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )).scalars().all()
    by_dept: dict[str, list[DepartmentAgent]] = {}
    for a in agents:
        by_dept.setdefault(a.department_id, []).append(a)

    pending_hitl = (await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.hitl_required == True,  # noqa: E712
            SkillExecution.hitl_approved.is_(None),
        )
    )).scalar() or 0

    return {
        "operator": {
            "name": operator.display_name if operator else "Operator",
            "email": operator.email if operator else None,
            "title": "Operator",
        },
        "conductor": {
            "name": "KAEOS Copilot",
            "description": "Your super agent. Knows every agent, skill and decision in this workspace and answers with grounded evidence.",
            "grounded_on": ["Enterprise memory", "Knowledge base"],
            "pending_approvals": int(pending_hitl),
        },
        "departments": [
            {
                "id": d.id,
                "slug": d.slug,
                "name": d.name,
                "status": d.status.value if isinstance(d.status, DepartmentStatus) else d.status,
                "health_score": d.health_score,
                "tasks_completed_total": d.tasks_completed_total,
                "agents": [
                    {
                        "id": a.id, "name": a.agent_name, "role": a.role_in_department,
                        "status": a.status, "tasks_handled": a.tasks_handled,
                    }
                    for a in by_dept.get(d.id, [])
                ],
            }
            for d in departments
        ],
    }


@router.get("/brain/search")
async def brain_search(
    q: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Query the whole brain: semantic over memory + rules, keyword fallback."""
    q = (q or "").strip()
    if not q:
        return {"query": q, "results": []}

    results: list[dict] = []

    # 1) Semantic over the memory namespaces (same stores the copilot cites).
    try:
        from app.core.polystore import get_vector_store
        from app.services.llm_router import get_tenant_router
        llm = await get_tenant_router(tenant_id)
        embedding = (await llm.embed([q]))[0]
        if not llm.embeddings_simulated:
            store = get_vector_store()
            for namespace in ("enterprise_memory", "hr_kb"):
                for r in await store.search(
                    tenant_id=tenant_id, query_embedding=embedding, limit=5, namespace=namespace,
                ):
                    if r.get("content") and float(r.get("similarity") or 0) >= 0.3:
                        results.append({
                            "kind": "memory",
                            "id": r["id"],
                            "score": round(float(r["similarity"]), 3),
                            "content": r["content"][:400],
                        })
    except Exception as e:
        logger.warning(f"[Neural] semantic search unavailable: {e}")

    # 2) Keyword over rules and skills so the brain always answers something real.
    like = f"%{q}%"
    for rule in (await db.execute(
        select(Rule).where(Rule.tenant_id == tenant_id, Rule.is_archived == False,  # noqa: E712
                           Rule.statement.ilike(like)).limit(5)
    )).scalars().all():
        results.append({
            "kind": "rule", "id": rule.id, "score": None,
            "content": rule.statement[:400], "domain": rule.domain,
        })
    for skill in (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.skill_id.ilike(like)).limit(5)
    )).scalars().all():
        results.append({
            "kind": "skill", "id": skill.skill_id, "score": None,
            "content": _human(skill.skill_id.split("/")[-1]),
            "domain": skill.department or skill.domain,
        })

    return {"query": q, "results": results[:12]}


@router.post("/brain/ingest")
async def brain_ingest(
    text: Optional[str] = Form(None),
    domain: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Dump into the brain: a note or a document becomes tenant knowledge.

    The content is stored as a Signal and embedded into the enterprise-memory
    vector namespace - the same namespace the Conductor grounds its answers on,
    so what you drop here immediately changes what the copilot knows.
    """
    content = (text or "").strip()
    filename = None
    if file is not None:
        raw = await file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large (2 MB limit)")
        filename = file.filename
        decoded = raw.decode("utf-8", errors="ignore").strip()
        if not decoded:
            raise HTTPException(
                status_code=422,
                detail="Could not read text from that file. Drop a text-based document (txt, md, csv, json).",
            )
        content = f"{content}\n\n{decoded}".strip() if content else decoded
    if not content:
        raise HTTPException(status_code=422, detail="Nothing to ingest - add text or a file")

    signal = Signal(
        tenant_id=tenant_id,
        source_type="document" if filename else "note",
        source_entity=filename or "operator-note",
        signal_type="KNOWLEDGE",
        domain=domain,
        clean_payload=content[:_MAX_STORED_CHARS],
        authority_score=0.8,  # operator-provided knowledge is high authority
        temporal_class="CURRENT",
    )
    db.add(signal)
    await db.commit()
    await db.refresh(signal)

    embedded = False
    try:
        from app.core.polystore import get_vector_store
        from app.services.llm_router import get_tenant_router
        llm = await get_tenant_router(tenant_id)
        embedding = (await llm.embed([content[:8000]]))[0]
        if not llm.embeddings_simulated:
            await get_vector_store().upsert(
                vector_id=f"brain-doc-{signal.id}",
                tenant_id=tenant_id,
                content=content[:4000],
                embedding=embedding,
                metadata={"source": filename or "operator-note", "domain": domain},
                namespace="enterprise_memory",
            )
            embedded = True
    except Exception as e:
        logger.warning(f"[Neural] ingest embedding failed: {e}")

    # Make the new knowledge visible on the graph too.
    try:
        from app.core.polystore import get_graph_store
        gs = get_graph_store()
        node_id = f"knowledge-{signal.id}"
        await gs.upsert_node(tenant_id, node_id, "Knowledge", {
            "name": filename or content[:48],
            "source": signal.source_type,
        })
        if domain:
            await gs.upsert_edge(tenant_id, node_id, f"domain-{domain}", "INFORMS", {})
    except Exception as e:
        logger.warning(f"[Neural] ingest graph write failed: {e}")

    return {
        "signal_id": signal.id,
        "stored_chars": min(len(content), _MAX_STORED_CHARS),
        "source": filename or "note",
        "embedded": embedded,
        "grounding_ready": embedded,
        "message": (
            "Learned and embedded - the Conductor can cite this now."
            if embedded else
            "Stored. Embedding was unavailable, so semantic recall will pick this up once embeddings are back."
        ),
    }
