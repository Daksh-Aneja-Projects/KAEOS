"""KAEOS — statistical disparate-impact testing (the four-fifths rule).

The EEOC's Uniform Guidelines four-fifths rule: a selection rate for any
group below 80% of the most-favored group's rate is evidence of adverse
impact. This module computes it from real cohort outcome counts - actual
selection rates, not an LLM's opinion of a prompt - plus a two-proportion
z-test so a two-person "cohort" cannot trigger (or mask) a finding without
statistical support.

Input shape (aggregated counts per protected attribute):

    {"gender": {"female": {"selected": 12, "total": 40},
                "male":   {"selected": 30, "total": 50}}}

Pure stdlib, deterministic, unit-testable. The FairnessEngine uses this as
the PRIMARY check whenever cohort outcome data is available and falls back to
LLM screening (labeled as screening) when it is not.
"""
import math
from typing import Any, Dict

FOUR_FIFTHS = 0.8
SIGNIFICANCE_ALPHA = 0.05
# Below this many observations in a group, rates are noise; we still report
# the ratio but never assert a finding on it without significance.
SMALL_SAMPLE_N = 30


def _two_proportion_p(s1: int, n1: int, s2: int, n2: int) -> float:
    """Two-sided p-value for the difference of two proportions (pooled z-test).

    Stdlib-only: the normal-tail probability via math.erfc. Standard normal
    approximation - adequate for the screening decision this feeds, which is
    'is there statistical support for the disparity', not a court exhibit.
    """
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = s1 / n1, s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(p1 - p2) / se
    return math.erfc(z / math.sqrt(2))


def four_fifths_test(cohorts: Dict[str, Dict[str, dict]]) -> Dict[str, Any]:
    """Apply the four-fifths rule per protected attribute.

    Returns::

        {"passed": bool, "flagged": [attr...], "attributes": {attr: {...}},
         "method": "four_fifths_selection_rate"}

    An attribute is FLAGGED when some group's selection rate is below 4/5ths
    of the most-favored group's AND the disparity is statistically supported
    (two-proportion p < alpha). Ratios without significance are reported with
    ``advisory: true`` so thin data surfaces without hard-blocking on noise.
    """
    results: Dict[str, Any] = {}
    flagged: list[str] = []

    for attribute, groups in (cohorts or {}).items():
        rates = {}
        for group, counts in (groups or {}).items():
            total = int(counts.get("total") or 0)
            selected = int(counts.get("selected") or 0)
            if total <= 0:
                continue
            rates[group] = {"selected": min(selected, total), "total": total,
                            "rate": min(selected, total) / total}
        if len(rates) < 2:
            results[attribute] = {"status": "INSUFFICIENT_GROUPS", "groups": rates}
            continue

        best_group = max(rates, key=lambda g: rates[g]["rate"])
        best = rates[best_group]
        attr_out = {"most_favored": best_group, "groups": {}, "status": "PASSED"}
        attr_flagged = False

        for group, r in rates.items():
            ratio = (r["rate"] / best["rate"]) if best["rate"] > 0 else 1.0
            p = _two_proportion_p(r["selected"], r["total"],
                                  best["selected"], best["total"])
            below = group != best_group and ratio < FOUR_FIFTHS
            significant = p < SIGNIFICANCE_ALPHA
            small = r["total"] < SMALL_SAMPLE_N or best["total"] < SMALL_SAMPLE_N
            attr_out["groups"][group] = {
                "selection_rate": round(r["rate"], 4),
                "impact_ratio": round(ratio, 4),
                "n": r["total"],
                "p_value": round(p, 5),
                "below_four_fifths": below,
                "statistically_significant": significant,
                "small_sample": small,
                "advisory": bool(below and not significant),
            }
            if below and significant:
                attr_flagged = True

        if attr_flagged:
            attr_out["status"] = "ADVERSE_IMPACT"
            flagged.append(attribute)
        elif any(g.get("advisory") for g in attr_out["groups"].values()):
            attr_out["status"] = "ADVISORY"
        results[attribute] = attr_out

    return {
        "passed": not flagged,
        "flagged": flagged,
        "attributes": results,
        "method": "four_fifths_selection_rate",
    }
