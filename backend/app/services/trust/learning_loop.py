"""
KAEOS Enterprise Learning Loop
Priority 5 & Learning Attribution
Asynchronously evaluates predictions and decisions. Compares models, calculates accuracy, and updates trust scores.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.intelligence_metrics import PredictionRecord
from app.services.trust.confidence_calibration import ConfidenceCalibrationEngine

logger = logging.getLogger(__name__)


class EnterpriseLearningLoop:
    
    @staticmethod
    async def evaluate_temporal_outcomes(db: AsyncSession, tenant_id: str, simulated_outcomes: dict):
        """
        Executes the Temporal Validation Framework.
        Takes a dict of expected 'actuals' and evaluates PENDING records against it.
        """
        logger.info(f"LearningLoop: Running Temporal Validation for {tenant_id}")
        
        # 1. Resolve Predictions
        stmt = select(PredictionRecord).where(PredictionRecord.tenant_id == tenant_id, PredictionRecord.status == "PENDING")
        result = await db.execute(stmt)
        pending_predictions = result.scalars().all()
        
        resolved_count = 0
        model_performance = {}
        
        for pred in pending_predictions:
            # Check if this prediction's target was impacted in the temporal state
            # For proof purposes, simulated_outcomes contains {"entity_id": (bool: failed_or_not, str: actual_reason)}
            if pred.target_entity in simulated_outcomes:
                actual_state = simulated_outcomes[pred.target_entity]
                is_correct = actual_state["is_correct"]
                actual_outcome = actual_state["actual_outcome"]
                
                await ConfidenceCalibrationEngine.evaluate_prediction(db, pred.id, is_correct, actual_outcome)
                resolved_count += 1
                
                # Learning Attribution tracking
                version = pred.model_version
                if version not in model_performance:
                    model_performance[version] = {"correct": 0, "total": 0}
                model_performance[version]["total"] += 1
                if is_correct:
                    model_performance[version]["correct"] += 1
                    
        logger.info(f"LearningLoop: Resolved {resolved_count} predictions.")
        
        # 2. Output Model Drift / Learning Attribution
        for ver, stats in model_performance.items():
            acc = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
            logger.info(f"Learning Attribution: Model {ver} Accuracy: {acc*100:.1f}%")
            
        return model_performance
