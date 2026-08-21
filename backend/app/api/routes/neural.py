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
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.result_cache import get_or_compute
from app.core.tenant import check_department_scope, get_tenant, get_tenant_id, require_role
from app.models.auth import User, UserRole
from app.models.domain import Rule, Signal, Skill, SkillExecution
from app.models.agent_factory import DeployedAgent
from app.models.infrastructure import AgentMessage
from app.workforce.models.core import (
    Department, DepartmentAgent, DepartmentStatus,
)
from app.api.routes.neural_helpers import (
    _brain_stats, _build_cluster, _build_world_clusters, _derive_level, _human, _ladder, _match_skills, _policy_min_confidence, _replaces_text, _resolve_department, _skill_exec_stats, _sop_steps, _task_label,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/neural", tags=["Neural Map"])

# Ingest guardrails: a dropped file becomes tenant knowledge, so bound what we
# accept rather than trusting the browser.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_MAX_STORED_CHARS = 20_000
_INGEST_EXTS = {"txt", "md", "markdown", "csv", "tsv", "json", "log", "yaml", "yml", "text"}

# The three rungs of the autonomy ladder, in escalation order. Names are
# user-facing; keep them plain English.
_LADDER = ("human_led", "human_assisted", "fully_autonomous")




















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

    # M7: this is the heaviest read - full fan-out + an O(agents x messages)
    # matching loop + a full graph snapshot in _brain_stats. Cache the BUILT
    # graph, fingerprinted on the cheap counts that actually change its shape;
    # the fingerprint is self-invalidating, so no staleness class of bug.
    _skill_count = (await db.execute(select(sqlfunc.count()).select_from(Skill)
                    .where(Skill.tenant_id == tenant_id))).scalar() or 0
    _msg_count = (await db.execute(select(sqlfunc.count()).select_from(AgentMessage)
                  .where(AgentMessage.tenant_id == tenant_id))).scalar() or 0
    _fingerprint = [len(departments),
                    sum(int(d.agent_count or 0) for d in departments),
                    int(_skill_count), int(_msg_count)]

    async def _compute() -> dict:
        nodes_by_id: dict[str, dict] = {}
        edges: list[dict] = []
        hub_ids: list[str] = []
        agents_by_dept: dict[str, list[dict]] = {}
        # Every cluster's rows are fetched in one query per entity type across all
        # departments (connectors included, which are tenant-wide anyway), instead
        # of five queries per department.
        for dept, n, e in await _build_world_clusters(db, tenant_id, departments):
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

    result, _cached = await get_or_compute(
        "neural_world", tenant_id, _fingerprint, _compute)
    return result










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
            # M4: hr_kb dropped — empty in production; enterprise_memory holds all
            # ingested knowledge (see chat.py _GROUNDING_NAMESPACES).
            for namespace in ("enterprise_memory",):
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
    tenant: dict = Depends(require_role("operator")),
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
        # Only accept text-based documents. Binary formats (PDF, images, exes)
        # decode to non-empty printable-string noise under errors="ignore" and
        # would otherwise be stored as bogus "knowledge".
        ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
        if ext not in _INGEST_EXTS:
            raise HTTPException(
                status_code=415,
                detail="Unsupported file type. Drop a text-based document (txt, md, csv, json, log, yaml).",
            )
        decoded = raw.decode("utf-8", errors="ignore").strip()
        if not decoded:
            raise HTTPException(
                status_code=422,
                detail="Could not read text from that file. Drop a text-based document (txt, md, csv, json).",
            )
        content = f"{content}\n\n{decoded}".strip() if content else decoded
    if not content:
        raise HTTPException(status_code=422, detail="Nothing to ingest - add text or a file")

    # Operator-uploaded content is UNTRUSTED and lands in the same enterprise-memory
    # namespace the copilot grounds on, so it must clear the same gauntlet every
    # other ingest path clears (mirrors live_connectors.records_to_signals):
    #  1. neutralize prompt-injection spans; quarantine (authority 0) if high-risk
    #  2. redact structured PII before it is persisted or embedded
    from app.services import prompt_guard
    from app.transforms.pii_scrubber import redact_structured_pii
    content, injection = prompt_guard.neutralize(content)
    content, _pii_hits = redact_structured_pii(content)
    authority = 0.8  # operator-provided knowledge is high authority...
    if injection.should_block:
        # ...unless it carries an injection payload: keep it human-visible but
        # below every consumer's authority floor so it can never drive an action.
        logger.warning(
            "[BrainIngest] quarantining operator upload from %s: injection risk=%s",
            filename or "operator-note", injection.risk.value,
        )
        content = f"[QUARANTINED: prompt-injection detected] {content}"
        authority = 0.0

    signal = Signal(
        tenant_id=tenant_id,
        source_type="document" if filename else "note",
        source_entity=filename or "operator-note",
        signal_type="KNOWLEDGE",
        domain=domain,
        clean_payload=content[:_MAX_STORED_CHARS],
        authority_score=authority,
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
