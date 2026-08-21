"""KAEOS — Neural Map helpers.

Pure, route-independent builders extracted from ``neural.py``: humanization,
skill matching, department resolution, brain stats, the per-department cluster
graph, and the autonomy-ladder derivations. ``neural.py`` imports these; keeping
them here holds the route module under the size budget without changing behavior.
"""
import logging
from typing import Optional

from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.domain import Connector, Rule, Signal, Skill, SkillExecution
from app.models.settings import AutonomyPolicy
from app.workforce.models.core import (
    BusinessProcess, Capability, Department, DepartmentAgent, DepartmentStatus,
)
from app.workforce.models.integration import IntegrationMapping

logger = logging.getLogger(__name__)


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


_ACRONYMS = {"hr", "it", "ap", "ar", "sla", "kb", "qa", "csat", "cpq", "ip", "pmo", "crm", "sop"}


def _human(identifier: str) -> str:
    """Machine token → plain-English label (skill_ids, agent_types, slugs)."""
    words = (identifier or "").replace("_", " ").replace("-", " ").strip().split()
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w.title() for w in words)


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
    # Four independent COUNTs on four tables: one SELECT of four scalar
    # subqueries instead of four round trips. Same predicates, same numbers.
    def _n(model):
        return select(sqlfunc.count(model.id)).where(model.tenant_id == tenant_id)

    rules, skills, signals, executions = (await db.execute(select(
        _n(Rule).where(Rule.is_archived == False).scalar_subquery(),  # noqa: E712
        _n(Skill).scalar_subquery(),
        _n(Signal).scalar_subquery(),
        _n(SkillExecution).scalar_subquery(),
    ))).one()

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


# Upper bound on task nodes pulled per department cluster.
_CLUSTER_SKILL_CAP = 500


async def _build_cluster(
    db: AsyncSession,
    tenant_id: str,
    dept: Department,
) -> tuple[list[dict], list[dict]]:
    """One department's cluster: hub + connectors + agents + tasks + capabilities
    + processes, with tiered edges. This is the single-department path; the
    org-wide world uses ``_build_world_clusters``, which fetches the same rows
    for every department at once and hands them to the same builder.
    """
    agents = (await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.department_id == dept.id, DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )).scalars().all()

    # Capped: duplicate task labels are collapsed below, but that happens after
    # loading, so an accumulating registry would grow this scan without bound.
    # A graph is not readable past a few hundred task nodes anyway.
    skills = (await db.execute(
        select(Skill)
        .where(Skill.tenant_id == tenant_id)
        .where((Skill.department == dept.slug) | (Skill.domain == dept.slug))
        .order_by(Skill.skill_id)
        .limit(_CLUSTER_SKILL_CAP)
    )).scalars().all()

    # Integrations: explicit mappings and connected_systems are LINKED; beyond
    # those, tenant connectors whose category serves this department appear as
    # feeds (the video-wall top tier is only honest if it shows real systems).
    # One fetch of the full mapping rows serves both the linked-id set and the
    # connector-to-agent wiring in the builder; they had been two queries with
    # the same WHERE, differing only in projection.
    mapping_rows = (await db.execute(
        select(IntegrationMapping)
        .where(IntegrationMapping.department_id == dept.id, IntegrationMapping.tenant_id == tenant_id)
    )).scalars().all()
    all_connectors = (await db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id)
    )).scalars().all()
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
    return _cluster_graph(dept, agents, skills, mapping_rows, all_connectors, capabilities, processes)


async def _build_world_clusters(
    db: AsyncSession,
    tenant_id: str,
    departments: list[Department],
) -> list[tuple[Department, list[dict], list[dict]]]:
    """Every department's cluster, with ONE query per entity type instead of one
    per department: the per-department WHERE becomes an IN over all department
    ids and the rows are bucketed in Python. Row order inside each bucket is the
    order the department-scoped query returned, so the graph is byte-identical.
    """
    dept_ids = [d.id for d in departments]
    slugs = [d.slug for d in departments]

    def _bucket(rows) -> dict[str, list]:
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(r.department_id, []).append(r)
        return out

    agents = _bucket((await db.execute(
        select(DepartmentAgent)
        .where(DepartmentAgent.department_id.in_(dept_ids), DepartmentAgent.tenant_id == tenant_id)
        .order_by(DepartmentAgent.agent_name)
    )).scalars().all())
    mappings = _bucket((await db.execute(
        select(IntegrationMapping)
        .where(IntegrationMapping.department_id.in_(dept_ids), IntegrationMapping.tenant_id == tenant_id)
    )).scalars().all())
    capabilities = _bucket((await db.execute(
        select(Capability)
        .where(Capability.department_id.in_(dept_ids), Capability.tenant_id == tenant_id)
        .order_by(Capability.name)
    )).scalars().all())
    processes = _bucket((await db.execute(
        select(BusinessProcess)
        .where(BusinessProcess.department_id.in_(dept_ids), BusinessProcess.tenant_id == tenant_id)
        .order_by(BusinessProcess.name)
    )).scalars().all())
    # A skill can serve two departments (department=hr, domain=finance), so it
    # is matched per department below rather than bucketed once.
    # ponytail: the per-cluster cap becomes a whole-tenant cap of cap x depts -
    # same rows loaded in the worst case. Past that ceiling a busy department
    # could crowd out a quiet one; go back to per-department LIMITs if a tenant
    # ever ships more than _CLUSTER_SKILL_CAP skills per department.
    all_skills = (await db.execute(
        select(Skill)
        .where(Skill.tenant_id == tenant_id)
        .where(Skill.department.in_(slugs) | Skill.domain.in_(slugs))
        .order_by(Skill.skill_id)
        .limit(_CLUSTER_SKILL_CAP * max(len(departments), 1))
    )).scalars().all()
    all_connectors = (await db.execute(
        select(Connector).where(Connector.tenant_id == tenant_id)
    )).scalars().all()

    return [
        (
            d,
            *_cluster_graph(
                d,
                agents.get(d.id, []),
                [s for s in all_skills if d.slug in (s.department, s.domain)][:_CLUSTER_SKILL_CAP],
                mappings.get(d.id, []),
                all_connectors,
                capabilities.get(d.id, []),
                processes.get(d.id, []),
            ),
        )
        for d in departments
    ]


def _cluster_graph(
    dept: Department,
    agents: list[DepartmentAgent],
    skills: list[Skill],
    mapping_rows: list[IntegrationMapping],
    all_connectors: list[Connector],
    capabilities: list[Capability],
    processes: list[BusinessProcess],
) -> tuple[list[dict], list[dict]]:
    """Pure node/edge assembly for one department, given its already-fetched
    rows. No DB access, so both the single-department graph and the org-wide
    world produce identical clusters from differently-shaped fetches."""
    linked_ids = set([*(m.connector_id for m in mapping_rows), *(dept.connected_systems or [])])
    dept_categories = {
        "hr": {"hris", "communications"},
        "finance": {"commercial"},
        "sales": {"crm", "commercial"},
        "support": {"support", "communications"},
        "engineering": {"engineering"},
        # Legal exchanges contracts over the communications backbone (email /
        # e-signature), so it is not an island in the org graph (Phase 3).
        "operations": {"commercial"},
        "legal": {"communications"},
        "healthcare": {"clinical"},
        "lending": {"core_banking"},
        "procurement": {"procurement"},
    }.get(dept.slug, set())
    connectors = [
        c for c in all_connectors
        if c.id in linked_ids or ((c.category or "") in dept_categories and c.status != "AVAILABLE")
    ]

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
