"""
genome_compiler.py
===================
Converts Enterprise Physics Law measurements into genome traits.

Each trait is a composite derived directly from validated Physics Laws.
No hardcoded archetypes. No manually assigned clusters.

Trait Formula Sources (Physics Laws → Traits):
  LAW_CAPABILITY_REDUNDANCY + LAW_WORKFORCE_STABILITY  → Resilience
  LAW_VENDOR_CONCENTRATION (inverted)                  → Dependency_Risk (low = good)
  LAW_PROJECT_DELIVERY                                 → Execution_Fitness
  LAW_CAPABILITY_REDUNDANCY + LAW_PROJECT_DELIVERY     → Knowledge_Distribution
  LAW_VENDOR_CONCENTRATION + budget_utilization        → Operational_Fragility
  LAW_WORKFORCE_STABILITY                              → Recovery_Capacity
  all traits combined                                  → Adaptability
"""

from __future__ import annotations
import math
import random
from typing import Any, Dict, List, Optional, Tuple


# ─── Genome Compiler ─────────────────────────────────────────────────────────

class GenomeCompiler:
    """
    Compiles raw enterprise metrics into Genome Trait Scores (0-100).
    Each trait score is a weighted composite of validated Physics Law features.
    """

    TRAIT_WEIGHTS: Dict[str, Dict[str, float]] = {
        "Resilience": {
            "capability_redundancy": 0.60,
            "workforce_stability":   0.40,
        },
        "Dependency_Risk": {
            # High vendor_concentration → high risk → inverted so 100 = safe
            "vendor_concentration": -1.0,
        },
        "Execution_Fitness": {
            "project_delivery": 1.0,
        },
        "Knowledge_Distribution": {
            "capability_redundancy": 0.70,
            "project_delivery":      0.30,
        },
        "Operational_Fragility": {
            # High vendor_concentration + extreme budget_utilization = fragile
            "vendor_concentration":  0.60,
            "budget_utilization":    0.40,   # deviation from 60 is bad
        },
        "Recovery_Capacity": {
            "workforce_stability": 1.0,
        },
    }

    def compile(self, features: Dict[str, float]) -> Dict[str, float]:
        """
        Returns a Genome dict: trait_name → score (0-100).
        """
        genome: Dict[str, float] = {}

        # Resilience
        genome["Resilience"] = self._weighted(features, {
            "capability_redundancy": 0.60,
            "workforce_stability":   0.40,
        })

        # Dependency_Risk (100 = zero dependency, 0 = totally dependent)
        raw_vc = features.get("vendor_concentration", 50)
        genome["Dependency_Risk"] = max(0.0, 100.0 - raw_vc)

        # Execution_Fitness
        genome["Execution_Fitness"] = features.get("project_delivery", 50)

        # Knowledge_Distribution
        genome["Knowledge_Distribution"] = self._weighted(features, {
            "capability_redundancy": 0.70,
            "project_delivery":      0.30,
        })

        # Operational_Fragility (low = good = stable operations)
        # Use deviation from optimal budget_utilization (60)
        bu_deviation = abs(features.get("budget_utilization", 60) - 60)
        raw_fragility = (features.get("vendor_concentration", 50) * 0.60 +
                         bu_deviation * 0.40)
        genome["Operational_Fragility"] = max(0.0, min(100.0, raw_fragility))

        # Recovery_Capacity
        genome["Recovery_Capacity"] = features.get("workforce_stability", 50)

        # Adaptability: composite of all positive traits
        genome["Adaptability"] = (
            genome["Resilience"]            * 0.25 +
            genome["Dependency_Risk"]       * 0.20 +
            genome["Execution_Fitness"]     * 0.25 +
            genome["Knowledge_Distribution"]* 0.15 +
            (100 - genome["Operational_Fragility"]) * 0.10 +
            genome["Recovery_Capacity"]     * 0.05
        )

        return {k: round(v, 3) for k, v in genome.items()}

    @staticmethod
    def _weighted(features: Dict[str, float], weights: Dict[str, float]) -> float:
        total_w = sum(abs(w) for w in weights.values())
        score = sum(features.get(k, 50) * w for k, w in weights.items())
        return max(0.0, min(100.0, score / total_w))


# ─── K-Means Archetype Clustering (pure Python, no sklearn) ──────────────────

