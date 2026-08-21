"""
KAEOS — Live Enterprise Twin

Builds the enterprise twin graph from the live database instead of the static
enterprise_graph.json artifact, so the Reality Experience reflects the same
data as every other dashboard: departments, capabilities, agents, processes,
HR employees, finance vendors, and operations projects.
"""
import importlib
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
    "Customer": 8,
    "Account": 9,
    "Ticket": 10,
    "Contract": 11,
    "Incident": 12,
    "PurchaseOrder": 13,
    "Encounter": 14,
    "LoanApplication": 15,
    "Requisition": 16,
}

# Per department, how many of each headline entity to weave into the twin. Enough
# for a rich, balanced constellation; the physics stays smooth and stats stay
# honest (computed from the full graph before sampling).
_ENTITY_SAMPLE = 14

# One headline entity per department, woven in on top of the structural
# backbone. Each row is exactly the _weave() call it declares:
#   ("module:Class", node label, department slug, edge type, name attribute,
#    extra _weave kwargs)
# The import is late and by name (same "module:Class" convention as
# app/core/domain_seed.py) so a department whose models are absent degrades to
# "missing from the twin" instead of breaking the whole build.
# Not the department roster (app.core.domain_seed.DEPARTMENT_SLUGS): hr has no
# entry on purpose - HREmployee is already woven in structurally below - and the
# slug here selects a MODEL, so there is nothing to derive from the roster.
_HEADLINE_WEAVES = [
    ("app.finance.models.accounts_receivable:Customer", "Customer", "finance", "SERVES", "name", {}),
    ("app.sales.models.accounts:Account", "Account", "sales", "OWNS", "name",
     {"status_attr": "health_score"}),
    ("app.support.models.tickets:Ticket", "Ticket", "support", "HANDLES", "subject", {}),
    ("app.legal.models.contracts:Contract", "Contract", "legal", "GOVERNS", "title",
     {"name_fn": lambda c: getattr(c, "title", None) or getattr(c, "counterparty", None) or "Contract"}),
    ("app.engineering.models.incidents:Incident", "Incident", "engineering", "OWNS", "title",
     {"name_fn": lambda i: getattr(i, "title", None) or getattr(i, "incident_number", None) or "Incident"}),
    ("app.operations.models.procurement:PurchaseOrder", "PurchaseOrder", "operations", "ORDERS", "po_number",
     {"name_fn": lambda p: f"PO {getattr(p, 'po_number', '')} · {getattr(p, 'vendor_name', '')}"[:60]}),
    ("app.healthcare.models.core:PatientEncounter", "Encounter", "healthcare", "TREATS", "encounter_number",
     {"name_fn": lambda e: f"Encounter {getattr(e, 'encounter_number', '') or ''}".strip() or "Encounter"}),
    ("app.lending.models.core:LoanApplication", "LoanApplication", "lending", "UNDERWRITES", "applicant_name",
     {"name_fn": lambda loan: getattr(loan, "applicant_name", None) or getattr(loan, "application_number", None) or "Loan Application"}),
    # The dedicated Procurement department's headline record: internal purchase
    # claims before a PO is issued (distinct from Operations' PurchaseOrder row
    # above, which tracks the PO once it exists).
    ("app.operations.models.procurement:PurchaseRequest", "Requisition", "procurement", "REQUESTS", "item_description", {}),
]


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

        # Sampled like every other headline entity (see _ENTITY_SAMPLE): the twin
        # is a balanced constellation, not an HR-employee cloud — an enterprise
        # tenant's full headcount would drown the graph and the physics.
        emps = (
            await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id)
                             .limit(_ENTITY_SAMPLE))
        ).scalars().all()
        hr_dept = dept_by_slug.get("hr")
        for e in emps:
            add_node(e.id, "Employee", f"{e.first_name} {e.last_name}",
                     title=e.job_title, status=str(e.status))
            add_edge(e.department_id or hr_dept, e.id, "STAFFS")

        vendors = (
            await db.execute(select(Vendor).where(Vendor.tenant_id == tenant_id)
                             .limit(_ENTITY_SAMPLE))
        ).scalars().all()
        fin_dept = dept_by_slug.get("finance")
        for v in vendors:
            add_node(v.id, "Vendor", v.name, status=str(v.status),
                     risk=v.risk_level, spend_ytd=v.total_spend_ytd)
            if fin_dept:
                add_edge(fin_dept, v.id, "CONTRACTS")

        projects = (
            await db.execute(select(Project).where(Project.tenant_id == tenant_id).limit(_ENTITY_SAMPLE))
        ).scalars().all()
        ops_dept = dept_by_slug.get("operations")
        for pr in projects:
            add_node(pr.id, "Project", pr.name, status=str(pr.status))
            if ops_dept:
                add_edge(ops_dept, pr.id, "EXECUTES")

        # ── Cross-domain headline entities: weave a SAMPLE of each domain's real
        #    records into the twin so the constellation is rich AND balanced across
        #    every department (not just an HR-employee cloud). Each query is bounded.
        async def _weave(model, label, dept_slug, rel, name_attr, name_fn=None,
                         status_attr="status", extra=None):
            dept = dept_by_slug.get(dept_slug)
            if not dept:
                return
            rows = (await db.execute(select(model).where(model.tenant_id == tenant_id)
                                     .limit(_ENTITY_SAMPLE))).scalars().all()
            for r in rows:
                name = name_fn(r) if name_fn else (getattr(r, name_attr, None) or label)
                props = {}
                st = getattr(r, status_attr, None)
                if st is not None:
                    props["status"] = str(st)
                if extra:
                    props.update({k: getattr(r, v, None) for k, v in extra.items()})
                add_node(r.id, label, str(name)[:60], **props)
                add_edge(dept, r.id, rel)

        for path, label, slug, rel, name_attr, opts in _HEADLINE_WEAVES:
            module, _, cls = path.partition(":")
            try:
                model = getattr(importlib.import_module(module), cls)
            except (ImportError, AttributeError):
                # Was silent: a renamed or moved model deleted a whole
                # department from the twin with no trace. Still degrades
                # (the twin builds without it), but now it is visible.
                logger.warning("Reality twin: cannot import %s - the %s department "
                               "will have no %s nodes", path, slug, label, exc_info=True)
                continue
            try:
                await _weave(model, label, slug, rel, name_attr, **opts)
            except Exception:
                logger.warning("Reality twin: failed to weave %s domain", label, exc_info=True)

    return nodes, edges


