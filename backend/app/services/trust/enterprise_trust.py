"""
KAEOS Enterprise Trust Model
Priority 3 & 4 of Trust Model
Calculates multidimensional trust indices (Prediction, Recommendation, Simulation, Causal, Enterprise).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.intelligence_metrics import TrustMetrics

logger = logging.getLogger(__name__)


class EnterpriseTrustModel:
    
    @staticmethod
    async def get_trust_scores(db: AsyncSession, tenant_id: str) -> dict:
        stmt = select(TrustMetrics).where(TrustMetrics.tenant_id == tenant_id)
        result = await db.execute(stmt)
        metrics = result.scalar_one_or_none()
        
        if not metrics:
            return {
                "enterprise_trust_score": 1.0,
                "prediction_trust": 1.0,
                "recommendation_trust": 1.0,
                "simulation_trust": 1.0,
                "causal_trust": 1.0,
                "brier_score_avg": 0.0,
                "total_predictions": 0,
                "learning_progress": "Baseline"
            }
            
        # Overall Enterprise Trust is a weighted average
        # Predictions and Causal paths are weighted higher for cognitive intelligence
        enterprise_trust = (
            (metrics.prediction_trust * 0.35) +
            (metrics.causal_trust * 0.35) +
            (metrics.recommendation_trust * 0.20) +
            (metrics.simulation_trust * 0.10)
        )
        
        metrics.enterprise_trust_score = enterprise_trust
        await db.commit()
        
        return {
            "enterprise_trust_score": round(enterprise_trust, 3),
            "prediction_trust": round(metrics.prediction_trust, 3),
            "recommendation_trust": round(metrics.recommendation_trust, 3),
            "simulation_trust": round(metrics.simulation_trust, 3),
            "causal_trust": round(metrics.causal_trust, 3),
            "brier_score_avg": round(metrics.brier_score_avg, 3),
            "total_predictions": metrics.total_predictions,
            "learning_progress": "Improving" if metrics.brier_score_avg < 0.2 else "Drifting"
        }
