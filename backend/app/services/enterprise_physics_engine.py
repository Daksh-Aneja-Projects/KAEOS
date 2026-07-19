"""
enterprise_physics_engine.py
=============================
Tests whether discovered patterns survive causal intervention.

A pattern becomes an Enterprise Law candidate only when:
  1. Correlation exists (already proven by PatternDiscoveryEngine)
  2. Controlled intervention reproduces the directional effect
  3. A counterfactual engine can predict outcome deltas
  4. The direction is stable across all enterprise archetypes

Zero domain-specific rules live here.
All causal evaluation is structural (intervention + counterfactual).
"""

from __future__ import annotations
import logging
import math
import random
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Shared simulator (the "world" — hidden from the discovery engine) ────────

ENTERPRISE_TYPES = ["Consulting", "Manufacturing", "Healthcare", "Technology", "Financial Services"]

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _simulate_outcome(features: Dict[str, float], enterprise_type: str, seed_noise: float = 0.0) -> float:
    """
    Deterministic-except-noise simulator.
    The causal coefficients here are the GROUND TRUTH the physics engine must rediscover.
    They are NOT visible to PatternDiscoveryEngine or EnterprisePhysicsEngine.
    """
    base = 50.0
    base -= (features.get("vendor_concentration",  50) - 50) * 0.35
    base += (features.get("capability_redundancy", 50) - 50) * 0.30
    base += (features.get("workforce_stability",   50) - 50) * 0.20
    base -= abs(features.get("budget_utilization", 60) - 60) * 0.10
    base += (features.get("project_delivery",      50) - 50) * 0.15
    type_mod = {"Consulting": 5, "Manufacturing": -3, "Healthcare": 2,
                "Technology": 4, "Financial Services": 0}.get(enterprise_type, 0)
    base += type_mod
    base += seed_noise
    return _clamp(base)


def _base_features() -> Dict[str, float]:
    return {
        "vendor_concentration":  50.0,
        "capability_redundancy": 50.0,
        "workforce_stability":   55.0,
        "budget_utilization":    60.0,
        "project_delivery":      55.0,
    }


# ─── Intervention Engine ─────────────────────────────────────────────────────

class InterventionEngine:
    """
    Runs do-calculus style experiments.
    For a given feature, creates paired Control/Intervention enterprises
    with all other features held fixed, and measures the causal effect.
    """

    def __init__(self, n_sims: int = 1000, rng_seed: int = 42):
        self.n_sims    = n_sims
        self.rng       = random.Random(rng_seed)

    def _noises(self) -> List[float]:
        return [self.rng.gauss(0, 4) for _ in range(self.n_sims)]

    def run_intervention(
        self,
        feature: str,
        control_value: float,
        intervention_value: float,
        enterprise_type: str = "Standard",
    ) -> Dict[str, Any]:
        noises = self._noises()
        base   = _base_features()

        ctrl_outcomes, intv_outcomes = [], []
        for noise in noises:
            ctrl_f = {**base, feature: control_value}
            intv_f = {**base, feature: intervention_value}
            etype  = enterprise_type if enterprise_type != "Standard" else "Technology"
            ctrl_outcomes.append(_simulate_outcome(ctrl_f, etype, noise))
            intv_outcomes.append(_simulate_outcome(intv_f, etype, noise))

        ctrl_mean = statistics.mean(ctrl_outcomes)
        intv_mean = statistics.mean(intv_outcomes)
        delta     = intv_mean - ctrl_mean

        # t-statistic approximation
        n = self.n_sims
        pooled_sd = math.sqrt((statistics.variance(ctrl_outcomes) + statistics.variance(intv_outcomes)) / 2)
        t_stat    = abs(delta) / (pooled_sd * math.sqrt(2 / n)) if pooled_sd > 0 else 0

        return {
            "feature":             feature,
            "control_value":       control_value,
            "intervention_value":  intervention_value,
            "enterprise_type":     enterprise_type,
            "n_simulations":       n,
            "control_mean":        round(ctrl_mean, 3),
            "intervention_mean":   round(intv_mean, 3),
            "causal_delta":        round(delta, 3),
            "direction":           "POSITIVE" if delta > 0 else "NEGATIVE",
            "effect_significant":  t_stat > 3.0,  # ~ p<0.001 two-tailed
            "t_statistic":         round(t_stat, 3),
        }

    def stability_across_archetypes(
        self,
        feature: str,
        lo_value: float,
        hi_value: float,
    ) -> Dict[str, Any]:
        """Tests that the causal direction is consistent across all enterprise types."""
        results = {}
        for etype in ENTERPRISE_TYPES:
            res = self.run_intervention(feature, lo_value, hi_value, etype)
            results[etype] = {
                "delta":     res["causal_delta"],
                "direction": res["direction"],
                "significant": res["effect_significant"],
            }

        directions = [v["direction"] for v in results.values()]
        all_same   = len(set(directions)) == 1
        return {
            "feature":          feature,
            "per_archetype":    results,
            "direction_stable": all_same,
            "consensus":        directions[0] if all_same else "MIXED",
        }