# The twin is a "living organization" HERO visual, not an exhaustive dump. With
# real data a department can have hundreds of employees; rendering every one turns
# the constellation into an unreadable hairball (and the O(N^2) client physics
# chokes). We keep the full structural backbone and sample the high-cardinality
# leaf entities to a legible-but-representative count PER DEPARTMENT.
_STRUCTURAL = {"Department", "Capability", "Agent", "Process"}
_LEAF_PER_DEPT_CAP = 12   # up to N employees/vendors/projects shown per department


def sample_twin_for_view(nodes: Dict[str, dict], edges: List[dict],
                         per_dept_cap: int = _LEAF_PER_DEPT_CAP) -> Tuple[Dict[str, dict], List[dict]]:
    """Return a legible subset: full backbone + a per-department sample of leaves.

    Stats are computed from the FULL graph by the caller, so the numbers stay
    honest even though the constellation only draws a representative sample.
    """
    # Map each leaf node to the department it hangs off (via its incoming edge).
    parent_of: Dict[str, str] = {}
    for e in edges:
        # edges point department/capability -> leaf; the leaf is the target
        if e["target"] in nodes and e["source"] in nodes:
            parent_of.setdefault(e["target"], e["source"])

    kept: Dict[str, dict] = {}
    per_group: Dict[str, int] = {}
    for nid, n in nodes.items():
        if n["label"] in _STRUCTURAL:
            kept[nid] = n
    # Sample leaves, capped per (parent, type) so every department stays populated.
    for nid, n in nodes.items():
        if n["label"] in _STRUCTURAL:
            continue
        key = f"{parent_of.get(nid, 'orphan')}::{n['label']}"
        if per_group.get(key, 0) >= per_dept_cap:
            continue
        per_group[key] = per_group.get(key, 0) + 1
        kept[nid] = n

    view_edges = [e for e in edges if e["source"] in kept and e["target"] in kept]
    return kept, view_edges


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
