import logging
from typing import Dict, Any

from app.models.intelligence_metrics import EnterpriseGenome, EnterpriseFitnessRecord

logger = logging.getLogger(__name__)

class GenomeComparisonEngine:
    """
    Calculates Deltas between Genome A and Genome B.
    """
    
    def compare_genomes(self, genome_a: EnterpriseGenome, fitness_a: EnterpriseFitnessRecord, 
                        genome_b: EnterpriseGenome, fitness_b: EnterpriseFitnessRecord) -> Dict[str, Any]:
        """
        Computes the structural, fitness, capability, and risk deltas between two versions.
        """
        logger.info(f"GenomeComparisonEngine: Diffing Genome V{genome_a.version} vs V{genome_b.version}")
        
        return {
            "version_transition": f"V{genome_a.version} -> V{genome_b.version}",
            "fitness_delta": fitness_b.global_fitness_score - fitness_a.global_fitness_score,
            "capability_delta": fitness_b.capability_fitness - fitness_a.capability_fitness,
            "risk_delta": fitness_b.risk_fitness - fitness_a.risk_fitness,
            "execution_delta": fitness_b.execution_fitness - fitness_a.execution_fitness,
            "workforce_delta": fitness_b.workforce_fitness - fitness_a.workforce_fitness,
            "vendor_delta": fitness_b.vendor_fitness - fitness_a.vendor_fitness,
            "portfolio_delta": fitness_b.portfolio_fitness - fitness_a.portfolio_fitness
        }
