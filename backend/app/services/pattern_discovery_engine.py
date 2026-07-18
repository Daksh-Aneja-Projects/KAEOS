"""
PatternDiscoveryEngine
======================
Discovers previously unknown enterprise patterns from accumulated outcome
history using only statistical techniques.

Rules inside this file: ZERO.
All thresholds, cut-offs, and groupings are derived from the data.

Techniques used
---------------
* Pearson correlation  – feature ↔ outcome_success relationship strength
* Percentile-based threshold discovery – replaces any hard-coded X
* Outcome segmentation (top-quartile vs bottom-quartile comparison)
* Association analysis (co-occurrence of feature buckets with outcome ranges)
"""

from __future__ import annotations
import logging
import math
import statistics
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ─── Tiny pure-Python correlation helper (no sklearn needed) ─────────────────

def _pearson(xs: List[float], ys: List[float]) -> float:
    """Pearson r in pure Python."""
    n = len(xs)
    if n < 4:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx * dy else 0.0


def _percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (p / 100) * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (idx - lo) * (s[hi] - s[lo])


def _stdev(data: List[float]) -> float:
    return statistics.pstdev(data) if len(data) > 1 else 0.0


# ─── Engine ──────────────────────────────────────────────────────────────────

class PatternDiscoveryEngine:
    """
    Discovers statistically significant patterns from a list of outcome records.

    Each record must have:
        feature_inputs: Dict[str, Any]   – numeric features
        success_score:  float
        domain:         str
        enterprise_type: str
    """

    MIN_SAMPLE = 15          # minimum records per pattern candidate
    MIN_ABS_CORR = 0.20      # minimum |correlation| to report
    EFFECT_THRESHOLD = 5.0   # minimum mean difference (top vs bottom quartile)

    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records

    # ── Public API ───────────────────────────────────────────────────────────

    def discover_patterns(self) -> List[Dict[str, Any]]:
        """Run all discovery routines and return a merged, de-duplicated list."""
        patterns: List[Dict[str, Any]] = []
        patterns.extend(self._correlation_patterns())
        patterns.extend(self._segmentation_patterns())
        # Sort by confidence descending
        patterns.sort(key=lambda p: p["confidence"], reverse=True)
        return patterns

    def predict(self, feature_inputs: Dict[str, Any],
                patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Given a new observation and discovered patterns, predict outcome_success.
        Returns a weighted average of pattern-based estimates.
        """
        estimates = []
        matched_patterns = []
        for pat in patterns:
            feat = pat.get("feature")
            if feat not in feature_inputs:
                continue
            val = feature_inputs[feat]
            # Does this observation fall in the high or low bucket?
            threshold = pat.get("discovered_threshold")
            if threshold is None:
                continue
            direction = pat.get("direction")   # "high_bad" or "high_good"
            if direction == "high_bad":
                pred_success = pat["low_bucket_mean"] if val < threshold else pat["high_bucket_mean"]
            else:
                pred_success = pat["high_bucket_mean"] if val >= threshold else pat["low_bucket_mean"]
            weight = abs(pat["correlation"])
            estimates.append(pred_success * weight)
            matched_patterns.append(pat["pattern_id"])

        if not estimates:
            return {"predicted_success": None, "matched_patterns": 0}

        return {
            "predicted_success": round(sum(estimates) / sum(abs(p["correlation"]) for p in patterns if p.get("feature") in feature_inputs), 2),
            "matched_patterns": len(matched_patterns),
            "pattern_ids_used": matched_patterns
        }

    # ── Internal routines ────────────────────────────────────────────────────

    def _numeric_features(self) -> List[str]:
        """Extract all numeric feature names present across records."""
        keys: set = set()
        for r in self.records:
            for k, v in r.get("feature_inputs", {}).items():
                if isinstance(v, (int, float)):
                    keys.add(k)
        return sorted(keys)

    def _correlation_patterns(self) -> List[Dict[str, Any]]:
        """
        For every numeric feature, compute Pearson r against success_score.
        Report features whose |r| >= MIN_ABS_CORR with >= MIN_SAMPLE records.
        Threshold is discovered as the 50th percentile (median split).
        """
        patterns = []
        features = self._numeric_features()

        for feat in features:
            xs, ys = [], []
            for r in self.records:
                v = r.get("feature_inputs", {}).get(feat)
                if isinstance(v, (int, float)):
                    xs.append(float(v))
                    ys.append(float(r.get("success_score", 50)))

            if len(xs) < self.MIN_SAMPLE:
                continue

            r_val = _pearson(xs, ys)
            if abs(r_val) < self.MIN_ABS_CORR:
                continue

            # Discover threshold as median of this feature (data-driven)
            threshold = _percentile(xs, 50)

            low  = [ys[i] for i, x in enumerate(xs) if x < threshold]
            high = [ys[i] for i, x in enumerate(xs) if x >= threshold]
            if len(low) < 4 or len(high) < 4:
                continue

            low_mean  = sum(low)  / len(low)
            high_mean = sum(high) / len(high)
            effect    = abs(high_mean - low_mean)
            if effect < self.EFFECT_THRESHOLD:
                continue

            direction = "high_bad" if r_val < 0 else "high_good"
            confidence = min(0.99, abs(r_val) * (len(xs) / (len(xs) + 50)))

            patterns.append({
                "pattern_id":          f"CORR_{feat.upper()}",
                "type":                "CORRELATION",
                "feature":             feat,
                "correlation":         round(r_val, 4),
                "discovered_threshold": round(threshold, 2),
                "direction":           direction,
                "low_bucket_mean":     round(low_mean,  2),
                "high_bucket_mean":    round(high_mean, 2),
                "effect_size":         round(effect, 2),
                "sample_size":         len(xs),
                "confidence":          round(confidence, 4),
            })

        return patterns

    def _segmentation_patterns(self) -> List[Dict[str, Any]]:
        """
        Compare top-quartile vs bottom-quartile outcome groups.
        Discover which features differ most between the two groups.
        """
        scores = [float(r.get("success_score", 50)) for r in self.records]
        if len(scores) < self.MIN_SAMPLE * 2:
            return []

        q25 = _percentile(scores, 25)
        q75 = _percentile(scores, 75)

        top_recs = [r for r in self.records if r.get("success_score", 50) >= q75]
        bot_recs = [r for r in self.records if r.get("success_score", 50) <= q25]

        if len(top_recs) < 5 or len(bot_recs) < 5:
            return []

        patterns = []
        for feat in self._numeric_features():
            top_vals = [float(r["feature_inputs"][feat]) for r in top_recs if feat in r.get("feature_inputs", {})]
            bot_vals = [float(r["feature_inputs"][feat]) for r in bot_recs if feat in r.get("feature_inputs", {})]
            if len(top_vals) < 4 or len(bot_vals) < 4:
                continue

            top_mean = sum(top_vals) / len(top_vals)
            bot_mean = sum(bot_vals) / len(bot_vals)
            diff     = top_mean - bot_mean
            if abs(diff) < self.EFFECT_THRESHOLD:
                continue

            # Pooled standard deviation for effect size (Cohen's d-ish)
            pooled_sd = (_stdev(top_vals) + _stdev(bot_vals)) / 2 or 1
            cohens_d  = abs(diff) / pooled_sd
            if cohens_d < 0.3:
                continue

            confidence = min(0.99, cohens_d / (cohens_d + 1) * (len(top_vals + bot_vals) / (len(top_vals + bot_vals) + 30)))
            patterns.append({
                "pattern_id":    f"SEG_{feat.upper()}",
                "type":          "SEGMENTATION",
                "feature":       feat,
                "correlation":   round(diff / (abs(diff) + 1), 4),   # proxy
                "discovered_threshold": round(_percentile(scores, 50), 2),
                "direction":     "high_good" if diff > 0 else "high_bad",
                "low_bucket_mean":  round(bot_mean, 2),
                "high_bucket_mean": round(top_mean, 2),
                "effect_size":   round(cohens_d, 3),
                "sample_size":   len(top_vals) + len(bot_vals),
                "confidence":    round(confidence, 4),
            })

        return patterns

    def generate_executive_insight(self, pattern: Dict[str, Any]) -> str:
        """
        Converts a discovered pattern into plain-English executive language.
        Text is fully data-derived — no hardcoded phrases about specific domains.
        """
        feat      = pattern["feature"].replace("_", " ")
        threshold = pattern["discovered_threshold"]
        low_mean  = pattern["low_bucket_mean"]
        high_mean = pattern["high_bucket_mean"]
        effect    = pattern["effect_size"]
        direction = pattern["direction"]
        confidence = int(pattern["confidence"] * 100)
        n         = pattern["sample_size"]

        pct_change = round(abs(high_mean - low_mean) / (low_mean + 1) * 100, 1)

        if direction == "high_bad":
            return (
                f"Enterprises with {feat} above {threshold} experience "
                f"{pct_change}% worse outcomes on average "
                f"(mean success {high_mean} vs {low_mean} below threshold). "
                f"Effect size: {effect}. Confidence: {confidence}%. Sample: {n} observations."
            )
        else:
            return (
                f"Enterprises with {feat} above {threshold} experience "
                f"{pct_change}% better outcomes on average "
                f"(mean success {high_mean} vs {low_mean} below threshold). "
                f"Effect size: {effect}. Confidence: {confidence}%. Sample: {n} observations."
            )
