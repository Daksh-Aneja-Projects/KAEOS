import logging
from typing import Dict, Any, List

from app.models.intelligence_metrics import EnterpriseGenome, EnterpriseFitnessRecord

logger = logging.getLogger(__name__)

class EnterpriseSimilarityEngine:
    """
    Computes multi-dimensional similarity between enterprise states.
    """
    
    def extract_feature_vector(self, genome: EnterpriseGenome, fitness: EnterpriseFitnessRecord) -> Dict[str, float]:
        """
        Normalizes fitness and structural metrics into a vector for comparison.
        """
        state = genome.state_snapshot or {}
        
        # We assume percentages are 0-100, normalize to 0-1
        vendor_conc = state.get("vendor_concentration_percent", 0.0) / 100.0
        
        # Capability gap is an absolute number, we'll normalize arbitrarily relative to a max of 20
        cap_gap = min(state.get("capability_gap_count", 0) / 20.0, 1.0)
        
        return {
            "Vendor Concentration": vendor_conc,
            "Capability Distribution": 1.0 - cap_gap, # High gap = low capability distribution
            "Risk Profile": fitness.risk_fitness,
            "Portfolio Structure": fitness.portfolio_fitness,
            "Workforce Allocation": fitness.workforce_fitness,
            "Goal Alignment": fitness.goal_alignment_fitness
        }

    def compute_similarity(self, vector_a: Dict[str, float], vector_b: Dict[str, float]) -> Dict[str, float]:
        """
        Computes the similarity score and individual dimensional drivers between two vectors.
        Uses 1 - absolute difference as a bounded similarity measure.
        """
        dimensions = {}
        total_sim = 0.0
        count = 0
        
        for key in vector_a.keys():
            if key in vector_b:
                # 1.0 means identical, 0.0 means completely opposite (0 vs 1)
                sim = 1.0 - abs(vector_a[key] - vector_b[key])
                dimensions[key] = sim
                total_sim += sim
                count += 1
                
        overall_score = total_sim / count if count > 0 else 0.0
        
        return {
            "overall_score": overall_score,
            "dimensions": dimensions
        }

    def find_similar_genomes(self, target_vector: Dict[str, float], historical_data: List[Dict[str, Any]], top_k: int = 10) -> List[Dict[str, Any]]:
        """
        historical_data is expected to be a list of dicts: {"genome_id": str, "vector": Dict[str, float], "fitness_record": EnterpriseFitnessRecord, ...}
        """
        results = []
        for hist in historical_data:
            sim_result = self.compute_similarity(target_vector, hist["vector"])
            hist_copy = hist.copy()
            hist_copy["similarity_score"] = sim_result["overall_score"]
            hist_copy["similarity_drivers"] = sim_result["dimensions"]
            results.append(hist_copy)
            
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:top_k]