class GenomeArchetypeClusterer:
    """
    Discovers naturally occurring enterprise archetypes via K-Means.
    k is selected by minimising within-cluster sum of squares (elbow method).
    No archetypes are hardcoded.
    """

    def __init__(self, max_k: int = 8, n_init: int = 5, max_iter: int = 300):
        self.max_k    = max_k
        self.n_init   = n_init
        self.max_iter = max_iter

    def _distance(self, a: List[float], b: List[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def _kmeans(self, data: List[List[float]], k: int, seed: int) -> Tuple[List[int], List[List[float]], float]:
        rng = random.Random(seed)
        centroids = rng.sample(data, k)
        labels = [0] * len(data)

        for _ in range(self.max_iter):
            # Assign
            new_labels = [
                min(range(k), key=lambda ci: self._distance(point, centroids[ci]))
                for point in data
            ]
            if new_labels == labels:
                break
            labels = new_labels
            # Update centroids
            for ci in range(k):
                cluster_pts = [data[i] for i, l in enumerate(labels) if l == ci]
                if cluster_pts:
                    centroids[ci] = [
                        sum(pt[d] for pt in cluster_pts) / len(cluster_pts)
                        for d in range(len(data[0]))
                    ]

        wcss = sum(
            self._distance(data[i], centroids[labels[i]]) ** 2
            for i in range(len(data))
        )
        return labels, centroids, wcss

    def fit(self, genomes: List[Dict[str, float]]) -> Dict[str, Any]:
        trait_names = sorted(genomes[0].keys())
        matrix = [[g[t] for t in trait_names] for g in genomes]

        # Elbow: find optimal k
        wcss_per_k = {}
        for k in range(2, self.max_k + 1):
            best_wcss = float("inf")
            best_labels, best_centroids = None, None
            for attempt in range(self.n_init):
                labels, centroids, wcss = self._kmeans(matrix, k, seed=attempt * 31 + k)
                if wcss < best_wcss:
                    best_wcss, best_labels, best_centroids = wcss, labels, centroids
            wcss_per_k[k] = (best_wcss, best_labels, best_centroids)

        # Discover optimal k via largest drop in WCSS (elbow)
        best_k = 2
        best_drop = 0.0
        wcss_vals = [wcss_per_k[k][0] for k in range(2, self.max_k + 1)]
        for i in range(1, len(wcss_vals)):
            drop = wcss_vals[i - 1] - wcss_vals[i]
            if drop > best_drop:
                best_drop = drop
                best_k = i + 2   # index+2 because we start at k=2

        _, labels, centroids = wcss_per_k[best_k]

        # Build archetype descriptors from centroid values
        archetypes = []
        for ci, centroid in enumerate(centroids):
            trait_scores = dict(zip(trait_names, centroid))
            # Name the archetype by its strongest and weakest trait
            strongest = max(trait_scores, key=trait_scores.get)
            weakest   = min(trait_scores, key=trait_scores.get)
            archetypes.append({
                "archetype_id":    ci,
                "archetype_label": f"ARCHETYPE_{ci}",
                "strongest_trait": strongest,
                "weakest_trait":   weakest,
                "centroid":        {t: round(centroid[i], 2) for i, t in enumerate(trait_names)},
                "member_count":    labels.count(ci),
            })

        return {
            "discovered_k":  best_k,
            "wcss_by_k":     {k: round(wcss_per_k[k][0], 2) for k in range(2, self.max_k + 1)},
            "archetypes":    archetypes,
            "labels":        labels,
        }


# ─── Genome Distance Engine ───────────────────────────────────────────────────

class GenomeDistanceEngine:
    """
    Computes pairwise Euclidean distance between enterprise genomes.
    Returns nearest neighbours for a query genome.
    """

    def nearest_neighbours(
        self,
        query: Dict[str, float],
        corpus: List[Dict[str, float]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        trait_names = sorted(query.keys())
        q_vec = [query[t] for t in trait_names]

        distances = []
        for idx, genome in enumerate(corpus):
            g_vec = [genome.get(t, 50) for t in trait_names]
            dist  = math.sqrt(sum((a - b) ** 2 for a, b in zip(q_vec, g_vec)))
            distances.append((dist, idx, genome))

        distances.sort(key=lambda x: x[0])
        return [
            {"rank": i + 1, "distance": round(d, 3), "genome": g, "corpus_index": orig_idx}
            for i, (d, orig_idx, g) in enumerate(distances[:top_k])
        ]


# ─── Simple Linear Regressor (pure Python) ───────────────────────────────────

class SimpleLinearRegressor:
    """
    Ordinary least-squares via normal equations (pure Python).
    Used to compare raw-metric model vs genome-trait model.
    """

    def __init__(self):
        self.coefficients: Optional[List[float]] = None
        self.intercept: float = 0.0

    def fit(self, X: List[List[float]], y: List[float]) -> None:
        n, m = len(X), len(X[0])
        # Add bias column
        Xb = [[1.0] + row for row in X]
        # Normal equations: β = (XᵀX)⁻¹Xᵀy  — simplified via gradient descent for stability
        lr, epochs = 0.0001, 800
        beta = [0.0] * (m + 1)
        for _ in range(epochs):
            grads = [0.0] * (m + 1)
            for i in range(n):
                pred  = sum(beta[j] * Xb[i][j] for j in range(m + 1))
                err   = pred - y[i]
                for j in range(m + 1):
                    grads[j] += err * Xb[i][j]
            beta = [beta[j] - lr * grads[j] / n for j in range(m + 1)]
        self.intercept    = beta[0]
        self.coefficients = beta[1:]

    def predict(self, X: List[List[float]]) -> List[float]:
        return [
            self.intercept + sum(self.coefficients[j] * row[j] for j in range(len(row)))
            for row in X
        ]

    def mae(self, X: List[List[float]], y: List[float]) -> float:
        preds = self.predict(X)
        return sum(abs(p - a) for p, a in zip(preds, y)) / len(y)