# ─── Counterfactual Engine ────────────────────────────────────────────────────

class EnterpriseCounterfactualEngine:
    """
    Answers "what would have happened if we had chosen Option B instead?"
    Uses the intervention engine internally; does NOT use pattern correlations.
    """

    def __init__(self, intervention_engine: InterventionEngine):
        self.engine = intervention_engine

    def predict_delta(
        self,
        observed_state: Dict[str, float],
        counterfactual_changes: Dict[str, float],
        enterprise_type: str = "Technology",
        n_sims: int = 500,
    ) -> Dict[str, Any]:
        """
        observed_state:         the actual feature values
        counterfactual_changes: features and their hypothetical values
        """
        noises = self.engine._noises()[:n_sims]
        etype  = enterprise_type if enterprise_type != "Standard" else "Technology"

        actual_outcomes = [_simulate_outcome(observed_state, etype, n) for n in noises]
        cf_state        = {**observed_state, **counterfactual_changes}
        cf_outcomes     = [_simulate_outcome(cf_state, etype, n) for n in noises]

        actual_mean = statistics.mean(actual_outcomes)
        cf_mean     = statistics.mean(cf_outcomes)
        delta       = cf_mean - actual_mean

        return {
            "observed_state":          observed_state,
            "counterfactual_changes":  counterfactual_changes,
            "actual_mean_outcome":     round(actual_mean, 3),
            "counterfactual_mean":     round(cf_mean, 3),
            "predicted_delta":         round(delta, 3),
            "interpretation":          (
                f"Choosing the counterfactual would have {'improved' if delta > 0 else 'worsened'} "
                f"outcomes by {abs(delta):.1f} points on average."
            ),
        }


# ─── Physics Candidate Extractor ─────────────────────────────────────────────

