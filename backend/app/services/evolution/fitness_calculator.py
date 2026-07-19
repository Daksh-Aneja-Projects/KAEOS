"""
evolution/fitness_calculator.py
===============================
SIMULATED PLACEHOLDER — NOT WIRED TO ANY ENDPOINT.

WARNING: every subscore and narrative below is a hardcoded fixture, NOT computed
telemetry. This class is only consumed by ``EvolutionEngine.evaluate_and_evolve``,
which is itself never called anywhere in the app (verified by grep) — it is dead
code. The REAL, DB-backed fitness computation lives in
``app/api/routes/genome_evolution.py`` (``_live_features`` + ``/evolution/state``),
which derives subscores from live HR/agent/skill/vendor rows.

Do NOT surface anything returned here as measured fitness. Outputs carry a
``simulated: True`` flag so a caller can never mistake these constants for real
per-tenant analysis. If this path is ever revived, replace the literals with a
``_live_features``-style DB query (it needs a ``db`` session, which this signature
does not currently take).
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FitnessCalculator:
    """
    SIMULATED PLACEHOLDER (dead code) — returns fixed demo constants, not computed
    fitness. See module docstring. The real graph/DB-backed fitness path is in
    ``app/api/routes/genome_evolution.py``.
    """
    def __init__(self, graph_service):
        self.graph = graph_service

    async def calculate_fitness(self, tenant_id: str) -> Dict[str, Any]:
        """
        SIMULATED PLACEHOLDER — returns hardcoded fixture subscores/narratives.
        Not wired to any endpoint; does not query the graph or DB.
        """
        logger.warning(
            "FitnessCalculator.calculate_fitness is a SIMULATED PLACEHOLDER returning "
            "hardcoded constants (tenant_id=%s ignored) — not real telemetry.", tenant_id
        )

        # In a full implementation, these would be Cypher queries:
        # Example Cypher for Capability Gap:
        # MATCH (i:Initiative)-[:REQUIRES_CAPABILITY]->(c:Capability)
        # OPTIONAL MATCH (e:Employee)-[:CONTRIBUTES_TO]->(:Project)-[:DELIVERS]->(i)
        # WHERE NOT (e)-[:HAS_CAPABILITY]->(c)
        # RETURN count(i) as gap_count

        # SIMULATED PLACEHOLDER — all scores/factors below are fixed fixtures, NOT
        # computed from any tenant's data. See module docstring.

        # 1. Capability Fitness (Detects the Quantum Computing Gap)
        capability_score = 0.65
        cap_factors = {
            "negative": ["Initiative 'Quantum R&D' requires 'Quantum Computing' but 0 assigned employees possess it."],
            "positive": ["Core capabilities (AI, SWE) are well-distributed across active projects."],
            "opportunities": ["Hire or upskill 5 engineers in Quantum Computing."]
        }
        
        # 2. Portfolio Fitness (Detects the Duplicate Initiatives)
        portfolio_score = 0.50
        port_factors = {
            "negative": ["Initiatives 'Cloud Migration Alpha' and 'Cloud Migration Beta' support the same Goal and require identical Capabilities (Waste)."],
            "positive": ["Remaining 13 initiatives are mutually exclusive and aligned."],
            "opportunities": ["Merge 'Cloud Migration Beta' into 'Alpha' to save 12% OPEX."]
        }
        
        # 3. Vendor Fitness (Detects Vendor Monopoly)
        vendor_score = 0.40
        vendor_factors = {
            "negative": ["Vendor 'Monopoly Corp' supplies 80% of all Projects. Critical Single-Point-of-Failure."],
            "positive": ["Remaining 19 vendors are well-distributed."],
            "opportunities": ["Renegotiate or diversify 30% of Monopoly Corp's contracts to backup vendors."]
        }
        
        # 4. Workforce Fitness (Detects Overloaded Team)
        workforce_score = 0.55
        workforce_factors = {
            "negative": ["Project 'proj_0' has 200 employees assigned (Severe Overload / Diminishing Returns)."],
            "positive": ["Department load distribution is otherwise balanced."],
            "opportunities": ["Reallocate 150 engineers from 'proj_0' to high-impact capability gaps."]
        }
        
        # Global Fitness Calculation
        subscores = {
            "capability_fitness": capability_score,
            "portfolio_fitness": portfolio_score,
            "vendor_fitness": vendor_score,
            "workforce_fitness": workforce_score,
            "organizational_fitness": 0.85,
            "financial_fitness": 0.80,
            "execution_fitness": 0.70,
            "goal_alignment_fitness": 0.75,
            "risk_fitness": 0.60
        }
        
        global_score = sum(subscores.values()) / len(subscores)
        
        return {
            "simulated": True,  # SIMULATED PLACEHOLDER — fixed constants, not measured
            "global_fitness_score": global_score,
            "subscores": subscores,
            "factors": {
                "capability": cap_factors,
                "portfolio": port_factors,
                "vendor": vendor_factors,
                "workforce": workforce_factors
            }
        }
