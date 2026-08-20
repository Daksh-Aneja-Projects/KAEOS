"""KAEOS — versioned prompt registry.

Inline f-string prompts scattered through the codebase are unversioned: a
wording change silently alters model behaviour with no diff-able record and no
way to pin a caller to a known-good template. This registry keeps each prompt as
a named, versioned template. Callers pin an explicit version so a new revision is
opt-in, never a silent behaviour change.

Usage:
    from app.services.prompts import render_prompt
    prompt = render_prompt("rag_faithfulness_judge", context=..., answer=...)

Add a new revision by adding a new ``PromptTemplate`` to the version list for a
name; the latest is served by default but callers SHOULD pin (``version=``) for
governance-sensitive paths.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    template: str

    def render(self, **kwargs) -> str:
        return self.template.format(**kwargs)


# name -> list of versions (ascending). Latest is last.
PROMPTS: dict[str, list[PromptTemplate]] = {
    "rag_faithfulness_judge": [
        PromptTemplate(
            name="rag_faithfulness_judge",
            version=1,
            template=(
                "You are a strict grader. Decide if the ANSWER is fully supported "
                "by the CONTEXT. An answer is faithful only if every factual claim "
                "it makes appears in the context. If it adds any fact not present "
                "in the context, it is unfaithful.\n\n"
                "CONTEXT:\n{context}\n\n"
                "ANSWER:\n{answer}\n\n"
                'Return ONLY JSON: {{"faithful": true|false, "reason": "..."}}'
            ),
        ),
    ],
}


def get_prompt(name: str, version: int | None = None) -> PromptTemplate:
    """Return a pinned prompt template. Latest version if ``version`` is None."""
    versions = PROMPTS.get(name)
    if not versions:
        raise KeyError(f"no prompt registered under name={name!r}")
    if version is None:
        return versions[-1]
    for tmpl in versions:
        if tmpl.version == version:
            return tmpl
    raise KeyError(f"prompt {name!r} has no version {version}")


def render_prompt(name: str, version: int | None = None, **kwargs) -> str:
    """Render a registered prompt."""
    return get_prompt(name, version).render(**kwargs)


def _demo() -> None:
    p = render_prompt(
        "rag_faithfulness_judge",
        context="The invoice was approved on the 3rd.",
        answer="The invoice was approved on the 3rd.",
    )
    assert "approved on the 3rd" in p and "faithful" in p
    # pinning is explicit and stable
    assert get_prompt("rag_faithfulness_judge", 1).version == 1
    try:
        get_prompt("rag_faithfulness_judge", 99)
        raise AssertionError("expected KeyError for missing version")
    except KeyError:
        pass
    print("prompts registry demo OK")


if __name__ == "__main__":
    _demo()
