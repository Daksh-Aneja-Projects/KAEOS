"""KAEOS — small RAG evaluation harness.

Deterministic, no-LLM-required checks that run in the CI unit lane and catch the
two failure modes that matter for governed retrieval:

  1. Retrieval quality — did the retriever surface the doc that actually answers
     the question?  (recall@k over a golden set)

  2. Faithfulness / hallucination — is every claim in an answer grounded in the
     retrieved context, or did the model invent facts?  (token-overlap grounding
     per sentence)

The grounding check is a deterministic lexical heuristic on purpose: it needs no
model, so it runs in CI on every commit. An optional LLM-judge (llm_judge_faithful)
uses the versioned ``rag_faithfulness_judge`` prompt and is gated to the e2e lane
where a real Ollama is reachable — it is NEVER called from the unit lane.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.services.retrieval import _tokens

_SENT = re.compile(r"[^.!?]+[.!?]?")

# Very common words carry no grounding signal; ignore them so a sentence is not
# judged "grounded" purely on shared stopwords.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on",
    "with", "as", "at", "by", "it", "this", "that", "be", "was", "were", "you",
    "your", "we", "our", "will", "can", "may", "must", "not", "no", "if",
}


@dataclass
class GoldenCase:
    question: str
    answer_doc_id: str          # the doc id that should be retrieved
    context_docs: dict[str, str]  # id -> text available to the retriever


@dataclass
class EvalReport:
    total: int
    recall_at_k_hits: int = 0
    faithful: int = 0
    hallucinated: list[str] = field(default_factory=list)

    @property
    def recall_at_k(self) -> float:
        return round(self.recall_at_k_hits / self.total, 4) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "recall_at_k": self.recall_at_k,
            "faithful": self.faithful,
            "hallucinated_count": len(self.hallucinated),
            "hallucinated": self.hallucinated,
        }


def _content_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in _STOP and len(t) > 2}


def grounding_score(sentence: str, context: str) -> float:
    """Fraction of a sentence's content tokens present in the context ([0,1])."""
    claim = _content_tokens(sentence)
    if not claim:
        return 1.0  # no checkable content (e.g. "Sure.") -> not a hallucination
    ctx = _content_tokens(context)
    return len(claim & ctx) / len(claim)


def is_faithful(answer: str, context: str, threshold: float = 0.6) -> tuple[bool, list[str]]:
    """True iff every sentence in ``answer`` is grounded in ``context``.

    Returns ``(faithful, unsupported_sentences)``. A sentence is unsupported when
    fewer than ``threshold`` of its content tokens appear in the context — the
    deterministic proxy for "made up a fact not in the retrieved evidence".
    """
    unsupported: list[str] = []
    for raw in _SENT.findall(answer):
        s = raw.strip()
        if not s:
            continue
        if grounding_score(s, context) < threshold:
            unsupported.append(s)
    return (not unsupported), unsupported


async def evaluate(
    cases: list[GoldenCase],
    retrieve: Callable[[str, dict[str, str]], Awaitable[list[str]]],
    answers: dict[str, str] | None = None,
    threshold: float = 0.6,
) -> EvalReport:
    """Run the golden set through ``retrieve`` and score recall + faithfulness.

    ``retrieve(question, context_docs)`` returns an ordered list of retrieved doc
    ids. ``answers`` maps question -> a generated answer string to faithfulness-
    check against the concatenated retrieved context (optional).
    """
    report = EvalReport(total=len(cases))
    for case in cases:
        retrieved = await retrieve(case.question, case.context_docs)
        if case.answer_doc_id in retrieved:
            report.recall_at_k_hits += 1
        if answers and case.question in answers:
            ctx = "\n".join(case.context_docs[i] for i in retrieved if i in case.context_docs)
            ok, bad = is_faithful(answers[case.question], ctx, threshold)
            if ok:
                report.faithful += 1
            else:
                report.hallucinated.extend(bad)
    return report


# Golden set shipped with the harness — extend as retrieval behaviour is pinned.
GOLDEN_SET: list[GoldenCase] = [
    GoldenCase(
        question="How many vacation days do full-time employees get?",
        answer_doc_id="pto",
        context_docs={
            "pto": "Full-time employees accrue 20 vacation days per year.",
            "401k": "The company matches 401k contributions up to 4 percent.",
            "parking": "Parking permits are issued by facilities on request.",
        },
    ),
    GoldenCase(
        question="What is the 401k match?",
        answer_doc_id="401k",
        context_docs={
            "pto": "Full-time employees accrue 20 vacation days per year.",
            "401k": "The company matches 401k contributions up to 4 percent.",
            "parking": "Parking permits are issued by facilities on request.",
        },
    ),
]


async def llm_judge_faithful(answer: str, sources: list[str] | str, router=None) -> dict:
    """LLM judge for faithfulness - e2e lane only, needs a real model.

    Renders the versioned ``rag_faithfulness_judge`` prompt (pinned v1), calls
    the router, and parses the verdict tolerantly (prompt-enforced JSON plus
    robust extraction - never format=json). Returns
    ``{"faithful": bool | None, "reason": str}``; ``faithful`` is ``None`` when
    the reply was unparseable - an honest "don't know", never a default verdict.
    """
    from app.services.json_utils import extract_json_object
    from app.services.prompts import render_prompt

    if router is None:
        from app.services.llm_router import LLMRouter
        router = LLMRouter()
    context = sources if isinstance(sources, str) else "\n".join(sources)
    prompt = render_prompt(
        "rag_faithfulness_judge", version=1, answer=answer, context=context
    )
    try:
        reply = await router.complete(prompt, model_tier="fast")
        parsed = extract_json_object(reply)
        faithful = parsed.get("faithful")
        if not isinstance(faithful, bool):
            return {"faithful": None, "reason": f"non-boolean verdict: {parsed}"}
        return {"faithful": faithful, "reason": str(parsed.get("reason", ""))}
    except Exception as exc:
        return {"faithful": None, "reason": f"judge unavailable or unparseable: {exc}"}


def _demo() -> None:
    import asyncio
    from app.services.retrieval import lexical_score

    async def lexical_retrieve(q: str, docs: dict[str, str]) -> list[str]:
        ranked = sorted(docs, key=lambda i: lexical_score(q, docs[i]), reverse=True)
        return ranked[:2]

    # Faithful answer (quotes the doc) passes; invented answer is flagged.
    good = {"What is the 401k match?": "The company matches 401k contributions up to 4 percent."}
    rep = asyncio.run(evaluate(GOLDEN_SET, lexical_retrieve, answers=good))
    assert rep.recall_at_k == 1.0, rep.to_dict()
    assert rep.faithful == 1, rep.to_dict()

    ok, bad = is_faithful("Employees receive unlimited vacation and a company car.",
                          "Full-time employees accrue 20 vacation days per year.")
    assert not ok and bad, "invented facts must be flagged as hallucination"

    ok2, _ = is_faithful("Full-time employees accrue 20 vacation days per year.",
                         "Full-time employees accrue 20 vacation days per year.")
    assert ok2, "a grounded claim must pass"
    print("rag_eval demo OK:", rep.to_dict())


if __name__ == "__main__":
    _demo()
