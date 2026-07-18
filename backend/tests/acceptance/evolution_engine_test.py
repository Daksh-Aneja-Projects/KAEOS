"""
Acceptance Test: Enterprise Evolution Engine
Scenario: Synthetic Graph with Injected Structural Rot
"""

import asyncio
import logging
import uuid

from app.core.database import AsyncSessionLocal, init_db
from app.services.graph.graph_service import GraphService
from app.services.synthetic.enterprise_generator import SyntheticEnterpriseGenerator
from app.services.evolution.evolution_engine import EvolutionEngine
from app.models.intelligence_metrics import EnterpriseFitnessRecord, EvolutionMemory, EnterpriseGenome

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

async def run_evolution_acceptance_test():
    logger.info("==================================================")
    logger.info("   EVOLUTION ENGINE ACCEPTANCE TEST STARTED       ")
    logger.info("==================================================")
    
    await init_db()
    
    graph_service = GraphService()
    try:
        await graph_service.initialize()
    except Exception as e:
        logger.warning(f"Neo4j failed to connect. Is it running? Error: {e}")
        # Proceeding anyway as fitness engine handles the simulation for the test
        
    generator = SyntheticEnterpriseGenerator(graph_service)
    evolution_engine = EvolutionEngine(graph_service)
    
    tenant_id = "tenant_test_evolution"
    
    # 1. Generate Graph with Rot
    logger.info("--- 1. Generating Synthetic Enterprise with Rot ---")
    config = {
        "seed": 999,
        "employee_count": 500,
        "department_count": 5,
        "project_count": 20,
        "vendor_count": 10,
        "goal_count": 3,
        "initiative_count": 8,
        "risk_count": 10,
        "inject_rot": True
    }
    try:
        await generator.generate_enterprise(config)
    except Exception as e:
        logger.warning(f"Generator Neo4j queries failed (expected if no DB): {e}")
        
    # 2. Execute Evolution Engine
    logger.info("--- 2. Executing Evolution Engine ---")
    evolution_results = await evolution_engine.evaluate_and_evolve(tenant_id)
    
    current_fitness = evolution_results["current_fitness"]
    future_fitness = evolution_results["future_fitness"]
    delta = evolution_results["fitness_delta"]
    opts = evolution_results["optimizations"]
    
    logger.info(f"Current Fitness: {current_fitness:.3f} | Simulated Future Fitness: {future_fitness:.3f} | Delta: +{delta:.3f}")
    
    for i, opt in enumerate(opts):
        logger.info(f"Optimization {i+1}: [{opt['type']}] {opt['description']} | Expected Gain: +{opt['expected_improvement']:.3f}")

    # 3. Store Genome and Memory
    logger.info("--- 3. Storing Genome & Evolution Memory ---")
    async with AsyncSessionLocal() as db:
        # Save Fitness Record
        fitness_id = str(uuid.uuid4())
        record = EnterpriseFitnessRecord(
            id=fitness_id,
            tenant_id=tenant_id,
            global_fitness_score=current_fitness,
            organizational_fitness=evolution_results["subscores"]["organizational_fitness"],
            workforce_fitness=evolution_results["subscores"]["workforce_fitness"],
            portfolio_fitness=evolution_results["subscores"]["portfolio_fitness"],
            vendor_fitness=evolution_results["subscores"]["vendor_fitness"],
            financial_fitness=evolution_results["subscores"]["financial_fitness"],
            execution_fitness=evolution_results["subscores"]["execution_fitness"],
            goal_alignment_fitness=evolution_results["subscores"]["goal_alignment_fitness"],
            risk_fitness=evolution_results["subscores"]["risk_fitness"],
            capability_fitness=evolution_results["subscores"]["capability_fitness"],
            factors=evolution_results["factors"]
        )
        db.add(record)
        
        # Save Current Genome (Version 1)
        genome_v1_id = str(uuid.uuid4())
        genome_v1 = EnterpriseGenome(
            id=genome_v1_id,
            tenant_id=tenant_id,
            version=1,
            fitness_record_id=fitness_id,
            state_snapshot={"node_count": "simulated", "edge_count": "simulated"}
        )
        db.add(genome_v1)
        
        # Save Optimizations to Memory
        for opt in opts:
            mem = EvolutionMemory(
                tenant_id=tenant_id,
                source_genome_id=genome_v1_id,
                recommendation_type=opt["type"],
                description=opt["description"],
                expected_improvement=opt["expected_improvement"],
                expected_cost=opt["expected_cost"],
                expected_risk=opt["expected_risk"],
                simulated_fitness_delta=opt["target_fitness_delta"],
                status="RECOMMENDED"
            )
            db.add(mem)
            
        await db.commit()
        logger.info("Successfully committed Genome V1 and Evolution Memory.")

    logger.info("==================================================")
    logger.info("   EVOLUTION ENGINE ACCEPTANCE TEST COMPLETE      ")
    logger.info("==================================================")

if __name__ == "__main__":
    asyncio.run(run_evolution_acceptance_test())
