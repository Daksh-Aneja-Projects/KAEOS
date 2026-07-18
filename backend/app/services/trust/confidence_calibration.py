"""
KAEOS Confidence Calibration Engine
Priority 2 of Trust Model
Tracks and evaluates the Brier Score, Calibration Error, and Confidence Drift for all intelligence outputs.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.intelligence_metrics import PredictionRecord, TrustMetrics

logger = logging.getLogger(__name__)


class ConfidenceCalibrationEngine:
    
    @staticmethod
    async def evaluate_prediction(db: AsyncSession, prediction_id: str, is_correct: bool, actual_outcome: str):
        """
        Evaluates a PENDING prediction, calculates Brier score and calibration error, and resolves it.
        """
        # Fetch prediction
        stmt = select(PredictionRecord).where(PredictionRecord.id == prediction_id)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record or record.status != "PENDING":
            logger.warning(f"CalibrationEngine: Prediction {prediction_id} not found or already resolved.")
            return

        # 1. Calculate Actual Label (1 for True, 0 for False)
        actual_label = 1.0 if is_correct else 0.0
        
        # 2. Calculate Brier Score (Confidence - Actual)^2
        # Lower Brier score is better (0.0 is perfect)
        brier_score = (record.confidence - actual_label) ** 2
        
        # 3. Calculate Calibration Error
        # Positive = Overconfident, Negative = Underconfident
        calibration_error = record.confidence - actual_label
        
        # 4. Resolve Record
        record.status = "CORRECT" if is_correct else "INCORRECT"
        record.actual_outcome = actual_outcome
        record.brier_score = brier_score
        record.calibration_error = calibration_error
        
        await db.commit()
        logger.info(f"CalibrationEngine: Resolved {prediction_id}. Correct: {is_correct}. Brier: {brier_score:.3f}, Error: {calibration_error:.3f}")
        
        # 5. Trigger Enterprise Trust update with confidence-weighted penalty
        await ConfidenceCalibrationEngine._update_enterprise_metrics(db, record.tenant_id, brier_score, calibration_error)

    @staticmethod
    async def _update_enterprise_metrics(db: AsyncSession, tenant_id: str, new_brier_score: float, calibration_error: float):
        stmt = select(TrustMetrics).where(TrustMetrics.tenant_id == tenant_id)
        result = await db.execute(stmt)
        metrics = result.scalar_one_or_none()
        
        if not metrics:
            metrics = TrustMetrics(tenant_id=tenant_id)
            db.add(metrics)
            await db.commit()
            await db.refresh(metrics)
            
        total = metrics.total_predictions
        current_avg = metrics.brier_score_avg
        
        # Running average update
        new_avg = ((current_avg * total) + new_brier_score) / (total + 1)
        metrics.brier_score_avg = new_avg
        metrics.total_predictions = total + 1
        
        # Confidence-Weighted Adaptive Trust Penalty
        # Trust is fully recoverable.
        if calibration_error > 0.8:
            # Overconfident incorrect: Severe penalty
            metrics.prediction_trust = max(0.1, metrics.prediction_trust - 0.10)
        elif calibration_error > 0.6:
            # High-confidence incorrect: Large penalty
            metrics.prediction_trust = max(0.1, metrics.prediction_trust - 0.05)
        elif calibration_error > 0.3:
            # Medium-confidence incorrect: Moderate penalty
            metrics.prediction_trust = max(0.1, metrics.prediction_trust - 0.02)
        elif calibration_error > 0:
            # Low-confidence incorrect: Small penalty
            metrics.prediction_trust = max(0.1, metrics.prediction_trust - 0.005)
        elif calibration_error <= 0:
            # Correct prediction: Recovery / Positive reinforcement
            metrics.prediction_trust = min(1.0, metrics.prediction_trust + 0.015)
            
        await db.commit()
