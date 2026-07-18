import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class SimilarityExplanationEngine:
    """
    Translates raw mathematical similarity into explainable drivers and shared characteristics.
    """
    
    def explain_similarity(self, similar_genomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes a list of similar genomes (with 'similarity_drivers' attached by the SimilarityEngine)
        and computes the high-level shared characteristics.
        """
        if not similar_genomes:
            return {"average_similarity": 0.0, "drivers": {}, "shared_characteristics": []}
            
        total_sim = 0.0
        dimension_sums = {}
        count = len(similar_genomes)
        
        for g in similar_genomes:
            total_sim += g.get("similarity_score", 0.0)
            drivers = g.get("similarity_drivers", {})
            for k, v in drivers.items():
                dimension_sums[k] = dimension_sums.get(k, 0.0) + v
                
        avg_sim = total_sim / count
        avg_drivers = {k: v / count for k, v in dimension_sums.items()}
        
        # Sort drivers to find which contributed most and which reduced similarity
        sorted_drivers = sorted(avg_drivers.items(), key=lambda x: x[1], reverse=True)
        
        top_drivers = [{"dimension": d[0], "similarity": d[1]} for d in sorted_drivers if d[1] >= 0.8]
        weak_drivers = [{"dimension": d[0], "similarity": d[1]} for d in sorted_drivers if d[1] < 0.8]
        
        # Extract qualitative shared characteristics based on the original values of the top genome
        # We'll just proxy this from the highest similarity match for the explanation
        best_match = similar_genomes[0]
        shared_chars = []
        vec = best_match["vector"]
        
        if vec.get("Vendor Concentration", 0.0) > 0.7:
            shared_chars.append("Vendor Concentration > 70%")
        if vec.get("Capability Distribution", 0.0) < 0.4:
            shared_chars.append("Low Capability Fitness")
        if vec.get("Risk Profile", 0.0) < 0.5:
            shared_chars.append("Elevated Risk Profile")
        if vec.get("Goal Alignment", 0.0) > 0.8:
            shared_chars.append("High Goal Alignment")
            
        if not shared_chars:
            shared_chars.append("Balanced Core Metrics")
            
        return {
            "average_similarity": avg_sim,
            "top_drivers": top_drivers,
            "weak_drivers": weak_drivers,
            "shared_characteristics": shared_chars
        }
