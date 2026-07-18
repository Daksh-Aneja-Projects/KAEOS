"""
Acceptance Test: Decision Studio End-to-End Pipeline
Scenario: Critical Vendor Bankruptcy
"""

import asyncio
import logging
import uuid

from app.core.database import AsyncSessionLocal, init_db
from app.services.decision.option_engine import OptionGenerationEngine
from app.services.decision.constraint_engine import DecisionConstraintEngine
from app.services.decision.evaluation_engine import OptionEvaluationEngine
from app.models.intelligence_metrics import DecisionRecord, DecisionTrace

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

# Mock Graph for testing
class MockGraph:
    pass

async def run_decision_acceptance_test():
    logger.info("==================================================")
    logger.info("   DECISION STUDIO ACCEPTANCE TEST STARTED        ")
    logger.info("==================================================")
    
    await init_db()
    
    graph = MockGraph()
    option_engine = OptionGenerationEngine(graph)
    constraint_engine = DecisionConstraintEngine(graph)
    evaluation_engine = OptionEvaluationEngine(graph)
    
    tenant_id = "tenant_test"
    event_type = "VENDOR_BANKRUPTCY"
    target_entity = "vendor_critical_5"
    
    # 1. Option Generation (Tier 1)
    logger.info("--- 1. Generating Options (Tier 1) ---")
    context = {"enterprise_trust_score": 0.92, "available_budget": 200000, "available_workforce": 10, "risk_appetite": 0.8}
    options = await option_engine.generate_options(event_type, target_entity, context)
    for opt in options:
        logger.info(f"Generated Option: {opt['action']} | Risk: {opt['risk_score']} | Est. EV: {opt['initial_expected_value']:.2f}")
        
    # 2. Constraint Evaluation
    logger.info("--- 2. Evaluating Constraints ---")
    constrained_options = []
    for opt in options:
        c_opt = await constraint_engine.evaluate_constraints(opt, context)
        constrained_options.append(c_opt)
        if c_opt["is_rejected_by_constraints"]:
            logger.warning(f"Option Rejected: {c_opt['action']} | Violations: {c_opt['constraint_violations']}")
        else:
            logger.info(f"Option Valid: {c_opt['action']}")
            
    # Filter out rejected options
    viable_options = [opt for opt in constrained_options if not opt["is_rejected_by_constraints"]]
    
    # 3. Deep Evaluation (Tier 2)
    logger.info("--- 3. Deep Evaluation & Ranking (Tier 2) ---")
    evaluated_options = []
    for opt in viable_options:
        deep_opt = await evaluation_engine.evaluate_option_deep(opt, context)
        evaluated_options.append(deep_opt)
        
    # Rank by Deep Decision Quality
    evaluated_options.sort(key=lambda x: x["deep_decision_quality"], reverse=True)
    
    for rank, opt in enumerate(evaluated_options):
        logger.info(f"Rank {rank+1}: {opt['action']} | Quality Score: {opt['deep_decision_quality']:.3f} | EV: {opt['deep_expected_value']:.3f}")
        
    # 4. Selection & Ledger Storage
    logger.info("--- 4. Storing Decision Ledger & Trace ---")
    best_option = evaluated_options[0]
    
    async with AsyncSessionLocal() as db:
        # Create Decision Record
        decision_id = str(uuid.uuid4())
        record = DecisionRecord(
            tenant_id=tenant_id,
            context=f"Response to {event_type} on {target_entity}",
            options_considered={opt["action"]: opt["deep_decision_quality"] for opt in evaluated_options},
            recommendation=best_option["action"],
            selected_action=best_option["action"],
            decision_maker="EXECUTIVE_TWIN",
            evaluation_tier=2,
            decision_score=best_option["deep_decision_quality"],
            expected_value=best_option["deep_expected_value"],
            risk_score=best_option["risk_score"],
            decision_quality_score=best_option["deep_decision_quality"],
            expected_outcome=best_option["description"]
        )
        db.add(record)
        
        # Create Decision Trace
        trace = DecisionTrace(
            trace_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_event=event_type,
            decision_record_id=decision_id,
            generated_options=options,
            constraint_evaluations={opt["action"]: opt["constraint_violations"] for opt in constrained_options},
            simulation_results={opt["action"]: opt["dimensions"] for opt in evaluated_options},
            executive_summary=f"Selected '{best_option['action']}' due to highest decision quality ({best_option['deep_decision_quality']:.2f}) and constraint compliance."
        )
        db.add(trace)
        
        await db.commit()
        logger.info(f"Successfully recorded DecisionRecord ({decision_id}) and DecisionTrace ({trace.trace_id}) to Ledger.")

    logger.info("==================================================")
    logger.info("   DECISION STUDIO ACCEPTANCE TEST COMPLETE       ")
    logger.info("==================================================")

if __name__ == "__main__":
    asyncio.run(run_decision_acceptance_test())
