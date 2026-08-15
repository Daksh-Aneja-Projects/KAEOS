"""KAEOS — honest hybrid retrieval primitives.

Two building blocks shared by the vector callers:

  * ``lexical_score`` — a bounded [0,1] BM25-lite term-overlap score over a
    document's searchable text. It is NOT a cosine similarity and is never
    reported under a ``similarity`` key; callers surface it as ``lexical_score``
    with ``retrieval_mode="lexical"`` so a keyword hit is never laundered as a
    semantic match.

  * ``reciprocal_rank_fusion`` — Reciprocal Rank Fusion (Cormack et al. 2009)
    over any number of ranked id lists. The fused number is a rank-fusion score,
    surfaced as ``fused_score`` with ``retrieval_mode="hybrid"`` — again never as
    a cosine.

Honesty contract: the only value ever labelled ``similarity`` is a real cosine
from an embedding model that was NOT simulated. Everything else is labelled for
what it is.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def lexical_score(query: str, document: str) -> float:
    """BM25-lite relevance of ``document`` to ``query``, normalised to [0,1].

    Single-document BM25 (no corpus IDF, k1=1.5, b=0): a bounded, monotone
    term-frequency overlap. Enough to rank a small candidate set honestly; a
    full corpus-IDF BM25 is only worth it if lexical precision measurably
    matters.
    ponytail: no corpus IDF, add BM25Okapi over the whole skill corpus if
    lexical ranking quality is ever the bottleneck.
    """
    q = set(_tokens(query))
    if not q:
        return 0.0
    tf = Counter(_tokens(document))
    if not tf:
        return 0.0
    k1 = 1.5
    # Per-term saturation f/(f+k1) is bounded in [0,1) and monotone in tf.
    # Averaging over query terms keeps the whole score in [0,1].
    score = sum(f / (f + k1) for f in (tf.get(term, 0) for term in q) if f)
    return round(score / len(q), 4)


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[str]], k: int = 60
) -> dict[str, float]:
    """Fuse ranked id lists into ``{id: fused_score}`` via RRF.

    ``score(id) = sum over lists of 1/(k + rank)`` with rank 1-based. ``k=60`` is
    the standard constant. The score is bounded and comparable across queries.
    """
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return fused


def _demo() -> None:
    # lexical_score is bounded, monotone, and 0 on no overlap.
    assert lexical_score("reset a password", "how to reset your password") > 0.0
    assert lexical_score("reset password", "unrelated ticket text") == 0.0
    assert 0.0 <= lexical_score("pay vendor invoice", "pay the vendor invoice now") <= 1.0
    # A doc matching more query terms outranks one matching fewer.
    both = lexical_score("vendor payment", "vendor payment approved")
    one = lexical_score("vendor payment", "vendor onboarding")
    assert both > one
    # RRF rewards items ranked high across multiple lists.
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert fused["a"] > fused["c"] and fused["b"] > fused["d"]
    # top item present in both lists near the top beats a single-list item.
    assert max(fused, key=fused.get) in {"a", "b"}
    print("retrieval demo OK")


if __name__ == "__main__":
    _demo()
