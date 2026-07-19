import logging
from typing import Dict, Any

from app.services.evolution.fitness_calculator import FitnessCalculator

logger = logging.getLogger(__name__)

class EvolutionEngine:
    """
    Proactively evaluates Enterprise Fitness and generates structural Evolution Recommendations.
    """

    def __init__(self, graph_service=None):
        """graph_service is optional — engine works without it using pattern-based analysis."""
        self.graph = graph_service
        self.fitness_calculator = FitnessCalculator(graph_service)

    async def evaluate_and_evolve(self, tenant_id: str) -> Dict[str, Any]:
        """
        Calculates fitness, detects threshold breaches, and generates data-driven optimization proposals.
        """
        logger.info("EvolutionEngine: Initiating Enterprise Evolution Analysis...")

        # 1. Current State Fitness
        fitness_result = await self.fitness_calculator.calculate_fitness(tenant_id)
        current_fitness = fitness_result["global_fitness_score"]
        subscores = fitness_result["subscores"]
        factors = fitness_result.get("factors", {})

        logger.info(f"EvolutionEngine: Current Enterprise Fitness: {current_fitness:.3f}")

        recommendations = []

        # 2. Trigger-based Recommendation Generation — data-driven, no hardcoded strings
        if subscores.get("portfolio_fitness", 1.0) < 0.7:
            logger.warning("EvolutionEngine: Portfolio Fitness breach detected.")
            waste = factors.get("portfolio_waste", {})
            duplicate_count = waste.get("duplicate_initiatives", 0)
            recommendations.append({
                "type": "PORTFOLIO_CONSOLIDATION",
                "description": (
                    f"Portfolio fitness at {subscores['portfolio_fitness']:.0%}. "
                    f"Detected {duplicate_count} overlapping initiative(s). "
                    "Consolidate redundant workstreams targeting the same strategic goal."
                ),
                "expected_improvement": round(max(0.03, (0.7 - subscores["portfolio_fitness"]) * 0.5), 3),
                "expected_cost": int(duplicate_count * 15000),
                "expected_risk": 0.2,
                "capability_improvement": 0.0,
                "target_fitness_delta": round(0.7 - subscores["portfolio_fitness"], 3),
            })

        if subscores.get("capability_fitness", 1.0) < 0.7:
            logger.warning("EvolutionEngine: Capability Gap breach detected.")
            gaps = factors.get("capability_gaps", [])
            top_gap = gaps[0] if gaps else "critical capability"
            recommendations.append({
                "type": "CAPABILITY_INVESTMENT",
                "description": (
                    f"Capability fitness at {subscores['capability_fitness']:.0%}. "
                    f"Critical gap identified: '{top_gap}'. "
                    "Reallocate engineers and fund targeted upskilling or external hire."
                ),
                "expected_improvement": round(max(0.05, (0.7 - subscores["capability_fitness"]) * 0.6), 3),
                "expected_cost": int(len(gaps) * 40000),
                "expected_risk": 0.4,
                "capability_improvement": round(len(gaps) * 0.05, 3),
                "target_fitness_delta": round(0.7 - subscores["capability_fitness"], 3),
            })

        if subscores.get("vendor_fitness", 1.0) < 0.6:
            logger.warning("EvolutionEngine: Vendor Concentration breach detected.")
            conc = factors.get("vendor_concentration", {})
            top_vendor = conc.get("top_vendor", "primary vendor")
            pct = conc.get("concentration_pct", 70)
            recommendations.append({
                "type": "VENDOR_DIVERSIFICATION",
                "description": (
                    f"Vendor fitness at {subscores['vendor_fitness']:.0%}. "
                    f"'{top_vendor}' supplies {pct}% of project dependencies. "
                    "Diversify 30-40% to qualified secondary vendors."
                ),
                "expected_improvement": round(max(0.03, (0.6 - subscores["vendor_fitness"]) * 0.4), 3),
                "expected_cost": 60000,
                "expected_risk": 0.3,
                "capability_improvement": 0.0,
                "target_fitness_delta": round(0.6 - subscores["vendor_fitness"], 3),
            })

        if subscores.get("workforce_fitness", 1.0) < 0.6:
            logger.warning("EvolutionEngine: Workforce Imbalance breach detected.")
            overloaded = factors.get("overloaded_teams", [])
            recommendations.append({
                "type": "WORKFORCE_REALLOCATION",
                "description": (
                    f"Workforce fitness at {subscores['workforce_fitness']:.0%}. "
                    f"{len(overloaded)} team(s) are over-allocated. "
                    "Rebalance engineers toward under-resourced strategic initiatives."
                ),
                "expected_improvement": round(max(0.06, (0.6 - subscores["workforce_fitness"]) * 0.7), 3),
                "expected_cost": int(len(overloaded) * 5000),
                "expected_risk": 0.1,
                "capability_improvement": 0.05,
                "target_fitness_delta": round(0.6 - subscores["workforce_fitness"], 3),
            })

        # 3. Simulate Future State
        total_delta = sum(r["target_fitness_delta"] for r in recommendations)
        future_fitness = min(1.0, current_fitness + total_delta)

        # Rank by expected improvement
        recommendations.sort(key=lambda x: x["expected_improvement"], reverse=True)

        logger.info(
            f"EvolutionEngine: {len(recommendations)} optimization(s) generated. "
            f"Future Simulated Fitness: {future_fitness:.3f}"
        )

        return {
            "current_fitness": current_fitness,
            "future_fitness": future_fitness,
            "fitness_delta": round(future_fitness - current_fitness, 3),
            "subscores": subscores,
            "factors": factors,
            "optimizations": recommendations,
        }

    # ── L10 closed-loop feedback (migrated from the shadowed app/services/evolution.py) ──

    @staticmethod
    async def handle_agent_failure(execution_id: str, task_intent: str, context_data: dict,
                                   skill_id: str, department: str, tenant_id: str):
        """
        Triggered when a skill execution fails or is human-overridden.
        Finds the domain expert and creates a targeted ElicitationQuestion.
        """
        import json
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.domain import Employee, ElicitationQuestion

        async with AsyncSessionLocal() as db:
            expert_q = await db.execute(
                select(Employee)
                .where(Employee.department == department)
                .order_by(Employee.authority_score.desc())
                .limit(1)
            )
            expert = expert_q.scalar_one_or_none()
            if not expert:
                expert = (await db.execute(select(Employee).limit(1))).scalar_one_or_none()
            if not expert:
                logger.warning(f"No employees found to handle failure for {skill_id}")
                return

            context_str = json.dumps(context_data)[:100] if context_data else "{}"
            question_text = (
                f"Hi {expert.display_name or 'there'}, an agent recently failed while executing the '{skill_id}' skill "
                f"for the intent '{task_intent}'. It encountered an edge case with the following context: {context_str}... "
                f"Could you explain the unwritten rule or exception that applies here?"
            )
            # Derive real (heuristic) quality scores from the generated question
            # instead of hardcoding them — otherwise they inflate the dashboard's
            # avg_quality_score with fabricated numbers.
            from app.services.elicitation import score_question_quality
            _q = score_question_quality(
                question_text,
                {"first_name": expert.display_name},
                {"context_ref": f"exec:{execution_id}", "action": task_intent},
            ).as_dict()
            eq = ElicitationQuestion(
                tenant_id=tenant_id,
                employee_id=expert.id,
                question_text=question_text,
                question_type="EXCEPTION_HANDLING",
                context_ref=f"exec:{execution_id}",
                priority="HIGH",
                delivery_channel="slack",
                status="PENDING",
                specificity=_q["specificity"],
                groundedness=_q["groundedness"],
                answerability=_q["answerability"],
            )
            db.add(eq)
            await db.commit()
            logger.info(f"Autonomously generated ElicitationQuestion for {expert.display_name} regarding {skill_id} failure.")
