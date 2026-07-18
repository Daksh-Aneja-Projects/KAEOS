import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.intelligence_metrics import EvolutionMemory, TransformationLibrary

logger = logging.getLogger(__name__)

class GenomeLearningEngine:
    """
    Evaluates Genome Transitions and learns which transformations consistently improve Enterprise Fitness.
    """
    
    async def evaluate_transformation(self, db: AsyncSession, tenant_id: str, memory_id: str) -> None:
        """
        Assesses the actual outcome of an applied evolution optimization and updates the Transformation Library.
        """
        logger.info(f"GenomeLearningEngine: Evaluating Transformation for memory {memory_id}")
        
        result = await db.execute(select(EvolutionMemory).where(EvolutionMemory.id == memory_id))
        memory = result.scalars().first()
        
        if not memory or memory.status != "IMPLEMENTED":
            logger.warning("GenomeLearningEngine: Memory not found or not fully implemented.")
            return
            
        # Calculate Success Score based on Expected vs Actual
        expected = memory.expected_improvement
        actual = memory.actual_fitness_delta or 0.0
        
        # Simple heuristic: Success is meeting or exceeding expectations, or at least positive growth
        if actual > 0 and actual >= expected * 0.8:
            success = 1.0
        elif actual > 0:
            success = 0.5
        else:
            success = 0.0
            
        memory.success_score = success
        
        # Update Library
        lib_result = await db.execute(select(TransformationLibrary).where(
            TransformationLibrary.tenant_id == tenant_id,
            TransformationLibrary.transformation_type == memory.recommendation_type
        ))
        lib_entry = lib_result.scalars().first()
        
        if not lib_entry:
            lib_entry = TransformationLibrary(
                tenant_id=tenant_id,
                transformation_type=memory.recommendation_type,
                usage_count=0,
                success_rate=0.0,
                failure_rate=0.0,
                average_fitness_improvement=0.0,
                average_risk_reduction=0.0,
                average_cost=0.0
            )
            db.add(lib_entry)
            
        # Recalculate aggregates
        lib_entry.usage_count += 1
        if success >= 0.8:
            success_count = (lib_entry.success_rate * (lib_entry.usage_count - 1)) + 1
            fail_count = lib_entry.failure_rate * (lib_entry.usage_count - 1)
        elif success <= 0.2:
            success_count = lib_entry.success_rate * (lib_entry.usage_count - 1)
            fail_count = (lib_entry.failure_rate * (lib_entry.usage_count - 1)) + 1
        else:
            success_count = lib_entry.success_rate * (lib_entry.usage_count - 1)
            fail_count = lib_entry.failure_rate * (lib_entry.usage_count - 1)
            
        lib_entry.success_rate = success_count / lib_entry.usage_count
        lib_entry.failure_rate = fail_count / lib_entry.usage_count
        
        # Moving averages
        lib_entry.average_fitness_improvement = ((lib_entry.average_fitness_improvement * (lib_entry.usage_count - 1)) + actual) / lib_entry.usage_count
        
        logger.info(f"GenomeLearningEngine: Transformation {memory.recommendation_type} updated. Success Rate: {lib_entry.success_rate:.2f}")
