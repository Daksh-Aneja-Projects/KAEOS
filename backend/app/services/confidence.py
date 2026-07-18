from typing import Dict

class ConfidenceEngine:
    """L6 - Confidence, Trust & Epistemic Scoring System"""
    
    WEIGHTS = {
        "source_breadth": 0.15,
        "source_authority": 0.20,
        "temporal_freshness": 0.20,
        "outcome_validation": 0.25,
        "explicit_validation": 0.20
    }

    @staticmethod
    def calculate_scalar(vector: Dict[str, float]) -> float:
        """Weighted harmonic mean — weakest dimension constrains overall score"""
        weighted_values = []
        for dim, value in vector.items():
            if dim in ConfidenceEngine.WEIGHTS:
                weight = ConfidenceEngine.WEIGHTS[dim]
                # Avoid division by zero
                safe_value = max(0.001, value)
                weighted_values.append(weight / safe_value)
                
        if not weighted_values:
            return 0.0
            
        return 1.0 / sum(weighted_values)

    def bayesian_update(self, prior: float, evidence_type: str) -> float:
        """Bayesian update for rule confidence based on new evidence"""
        likelihood_ratio = {
            "AGENT_SUCCESS": 2.5,
            "AGENT_FAILURE": 0.3,
            "PEER_VALIDATION": 2.0,
            "DEPT_HEAD_VALIDATION": 4.0,
            "PEER_CONTRADICTION": 0.4,
            "NEW_CORROBORATING_SIGNAL": 1.8,
            "TEMPORAL_DECAY": 0.95,
        }.get(evidence_type, 1.0)
        
        # Beta-Bernoulli update
        # P(H|E) = (P(H)*P(E|H)) / (P(H)*P(E|H) + P(~H)*P(E|~H))
        posterior = (prior * likelihood_ratio) / (prior * likelihood_ratio + (1 - prior))
        return min(0.99, max(0.01, posterior))

    def evaluate_decay(self, current_confidence: float, days_since_validation: int, half_life: int) -> float:
        """Exponential decay: C(t) = C0 * 0.5^(t/T½)"""
        decay_factor = 0.5 ** (days_since_validation / max(1, half_life))
        return current_confidence * decay_factor