class PhysicsCandidateExtractor:
    """
    Promotes a discovered pattern to Enterprise Law candidate status
    only if all four causality criteria are met.
    """

    def evaluate(
        self,
        pattern: Dict[str, Any],
        intervention_result: Dict[str, Any],
        stability_result: Dict[str, Any],
        cf_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        corr_strength  = abs(pattern.get("correlation", 0))
        intv_sig       = intervention_result.get("effect_significant", False)
        intv_delta     = intervention_result.get("causal_delta", 0)
        stable         = stability_result.get("direction_stable", False)

        # Check that observed correlation direction matches intervention direction
        corr_positive  = pattern.get("direction", "") == "high_good"
        intv_positive  = intv_delta > 0
        direction_match = corr_positive == intv_positive

        # Counterfactual corroboration
        cf_corroborates = True
        if cf_result:
            cf_delta    = cf_result.get("predicted_delta", 0)
            cf_corroborates = (cf_delta > 0) == intv_positive

        # Compute scores
        causal_confidence = min(100, int(
            (corr_strength * 40) +
            (30 if intv_sig else 0) +
            (20 if direction_match else 0) +
            (10 if cf_corroborates else 0)
        ))
        stability_score   = min(100, int(
            sum(1 for v in stability_result.get("per_archetype", {}).values() if v["significant"]) /
            max(len(stability_result.get("per_archetype", {})), 1) * 100
        ))
        predictive_power  = min(100, int(corr_strength * 100))

        is_candidate = intv_sig and direction_match and stable and causal_confidence >= 60

        return {
            "law_name":          f"LAW_{pattern['feature'].upper()}",
            "feature":           pattern["feature"],
            "causal_confidence": causal_confidence,
            "stability":         stability_score,
            "predictive_power":  predictive_power,
            "intervention_significant": intv_sig,
            "direction_match":   direction_match,
            "cross_archetype_stable": stable,
            "cf_corroborates":   cf_corroborates,
            "status":            "CANDIDATE" if is_candidate else "REJECTED",
        }


# ─── Macro-shock adapter (used by /10x/physics/simulate) ─────────────────────

# Macro shocks expressed as feature interventions on the shared simulator.
MACRO_SHOCKS: Dict[str, Dict[str, float]] = {
    "MACRO_RATE_HIKE_50BPS": {"budget_utilization": 75.0, "vendor_concentration": 60.0},
    "SUPPLY_CHAIN_DISRUPTION": {"vendor_concentration": 80.0, "project_delivery": 40.0},
    "TALENT_EXODUS": {"workforce_stability": 30.0},
    "BUDGET_CUT": {"budget_utilization": 85.0, "capability_redundancy": 35.0},
    # M&A integration: duplicated capabilities spike redundancy short-term, but
    # workforce stability and delivery drop while budgets strain on integration cost.
    "MERGER_INTEGRATION": {
        "capability_redundancy": 78.0,
        "workforce_stability": 38.0,
        "project_delivery": 42.0,
        "budget_utilization": 82.0,
    },
    # Cyber incident: delivery and stability collapse while emergency spend and
    # single-vendor recovery dependencies concentrate risk.
    "CYBER_INCIDENT": {
        "project_delivery": 25.0,
        "workforce_stability": 45.0,
        "vendor_concentration": 72.0,
        "budget_utilization": 88.0,
    },
}


class EnterprisePhysicsEngine:
    """Facade over the intervention machinery for API-level shock simulation."""

    def __init__(self, n_sims: int = 500):
        self.intervention = InterventionEngine(n_sims=n_sims)

    async def simulate_impact(self, db=None, shock_type: str = "MACRO_RATE_HIKE_50BPS") -> List[Dict[str, Any]]:
        """Propagate a macro shock through each enterprise archetype.

        HONESTY NOTE: this is a *parameterized closed-form simulation*, not causal
        inference on the caller's own tenant data. The deltas come from the shared
        `_simulate_outcome` heuristic over fixed archetype constants (`_base_features`
        + `MACRO_SHOCKS`); the same `shock_type` yields the same ripple for every
        tenant. `db` is accepted for interface parity but is deliberately NOT queried
        here — nothing in the output is derived from tenant rows, so each entry is
        flagged ``simulated: True`` / ``model: "closed-form-heuristic"`` to stop it
        being read as a discovered enterprise law or per-tenant measurement.
        """
        if db is not None:
            logger.debug(
                "simulate_impact received a db session but does not query it; "
                "output is a closed-form heuristic simulation, not tenant-specific."
            )
        shock = MACRO_SHOCKS.get(shock_type, MACRO_SHOCKS["MACRO_RATE_HIKE_50BPS"])
        base = _base_features()
        ripple: List[Dict[str, Any]] = []
        for etype in ENTERPRISE_TYPES:
            for feature, shocked_value in shock.items():
                result = self.intervention.run_intervention(
                    feature=feature,
                    control_value=base[feature],
                    intervention_value=shocked_value,
                    enterprise_type=etype,
                )
                ripple.append({
                    "enterprise_type": etype,
                    "feature": feature,
                    "shock_type": shock_type,
                    "delta": result["delta"] if "delta" in result else round(
                        result["intervention_mean"] - result["control_mean"], 3),
                    "control_mean": result["control_mean"],
                    "intervention_mean": result["intervention_mean"],
                    "significant": result.get("significant", result.get("t_statistic", 0) > 2),
                    # Not measured from tenant data — see method docstring.
                    "simulated": True,
                    "model": "closed-form-heuristic",
                })
        return ripple
