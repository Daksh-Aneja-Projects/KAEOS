"""
KAEOS — Domain Analytics Payload Contract

Every department's ``<domain>_analytics(db, tenant_id, charts=...)`` service
returns the same four-key payload, which the frontend DomainAnalytics component
and /org/pulse both read:

    {"domain": str, "kpis": [...], "charts": [...], "insights": [...]}

Until now that contract lived only in prose, repeated across ten docstrings,
with nothing checking it. These TypedDicts are that contract in a form a type
checker can see.

TYPE-LEVEL ONLY. Nothing here runs: a DomainAnalytics *is* a plain dict at
runtime, in the same key order the service wrote it. No validation, no
coercion, no defaults, no reordering — the JSON on the wire is unchanged.

The item lists stay ``list[dict]`` on purpose: every service builds them from
local aggregates whose inferred types are invariant-incompatible with a
narrower element type, so tightening them would buy nothing but ten
``# type: ignore``s. The per-item shapes are documented below instead.
"""
from __future__ import annotations

from typing import TypedDict


class DomainAnalytics(TypedDict):
    """The shape all ten department analytics services return.

    ``kpis``     — {"key": str, "label": str, "value": float | int | None,
                    "format": "number" | "currency" | "percent" | "hours", ...}
                   plus an optional "note" when value is None (the honesty
                   contract: an unmeasurable metric is null-with-a-reason,
                   never a fabricated 0).
                   REVIEW: lending alone emits format "int"/"ratio" instead of
                   "number"/"percent", and attaches "note" even when the value
                   is not None. Preserved as-is: the frontend formats off these
                   strings, so normalising them is a UI behaviour change.
    ``charts``   — {"key": str, "title": str, "type": "bar" | "donut" |
                   "funnel", "items": [{"label": str, "value": float | int}]}.
                   Empty list when the caller passed charts=False.
    ``insights`` — {"severity": "info" | "warning" | "critical",
                    "message": str}; /org/pulse scores health off severity and
                   drops "info" from the cross-domain feed.
    """
    domain: str
    kpis: list[dict]
    charts: list[dict]
    insights: list[dict]
