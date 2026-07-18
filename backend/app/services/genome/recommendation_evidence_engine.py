import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class RecommendationEvidenceEngine:
    """
    Compiles historical evidence packages and calculates Recommendation Trust Score.
    """
    
    def compile_evidence_package(self, recommendation_type: str, relevant_memories: List[Dict[str, Any]], explanation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates an Evidence Package for a specific transformation based on memories originating from similar genomes.
        """
        sample_size = len(relevant_memories)
        
        if sample_size == 0:
            return {
                "transformation_type": recommendation_type,
                "historical_sample_size": 0,
                "average_similarity": explanation.get("average_similarity", 0.0),
                "observed_success_rate": 0.0,
                "observed_failure_rate": 0.0,
                "average_fitness_gain": 0.0,
                "average_risk_reduction": 0.0,
                "average_capability_improvement": 0.0,
                "historical_cases": [],
                "recommendation_trust_score": 0.0
            }
            
        successes = 0
        total_fitness_gain = 0.0
        total_risk_reduction = 0.0
        total_cap_improvement = 0.0
        
        historical_cases = []
        
        for mem in relevant_memories:
            success_score = mem.get("success_score", 0.0)
            if success_score >= 0.8:
                successes += 1
                
            fit_delta = mem.get("actual_fitness_delta", 0.0)
            risk_delta = mem.get("risk_delta", 0.0)
            cap_delta = mem.get("capability_improvement", 0.0)
            
            total_fitness_gain += fit_delta
            total_risk_reduction += risk_delta
            total_cap_improvement += cap_delta
            
            # Format historical case
            historical_cases.append({
                "memory_id": mem.get("id"),
                "similarity": mem.get("similarity_score", 0.0),
                "transformation_applied": mem.get("recommendation_type"),
                "observed_result": {
                    "fitness_delta": fit_delta,
                    "risk_delta": risk_delta,
                    "capability_delta": cap_delta
                }
            })
            
        # Sort historical cases by similarity
        historical_cases.sort(key=lambda x: x["similarity"], reverse=True)
        
        success_rate = successes / sample_size
        
        # Calculate Trust Score
        # Combines Sample Size (capped at 20), Similarity Strength, and Outcome Consistency (Success Rate)
        sample_weight = min(sample_size / 20.0, 1.0)
        sim_strength = explanation.get("average_similarity", 0.0)
        
        # If success_rate is high (e.g. 0.9), it's highly consistent. 
        # If it's low (e.g. 0.1), it's also highly consistent (consistently bad).
        # We only trust the recommendation to *do* the transformation if success rate is high.
        trust_score = (sample_weight * 0.3) + (sim_strength * 0.4) + (success_rate * 0.3)
        
        return {
            "transformation_type": recommendation_type,
            "historical_sample_size": sample_size,
            "average_similarity": sim_strength,
            "observed_success_rate": success_rate,
            "observed_failure_rate": 1.0 - success_rate,
            "average_fitness_gain": total_fitness_gain / sample_size,
            "average_risk_reduction": total_risk_reduction / sample_size,
            "average_capability_improvement": total_cap_improvement / sample_size,
            "historical_cases": historical_cases[:5], # Return top 5 best matching cases
            "recommendation_trust_score": trust_score
        }
