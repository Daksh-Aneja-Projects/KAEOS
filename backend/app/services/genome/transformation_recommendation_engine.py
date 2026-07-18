import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.intelligence_metrics import EnterpriseGenome, EnterpriseFitnessRecord, EvolutionMemory
from app.services.genome.enterprise_similarity_engine import EnterpriseSimilarityEngine
from app.services.genome.similarity_explanation_engine import SimilarityExplanationEngine
from app.services.genome.recommendation_evidence_engine import RecommendationEvidenceEngine

logger = logging.getLogger(__name__)

class TransformationRecommendationEngine:
    """
    Provides context-aware transformation recommendations backed by historical peer evidence.
    """
    
    def __init__(self):
        self.similarity_engine = EnterpriseSimilarityEngine()
        self.explanation_engine = SimilarityExplanationEngine()
        self.evidence_engine = RecommendationEvidenceEngine()

    async def generate_recommendation(self, db: AsyncSession, target_genome: EnterpriseGenome, target_fitness: EnterpriseFitnessRecord) -> Dict[str, Any]:
        """
        Orchestrates similarity matching, evidence extraction, and recommendation ranking.
        """
        logger.info(f"TransformationRecommendationEngine: Evaluating context for Genome V{target_genome.version}")
        
        # 1. Build target vector
        target_vector = self.similarity_engine.extract_feature_vector(target_genome, target_fitness)
        
        # 2. Extract historical data (For a real system this would be heavily optimized/indexed, 
        # but for this acceptance test we pull all distinct historical genomes and their fitness).
        hist_genomes = await db.execute(select(EnterpriseGenome).where(EnterpriseGenome.id != target_genome.id))
        all_hist = hist_genomes.scalars().all()
        
        historical_data = []
        for hg in all_hist:
            h_fit = await db.execute(select(EnterpriseFitnessRecord).where(EnterpriseFitnessRecord.id == hg.fitness_record_id))
            h_fit_rec = h_fit.scalars().first()
            if h_fit_rec:
                vec = self.similarity_engine.extract_feature_vector(hg, h_fit_rec)
                historical_data.append({
                    "genome_id": hg.id,
                    "vector": vec,
                    "version": hg.version
                })
                
        # 3. Find Similar Genomes (Top 20 matches)
        similar_matches = self.similarity_engine.find_similar_genomes(target_vector, historical_data, top_k=20)
        
        # Filter to matches with similarity > 0.70 to ensure quality evidence
        valid_matches = [m for m in similar_matches if m["similarity_score"] >= 0.70]
        
        if not valid_matches:
            logger.warning("No highly similar historical genomes found. Cannot provide evidence-based recommendation.")
            return {"error": "Insufficient historical peer evidence."}
            
        # Explain similarity
        explanation = self.explanation_engine.explain_similarity(valid_matches)
        
        # 4. Extract Memories from these valid matches
        match_ids = [m["genome_id"] for m in valid_matches]
        
        # We need the memory transitions where the source_genome_id was one of our matches
        # Since we use sqlite mostly, we can just fetch all and filter in python for ease in testing
        mem_res = await db.execute(select(EvolutionMemory))
        all_mems = mem_res.scalars().all()
        
        relevant_memories = [m for m in all_mems if m.source_genome_id in match_ids and m.status == "IMPLEMENTED"]
        
        # Group by transformation type
        memories_by_type = {}
        for m in relevant_memories:
            t_type = m.recommendation_type
            if t_type not in memories_by_type:
                memories_by_type[t_type] = []
            
            # Attach the similarity score of its source genome so evidence engine can use it
            m_dict = {
                "id": m.id,
                "recommendation_type": m.recommendation_type,
                "success_score": m.success_score,
                "actual_fitness_delta": m.actual_fitness_delta,
                "risk_delta": m.risk_delta,
                "capability_improvement": m.capability_improvement,
                "source_genome_id": m.source_genome_id
            }
            # Find the sim score
            sim = next((match["similarity_score"] for match in valid_matches if match["genome_id"] == m.source_genome_id), 0.0)
            m_dict["similarity_score"] = sim
            
            memories_by_type[t_type].append(m_dict)
            
        # 5. Build Evidence Packages
        evidence_packages = []
        for t_type, mems in memories_by_type.items():
            pkg = self.evidence_engine.compile_evidence_package(t_type, mems, explanation)
            evidence_packages.append(pkg)
            
        # 6. Rank packages by Trust Score * Average Fitness Gain
        # We want to recommend transformations that we trust AND that perform well for this specific context
        evidence_packages.sort(key=lambda x: x["recommendation_trust_score"] * x["average_fitness_gain"], reverse=True)
        
        if not evidence_packages:
            return {"error": "Similar genomes exist, but no implemented transformations found."}
            
        top_recommendation = evidence_packages[0]
        counterfactuals = evidence_packages[1:]
        
        # 7. Formulate rationale
        shared_chars_str = ", ".join(explanation.get("shared_characteristics", []))
        rationale = f"Matched {top_recommendation['historical_sample_size']} similar enterprise genomes (Average Similarity: {explanation['average_similarity']*100:.1f}%). " \
                    f"Shared Characteristics: {shared_chars_str}. " \
                    f"Observed Outcome: {top_recommendation['observed_success_rate']*100:.1f}% success rate with an average fitness gain of +{top_recommendation['average_fitness_gain']*100:.2f}%."
                    
        return {
            "recommended_transformation": top_recommendation["transformation_type"],
            "expected_fitness_gain": top_recommendation["average_fitness_gain"],
            "expected_risk_reduction": top_recommendation["average_risk_reduction"],
            "expected_capability_improvement": top_recommendation["average_capability_improvement"],
            "recommendation_trust_score": top_recommendation["recommendation_trust_score"],
            "rationale": rationale,
            "similarity_drivers": explanation["top_drivers"],
            "historical_evidence": top_recommendation,
            "counterfactuals": counterfactuals
        }
