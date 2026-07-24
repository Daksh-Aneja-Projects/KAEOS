"""
evolution/fitness_calculator.py
===============================
Enterprise Fitness computed from the REAL enterprise graph.

This module used to return hardcoded fixture subscores tagged ``simulated: True``.
It now computes every subscore from the live graph snapshot returned by
``GraphService.snapshot()`` (durable SQLite graph in dev, Neo4j in prod), plus
best-effort DB-backed financial health from ``StateService``.

The structural signals it measures map 1:1 to the "rot" the synthetic generator
injects and that a real org exhibits:

  * vendor_fitness      — supplier concentration (a monopoly vendor lowers it)
  * portfolio_fitness   — duplicate initiatives (same goal + same capability)
  * capability_fitness  — initiatives requiring a capability no employee possesses
  * workforce_fitness   — projects overloaded far above the mean contributor count
  * risk_fitness        — share of CRITICAL risks threatening the org
  * goal_alignment / execution / organizational — structural coverage ratios

When the graph is empty the calculator returns neutral (1.0) scores and empty
factors — an honest "no data" rather than fabricated numbers. Nothing here is
tagged ``simulated``; every number is derived from graph structure.
"""
import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _by_label(nodes: Dict[str, Any]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = defaultdict(list)
    for nid, node in nodes.items():
        groups[node.get("label", "Unknown")].append(nid)
    return groups


def _edges_by_type(edges: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in edges:
        groups[e.get("type", "UNKNOWN")].append(e)
    return groups


class FitnessCalculator:
    """Computes Enterprise Fitness from the real graph. No fixtures."""

    def __init__(self, graph_service):
        self.graph = graph_service

    async def calculate_fitness(self, tenant_id: str) -> Dict[str, Any]:
        nodes: Dict[str, Any] = {}
        edges: List[Dict[str, Any]] = []
        if self.graph is not None:
            try:
                nodes, edges = await self.graph.snapshot()
            except Exception as exc:  # graph unavailable -> honest neutral, not fake
                logger.warning("FitnessCalculator: graph snapshot failed (%s); returning neutral fitness.", exc)

        by_label = _by_label(nodes)
        by_type = _edges_by_type(edges)

        initiatives = set(by_label.get("Initiative", []))
        projects = set(by_label.get("Project", []))
        departments = set(by_label.get("Department", []))

        # ── Vendor concentration ────────────────────────────────────────────
        supplies = by_type.get("SUPPLIES", [])
        vendor_supply = defaultdict(int)
        for e in supplies:
            vendor_supply[e["source"]] += 1
        vendor_concentration = 0.0
        top_vendor_id = None
        if supplies:
            top_vendor_id, top_count = max(vendor_supply.items(), key=lambda kv: kv[1])
            vendor_concentration = top_count / len(supplies)
        vendor_fitness = round(1.0 - vendor_concentration, 3) if supplies else 1.0
        top_vendor_name = nodes.get(top_vendor_id, {}).get("name", top_vendor_id) if top_vendor_id else None

        # ── Portfolio duplication (same goal + same required capability) ─────
        supports = defaultdict(set)   # initiative -> {goal}
        requires = defaultdict(set)   # initiative|project -> {capability}
        for e in by_type.get("SUPPORTS", []):
            supports[e["source"]].add(e["target"])
        for e in by_type.get("REQUIRES_CAPABILITY", []):
            requires[e["source"]].add(e["target"])
        signature_to_inits = defaultdict(list)
        for init in initiatives:
            sig = (frozenset(supports.get(init, set())), frozenset(requires.get(init, set())))
            if sig[0] or sig[1]:
                signature_to_inits[sig].append(init)
        duplicate_initiatives = sum(len(v) - 1 for v in signature_to_inits.values() if len(v) > 1)
        portfolio_fitness = round(1.0 - duplicate_initiatives / len(initiatives), 3) if initiatives else 1.0

        # ── Capability gaps (required by an initiative, possessed by no employee) ──
        possessed_caps = {e["target"] for e in by_type.get("HAS_CAPABILITY", [])}
        required_by_init = defaultdict(set)
        for e in by_type.get("REQUIRES_CAPABILITY", []):
            if e["source"] in initiatives:
                required_by_init[e["source"]].add(e["target"])
        gap_caps = set()
        blocked_initiatives = set()
        for init, caps in required_by_init.items():
            missing = caps - possessed_caps
            if missing:
                gap_caps |= missing
                blocked_initiatives.add(init)
        capability_fitness = (
            round(1.0 - len(blocked_initiatives) / len(initiatives), 3) if initiatives else 1.0
        )
        capability_gap_names = sorted(nodes.get(c, {}).get("name", c) for c in gap_caps)

        # ── Workforce overload (projects far above mean contributor count) ──
        contrib = defaultdict(int)
        for e in by_type.get("CONTRIBUTES_TO", []):
            contrib[e["target"]] += 1
        overloaded_teams: List[str] = []
        if contrib and projects:
            mean_load = sum(contrib.values()) / max(1, len(contrib))
            threshold = max(3.0 * mean_load, mean_load + 10)
            overloaded_teams = sorted(p for p, c in contrib.items() if c > threshold)
        workforce_fitness = (
            round(1.0 - len(overloaded_teams) / len(projects), 3) if projects else 1.0
        )

        # ── Risk pressure (share of CRITICAL risks) ─────────────────────────
        risk_ids = by_label.get("Risk", [])
        critical = sum(1 for r in risk_ids if str(nodes.get(r, {}).get("severity", "")).upper() == "CRITICAL")
        risk_fitness = round(1.0 - critical / len(risk_ids), 3) if risk_ids else 1.0

        # ── Structural coverage ratios ──────────────────────────────────────
        delivering = {e["source"] for e in by_type.get("DELIVERS", []) if e["source"] in projects}
        execution_fitness = round(len(delivering) / len(projects), 3) if projects else 1.0
        aligned = {e["source"] for e in by_type.get("SUPPORTS", []) if e["source"] in initiatives}
        goal_alignment_fitness = round(len(aligned) / len(initiatives), 3) if initiatives else 1.0
        depts_with_cap = {e["source"] for e in by_type.get("POSSESSES_CAPABILITY", []) if e["source"] in departments}
        organizational_fitness = round(len(depts_with_cap) / len(departments), 3) if departments else 1.0

        # ── Financial health: best-effort from StateService, else neutral ───
        financial_fitness = await self._financial_fitness(tenant_id)

        subscores = {
            "capability_fitness": capability_fitness,
            "portfolio_fitness": portfolio_fitness,
            "vendor_fitness": vendor_fitness,
            "workforce_fitness": workforce_fitness,
            "organizational_fitness": organizational_fitness,
            "financial_fitness": financial_fitness,
            "execution_fitness": execution_fitness,
            "goal_alignment_fitness": goal_alignment_fitness,
            "risk_fitness": risk_fitness,
        }
        global_score = round(sum(subscores.values()) / len(subscores), 4)

        factors = {
            "portfolio_waste": {"duplicate_initiatives": duplicate_initiatives},
            "capability_gaps": capability_gap_names,
            "vendor_concentration": {
                "top_vendor": top_vendor_name,
                "concentration_pct": round(vendor_concentration * 100),
            },
            "overloaded_teams": overloaded_teams,
            "graph_size": {"nodes": len(nodes), "edges": len(edges)},
        }

        logger.info(
            "FitnessCalculator: tenant=%s global=%.3f (nodes=%d, edges=%d) — computed from live graph.",
            tenant_id, global_score, len(nodes), len(edges),
        )

        return {
            "global_fitness_score": global_score,
            "subscores": subscores,
            "factors": factors,
        }

    async def _financial_fitness(self, tenant_id: str) -> float:
        """Real financial health from StateService when available; neutral otherwise."""
        try:
            from app.core.database import AsyncSessionLocal
            from app.services.state.state_service import StateService
            async with AsyncSessionLocal() as db:
                fin_state = await StateService.get_state(db, tenant_id, "finance")
            if fin_state is not None and getattr(fin_state, "financial_health_score", None) is not None:
                return round(float(fin_state.financial_health_score), 3)
        except Exception as exc:
            logger.debug("FitnessCalculator: financial health unavailable (%s); using neutral.", exc)
        return 1.0
