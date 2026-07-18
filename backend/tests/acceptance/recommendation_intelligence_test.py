"""
Acceptance Test: Recommendation Intelligence Engine
Scenario: Context-Aware Recommendation using Historical Genomes
Proves KAEOS recommends specific transformations based on multi-dimensional similarity, not just global rankings.
"""

import asyncio
import logging
import uuid
import random

from app.core.database import Base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.intelligence_metrics import EnterpriseFitnessRecord, EvolutionMemory, EnterpriseGenome
from app.services.genome.transformation_recommendation_engine import TransformationRecommendationEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

async def run_recommendation_acceptance_test():
    logger.info("==========================================================")
    logger.info("   RECOMMENDATION INTELLIGENCE ACCEPTANCE TEST STARTED    ")
    logger.info("==========================================================")
    
    # Use isolated in-memory DB for this test to ensure determinism
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    recommendation_engine = TransformationRecommendationEngine()
    
    logger.info("--- Phase 1: Seeding Contextual Historical Genomes ---")
    
    async with AsyncSessionLocal() as db:
        
        # We will create two distinct profiles:
        # Profile A: High Vendor Concentration. VENDOR_DIVERSIFICATION works brilliantly here.
        # Profile B: Low Capability Fitness. CAPABILITY_INVESTMENT works brilliantly here.
        
        for i in range(50):
            tenant_id = f"tenant_{i}"
            is_profile_a = (i % 2 == 0)
            
            gen_id = str(uuid.uuid4())
            fit_id = str(uuid.uuid4())
            
            if is_profile_a:
                # Profile A (Vendor Heavy)
                state_snapshot = {"vendor_concentration_percent": 90.0, "capability_gap_count": 0}
                fitness = EnterpriseFitnessRecord(
                    id=fit_id, tenant_id=tenant_id, global_fitness_score=0.5,
                    vendor_fitness=0.2, capability_fitness=0.9, risk_fitness=0.3,
                    organizational_fitness=0.5, workforce_fitness=0.5, portfolio_fitness=0.5,
                    financial_fitness=0.5, execution_fitness=0.5, goal_alignment_fitness=0.5, factors={}
                )
            else:
                # Profile B (Capability Starved)
                state_snapshot = {"vendor_concentration_percent": 20.0, "capability_gap_count": 18}
                fitness = EnterpriseFitnessRecord(
                    id=fit_id, tenant_id=tenant_id, global_fitness_score=0.5,
                    vendor_fitness=0.9, capability_fitness=0.1, risk_fitness=0.5,
                    organizational_fitness=0.5, workforce_fitness=0.5, portfolio_fitness=0.5,
                    financial_fitness=0.5, execution_fitness=0.5, goal_alignment_fitness=0.5, factors={}
                )
                
            db.add(fitness)
            
            genome = EnterpriseGenome(
                id=gen_id, tenant_id=tenant_id, version=1, fitness_record_id=fit_id, state_snapshot=state_snapshot
            )
            db.add(genome)
            
            # Now we add a memory of a transformation. 
            # If we apply VENDOR_DIVERSIFICATION to Profile A, it works well.
            # If we apply CAPABILITY_INVESTMENT to Profile B, it works well.
            # We'll sprinkle some counterfactuals too (doing the wrong thing).
            
            mem_id = str(uuid.uuid4())
            
            if is_profile_a:
                # 80% of the time, they did the right thing
                if random.random() < 0.8:
                    trans_type = "VENDOR_DIVERSIFICATION"
                    success = 1.0
                    actual_delta = 0.08
                else:
                    trans_type = "CAPABILITY_INVESTMENT"
                    success = 0.0 # Doesn't help if they already have capabilities
                    actual_delta = 0.01
            else:
                if random.random() < 0.8:
                    trans_type = "CAPABILITY_INVESTMENT"
                    success = 1.0
                    actual_delta = 0.09
                else:
                    trans_type = "VENDOR_DIVERSIFICATION"
                    success = 0.0
                    actual_delta = 0.01
                    
            mem = EvolutionMemory(
                id=mem_id, tenant_id=tenant_id, source_genome_id=gen_id,
                recommendation_type=trans_type, description="Test",
                expected_improvement=0.05, expected_cost=10000, expected_risk=0.1,
                simulated_fitness_delta=0.05, status="IMPLEMENTED",
                actual_fitness_delta=actual_delta, success_score=success,
                risk_delta=-0.04, capability_improvement=actual_delta if trans_type == "CAPABILITY_INVESTMENT" else 0.0
            )
            db.add(mem)
            
        await db.commit()
        
        logger.info("--- Phase 2: Generating Target Enterprise (Profile A match) ---")
        
        target_fit_id = str(uuid.uuid4())
        target_gen_id = str(uuid.uuid4())
        
        target_fitness = EnterpriseFitnessRecord(
            id=target_fit_id, tenant_id="target_tenant", global_fitness_score=0.45,
            vendor_fitness=0.25, capability_fitness=0.85, risk_fitness=0.35, # Similar to Profile A
            organizational_fitness=0.5, workforce_fitness=0.5, portfolio_fitness=0.5,
            financial_fitness=0.5, execution_fitness=0.5, goal_alignment_fitness=0.5, factors={}
        )
        db.add(target_fitness)
        
        target_genome = EnterpriseGenome(
            id=target_gen_id, tenant_id="target_tenant", version=1, fitness_record_id=target_fit_id,
            state_snapshot={"vendor_concentration_percent": 88.0, "capability_gap_count": 1}
        )
        db.add(target_genome)
        await db.commit()
        
        logger.info("--- Phase 3: Generating Evidence-Based Recommendation ---")
        
        rec = await recommendation_engine.generate_recommendation(db, target_genome, target_fitness)
        
        assert "error" not in rec, f"Recommendation failed: {rec.get('error')}"
        assert rec["recommended_transformation"] == "VENDOR_DIVERSIFICATION", f"Expected VENDOR_DIVERSIFICATION, got {rec['recommended_transformation']}"
        
        logger.info("RECOMMENDATION SUCCESS:")
        logger.info(f"Target: {rec['recommended_transformation']}")
        logger.info(f"Trust Score: {rec['recommendation_trust_score']:.2f}")
        logger.info(f"Rationale: {rec['rationale']}")
        
        # Verify Drivers
        vendor_driver = next((d for d in rec['similarity_drivers'] if d['dimension'] == "Vendor Concentration"), None)
        assert vendor_driver is not None, "Vendor Concentration should be a similarity driver"
        logger.info(f"Similarity Driver Confirmed: Vendor Concentration ({vendor_driver['similarity']:.2f})")
        
        # Verify Counterfactual
        cf = next((c for c in rec['counterfactuals'] if c['transformation_type'] == "CAPABILITY_INVESTMENT"), None)
        assert cf is not None, "Counterfactual CAPABILITY_INVESTMENT missing"
        logger.info(f"Counterfactual Evidence Confirmed: {cf['transformation_type']} ranked lower. Success Rate: {cf['observed_success_rate']:.2f}")
        
    logger.info("==========================================================")
    logger.info("   RECOMMENDATION INTELLIGENCE ACCEPTANCE TEST COMPLETE   ")
    logger.info("==========================================================")

if __name__ == "__main__":
    asyncio.run(run_recommendation_acceptance_test())
