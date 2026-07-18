"""
KAEOS — Live Enterprise Twin

Builds the enterprise twin graph from the live database instead of the static
enterprise_graph.json artifact, so the Reality Experience reflects the same
data as every other dashboard: departments, capabilities, agents, processes,
HR employees, finance vendors, and operations projects.
"""
import logging
from collections import deque
from typing import Dict, List, Tuple

from sqlalchemy import select

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# group numbers drive node colors in the frontend graph
GROUPS = {
    "Department": 1,
    "Capability": 2,
    "Agent": 3,
    "Process": 4,
    "Employee": 5,
    "Vendor": 6,
    "Project": 7,
}


async def build_live_twin(tenant_id: str) -> Tuple[Dict[str, dict], List[dict]]:
    """Return (nodes, edges) for the tenant, straight from the DB."""
    from app.workforce.models.core import (
        Department, Capability, DepartmentAgent, BusinessProcess,
    )
    from app.hr.models.core import HREmployee
    from app.finance.models.accounts_payable import Vendor
    from app.operations.models.projects import Project

    nodes: Dict[str, dict] = {}
    edges: List[dict] = []

    def add_node(node_id: str, label: str, name: str, **props):
        nodes[node_id] = {
            "id": node_id,
            "label": label,
            "name": name,
            "group": GROUPS.get(label, 0),
            **props,
        }

    def add_edge(source: str, target: str, rel: str):
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "type": rel})

    async with AsyncSessionLocal() as db:
        deps = (
            await db.execute(select(Department).where(Department.tenant_id == tenant_id))
        ).scalars().all()
        dept_by_slug = {}
        for d in deps:
            add_node(d.id, "Department", d.name, slug=d.slug,
                     status=str(d.status), health=d.health_score)
            dept_by_slug[d.slug] = d.id

        caps = (
            await db.execute(select(Capability).where(Capability.tenant_id == tenant_id))
        ).scalars().all()
        for c in caps:
            add_node(c.id, "Capability", c.name, status=str(c.status),
                     automation_pct=c.automation_pct)
            add_edge(c.department_id, c.id, "PROVIDES")

        agents = (
            await db.execute(select(DepartmentAgent).where(DepartmentAgent.tenant_id == tenant_id))
        ).scalars().all()
        for a in agents:
            add_node(a.id, "Agent", a.agent_name, status=a.status,
                     role=a.role_in_department)
            add_edge(a.department_id, a.id, "EMPLOYS")

        procs = (
            await db.execute(select(BusinessProcess).where(BusinessProcess.tenant_id == tenant_id))
        ).scalars().all()
        for p in procs:
            add_node(p.id, "Process", p.name, status=p.status,
                     success_rate=p.success_rate)
            if p.capability_id and p.capability_id in nodes:
                add_edge(p.capability_id, p.id, "RUNS")
            else:
                add_edge(p.department_id, p.id, "RUNS")

        emps = (
            await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id))
        ).scalars().all()
        hr_dept = dept_by_slug.get("hr")
        for e in emps:
            add_node(e.id, "Employee", f"{e.first_name} {e.last_name}",
                     title=e.job_title, status=str(e.status))
            add_edge(e.department_id or hr_dept, e.id, "STAFFS")

        vendors = (
            await db.execute(select(Vendor).where(Vendor.tenant_id == tenant_id))
        ).scalars().all()
        fin_dept = dept_by_slug.get("finance")
        for v in vendors:
            add_node(v.id, "Vendor", v.name, status=str(v.status),
                     risk=v.risk_level, spend_ytd=v.total_spend_ytd)
            if fin_dept:
                add_edge(fin_dept, v.id, "CONTRACTS")

        projects = (
            await db.execute(select(Project).where(Project.tenant_id == tenant_id))
        ).scalars().all()
        ops_dept = dept_by_slug.get("operations")
        for pr in projects:
            add_node(pr.id, "Project", pr.name, status=str(pr.status))
            if ops_dept:
                add_edge(ops_dept, pr.id, "EXECUTES")

    return nodes, edges


def twin_stats(nodes: Dict[str, dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for n in nodes.values():
        counts[n["label"]] = counts.get(n["label"], 0) + 1
    return {
        "employees": counts.get("Employee", 0),
        "departments": counts.get("Department", 0),
        "capabilities": counts.get("Capability", 0),
        "agents": counts.get("Agent", 0),
        "vendors": counts.get("Vendor", 0),
        "projects": counts.get("Project", 0),
        "processes": counts.get("Process", 0),
    }


def traverse_blast_radius(
    nodes: Dict[str, dict], edges: List[dict], start_id: str, max_depth: int = 3
) -> List[dict]:
    """Undirected BFS from start_id — a shock cascades both up and down."""
    if start_id not in nodes:
        return []
    adjacency: Dict[str, List[Tuple[str, str]]] = {}
    for e in edges:
        adjacency.setdefault(e["source"], []).append((e["target"], e["type"]))
        adjacency.setdefault(e["target"], []).append((e["source"], e["type"]))

    results: List[dict] = []
    visited = {start_id}
    queue: deque = deque([(start_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor, rel in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            results.append({"downstream": nodes[neighbor], "rel": rel, "depth": depth + 1})
            queue.append((neighbor, depth + 1))
    return results
