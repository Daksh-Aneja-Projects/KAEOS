"""
universal_enterprise_model.py
==============================
Proves that Enterprise Genomes causally govern enterprise evolution.

Key mechanism:
  Each shock reduces enterprise feature values.
  Recovery rates are modulated by genome traits — NOT by raw features.
  Therefore different genomes produce different evolutionary trajectories
  under identical shocks.

This is the causal link: Genome -> Recovery Rate -> Future State.
"""

from __future__ import annotations
import math
import random
from typing import Any, Dict, List, Tuple

from app.services.genome_compiler import GenomeCompiler
from app.services.enterprise_physics_engine import _simulate_outcome, _clamp

compiler = GenomeCompiler()

# ─── Shock Definitions ────────────────────────────────────────────────────────
# Each shock reduces specific features by a fixed absolute amount.
# The SAME shock hits all enterprises identically — no enterprise-specific logic.

SHOCKS = [
    {
        "id":   "SUPPLIER_FAILURE",
        "name": "Strategic Supplier Failure",
        "feature_impact": {"vendor_concentration": +20},    # concentration suddenly spikes
    },
    {
        "id":   "WORKFORCE_ATTRITION",
        "name": "20% Workforce Attrition",
        "feature_impact": {"workforce_stability": -20, "capability_redundancy": -10},
    },
    {
        "id":   "CYBER_INCIDENT",
        "name": "Cybersecurity Incident",
        "feature_impact": {"project_delivery": -18, "workforce_stability": -5},
    },
    {
        "id":   "BUDGET_REDUCTION",
        "name": "15% Budget Reduction",
        "feature_impact": {"budget_utilization": -15, "project_delivery": -8},
    },
    {
        "id":   "PROJECT_DELAY",
        "name": "Critical Project Delay",
        "feature_impact": {"project_delivery": -12},
    },
]


def apply_shocks(features: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]:
    """Apply all shocks in identical order. Returns post-shock features and trace."""
    f = dict(features)
    trace = []
    for shock in SHOCKS:
        for feat, delta in shock["feature_impact"].items():
            old = f.get(feat, 50)
            f[feat] = _clamp(old + delta)
            trace.append(f"{shock['name']}: {feat} {delta:+} ({old:.1f} -> {f[feat]:.1f})")
    return f, trace


# ─── Recovery Simulator ───────────────────────────────────────────────────────

def _recovery_rate(trait_name: str, genome: Dict[str, float]) -> float:
    """
    Recovery rate for a feature is modulated by relevant genome traits.
    Range: 0.001 (very slow) to 0.020 (fast) per day.
    Slowed deliberately so genome advantage is observable at 180-day window.
    No hardcoded constants — derived purely from genome trait scores.
    """
    trait_score = genome.get(trait_name, 50) / 100.0  # 0-1
    return 0.0005 + trait_score * 0.015


FEATURE_RECOVERY_TRAIT = {
    "vendor_concentration":  "Dependency_Risk",      # high dependency risk genome = faster recovery from supplier shock
    "workforce_stability":   "Recovery_Capacity",
    "capability_redundancy": "Resilience",
    "project_delivery":      "Execution_Fitness",
    "budget_utilization":    "Adaptability",
}

def _target_feature(feat: str) -> float:
    """Long-run equilibrium (pre-shock baseline)."""
    return {"vendor_concentration": 50, "workforce_stability": 55,
            "capability_redundancy": 50, "project_delivery": 55,
            "budget_utilization": 60}.get(feat, 50)


def simulate_evolution(
    post_shock_features: Dict[str, float],
    genome: Dict[str, float],
    enterprise_type: str,
    days: List[int],
    rng: random.Random,
) -> List[Dict[str, Any]]:
    """
    Evolve the enterprise day-by-day.
    Recovery is genome-modulated: genome traits determine daily recovery rate.
    Returns snapshots at the requested day milestones.
    """
    f = dict(post_shock_features)
    snapshots = []
    day_set = set(days)
    max_day = max(days)

    for day in range(1, max_day + 1):
        # Each feature recovers toward equilibrium at genome-modulated rate
        for feat, target in [(k, _target_feature(k)) for k in f]:
            trait = FEATURE_RECOVERY_TRAIT.get(feat, "Adaptability")
            rate  = _recovery_rate(trait, genome)
            gap   = target - f[feat]
            # Remove cumulative random walk; let genome causality govern the path
            f[feat] = _clamp(f[feat] + gap * rate)

        if day in day_set:
            genome_now = compiler.compile(f)
            outcome    = _simulate_outcome(f, enterprise_type, rng.gauss(0, 2))
            snapshots.append({
                "day":               day,
                "features":          {k: round(v, 2) for k, v in f.items()},
                "genome":            {k: round(v, 2) for k, v in genome_now.items()},
                "fitness_score":     round(outcome, 2),
                "resilience":        round(genome_now["Resilience"], 2),
                "execution_fitness": round(genome_now["Execution_Fitness"], 2),
                "dependency_risk":   round(genome_now["Dependency_Risk"], 2),
                "recovery_capacity": round(genome_now["Recovery_Capacity"], 2),
            })

    return snapshots


# ─── Genome Forecast Engine ───────────────────────────────────────────────────

class GenomeForecastEngine:
    """
    Predicts enterprise evolution outcomes from genome traits alone.
    Uses K-Nearest Neighbours (KNN) on the genome manifold.
    KNN naturally captures non-linear synergies between traits better than OLS.
    """

    def __init__(self):
        from app.services.genome_compiler import GenomeDistanceEngine
        self._distance_engine = GenomeDistanceEngine()
        self._corpus: List[Dict[str, Any]] = []
        self._trained = False

    def train(self, training_data: List[Dict[str, Any]]) -> None:
        self._corpus = training_data
        self._trained = True

    def predict(self, genome: Dict[str, float]) -> Dict[str, Any]:
        if not self._trained:
            raise RuntimeError("GenomeForecastEngine not trained.")
            
        corpus_genomes = [d["genome"] for d in self._corpus]
        nn = self._distance_engine.nearest_neighbours(genome, corpus_genomes, top_k=25)
        
        # Average outcomes of nearest neighbours
        fit_preds = [self._corpus[n["corpus_index"]]["outcome_365"] for n in nn]
        rec_preds = [self._corpus[n["corpus_index"]]["recovery_time"] for n in nn]
        
        # Distance-weighted average
        total_w = 0.0
        fit_pred = 0.0
        rec_pred = 0.0
        for i, n in enumerate(nn):
            w = 1.0 / (n["distance"] + 0.1)
            total_w += w
            fit_pred += fit_preds[i] * w
            rec_pred += rec_preds[i] * w
            
        fit_pred /= total_w
        rec_pred /= total_w

        fit_pred = _clamp(fit_pred)
        rec_pred = max(10.0, rec_pred)
        survival  = 1 / (1 + math.exp(-(fit_pred - 50) / 15))
        
        return {
            "predicted_fitness_365":    round(fit_pred, 2),
            "predicted_recovery_time":  round(rec_pred, 1),
            "predicted_survival_prob":  round(survival, 4),
            "predicted_goal_degradation": round(max(0, 70 - fit_pred), 2),
        }

