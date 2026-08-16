"""RAG honesty contract (workstream: rag).

Proves the retrieval layer never launders a non-semantic match as a cosine score:

  * search_skills' lexical fallback no longer fabricates ``similarity: 0.85`` for
    a substring hit; lexical results carry ``similarity: None`` +
    ``retrieval_mode="lexical"`` and a real bounded ``lexical_score``.
  * semantic_search returns nothing when embeddings are simulated (pseudo-vector
    noise is not laundered as rule recall).
  * enterprise_memory.recall and hr.retrieve_context refuse to return
    pseudo-vector matches, falling back honestly (empty / keyword).
  * route_task never auto-binds a skill on a lexical (non-cosine) hit.

All deterministic — no live Ollama, no live DB (the Skill query is stubbed to
sidestep the dual in-memory-engine split between the app engine and the test
engine).
"""

import pytest

from app.services.knowledge import PolystoreEngine
from app.services.llm_router import LLMRouter


# ── fake DB plumbing ─────────────────────────────────────────────────────────

class _FakeSkill:
    def __init__(self, skill_id, id_, domain, triggers, status="ACTIVE"):
        self.skill_id = skill_id
        self.id = id_
        self.domain = domain
        self.triggers = triggers
        self.status = status


class _FakeResult:
    def __init__(self, skills):
        self._skills = skills

    def scalars(self):
        return self

    def all(self):
        return self._skills

    def fetchall(self):
        # The vector-similarity lane (raw SQL) finds nothing in the fake DB.
        return []


class _FakeSession:
    def __init__(self, skills):
        self._skills = skills

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *_a, **_k):
        return _FakeResult(self._skills)


def _patch_skills(monkeypatch, skills):
    monkeypatch.setattr(
        "app.services.knowledge.AsyncSessionLocal", lambda: _FakeSession(skills)
    )


# ── search_skills honesty ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_skills_lexical_is_not_a_fake_cosine(monkeypatch):
    skills = [
        _FakeSkill("vendor_payment_approval", "s1", "finance",
                   [{"pattern": "approve vendor payment"}]),
        _FakeSkill("onboard_employee", "s2", "hr", ["onboard new hire"]),
    ]
    _patch_skills(monkeypatch, skills)

    eng = PolystoreEngine()
    # No usable embedding -> lexical-only path.
    async def _no_embed(_self, _text, _tenant=None):
        _self._last_query_simulated = False
        return None
    monkeypatch.setattr(PolystoreEngine, "_generate_embedding_for_text", _no_embed)

    out = await eng.search_skills("approve vendor payment", tenant_id="t1")
    assert out, "a clear lexical match must still be retrievable"
    top = out[0]
    assert top["skill_id"] == "vendor_payment_approval"
    # The core regression: never a fabricated cosine on a keyword hit.
    assert top["similarity"] is None
    assert top["retrieval_mode"] == "lexical"
    assert 0.0 < top["lexical_score"] <= 1.0
    assert top["lexical_score"] != 0.85, "lexical score must be measured, not fabricated"


@pytest.mark.asyncio
async def test_search_skills_lexical_when_embeddings_simulated(monkeypatch):
    skills = [_FakeSkill("reset_password", "s1", "it", [{"pattern": "reset password"}])]
    _patch_skills(monkeypatch, skills)

    eng = PolystoreEngine()
    # Simulated embedding returns a vector but the flag is set -> must NOT be
    # trusted as semantic.
    async def _sim_embed(_self, _text, _tenant=None):
        _self._last_query_simulated = True
        return [0.1] * 8
    monkeypatch.setattr(PolystoreEngine, "_generate_embedding_for_text", _sim_embed)

    out = await eng.search_skills("reset password", tenant_id="t1")
    assert out and out[0]["retrieval_mode"] == "lexical"
    assert out[0]["similarity"] is None


@pytest.mark.asyncio
async def test_search_skills_relabels_lexical_when_vector_lane_is_empty(monkeypatch):
    """A real query vector but zero vector hits is NOT a hybrid ranking:
    single-list RRF is just the lexical ranking and must say so."""
    skills = [
        _FakeSkill("vendor_payment_approval", "s1", "finance",
                   [{"pattern": "approve vendor payment"}]),
        _FakeSkill("vendor_onboarding", "s2", "finance",
                   [{"pattern": "vendor onboarding"}]),
    ]
    _patch_skills(monkeypatch, skills)

    eng = PolystoreEngine()
    # Real (non-simulated) query embedding -> the hybrid path is attempted.
    async def _real_embed(_self, _text, _tenant=None):
        _self._last_query_simulated = False
        return [0.1] * 8
    monkeypatch.setattr(PolystoreEngine, "_generate_embedding_for_text", _real_embed)

    out = await eng.search_skills("approve vendor payment", tenant_id="t1")
    assert out, "lexical matches must survive an empty vector lane"
    for rec in out:
        assert rec["retrieval_mode"] == "lexical", (
            "single-list RRF must not be labeled hybrid"
        )
        assert rec["similarity"] is None
        assert "fused_score" not in rec
    scores = [r["lexical_score"] for r in out]
    assert scores == sorted(scores, reverse=True), "must rank by lexical_score"


# ── skill-embedding writer guard ─────────────────────────────────────────────

class _StubEmbedRouter:
    def __init__(self, simulated):
        self.embeddings_simulated = simulated

    async def embed(self, texts):
        return [[0.1] * 8 for _ in texts]


class _CaptureSession:
    """Session factory that records merge() calls so a test can assert what
    was (or was not) persisted."""
    merged: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def merge(self, obj):
        type(self).merged.append(obj)
        return obj

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_embed_skill_never_persists_a_pseudo_vector(monkeypatch):
    from app.services.knowledge import embed_skill

    _CaptureSession.merged = []
    monkeypatch.setattr("app.services.knowledge.AsyncSessionLocal", _CaptureSession)
    skill = _FakeSkill("reset_password", "s1", "it", [{"pattern": "reset password"}])

    ok = await embed_skill(skill, "t1", router=_StubEmbedRouter(simulated=True))
    assert ok is False
    assert _CaptureSession.merged == [], "a simulated embedding must never be persisted"


@pytest.mark.asyncio
async def test_embed_skill_persists_real_vectors(monkeypatch):
    from app.services.knowledge import embed_skill

    _CaptureSession.merged = []
    monkeypatch.setattr("app.services.knowledge.AsyncSessionLocal", _CaptureSession)
    skill = _FakeSkill("reset_password", "s1", "it", [{"pattern": "reset password"}])

    ok = await embed_skill(skill, "t1", router=_StubEmbedRouter(simulated=False))
    assert ok is True
    assert len(_CaptureSession.merged) == 1
    row = _CaptureSession.merged[0]
    assert row.skill_db_id == "s1"
    assert row.tenant_id == "t1"


@pytest.mark.asyncio
async def test_embed_skill_failure_is_swallowed(monkeypatch):
    """The non-blocking contract: a failed embed never fails the skill write."""
    from app.services.knowledge import embed_skill

    class _BoomRouter:
        embeddings_simulated = False

        async def embed(self, texts):
            raise RuntimeError("provider exploded")

    skill = _FakeSkill("reset_password", "s1", "it", [{"pattern": "reset password"}])
    ok = await embed_skill(skill, "t1", router=_BoomRouter())
    assert ok is False, "an embed failure must degrade, never raise"


# ── semantic_search honesty ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_search_empty_when_simulated(monkeypatch):
    eng = PolystoreEngine()

    async def _sim_embed(_self, _text, _tenant=None):
        _self._last_query_simulated = True
        return [0.1] * 8
    monkeypatch.setattr(PolystoreEngine, "_generate_embedding_for_text", _sim_embed)

    # Must return [] without ever touching the DB (pseudo-vectors are noise).
    out = await eng.semantic_search("anything", tenant_id="t1")
    assert out == []


# ── enterprise memory honesty ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recall_returns_nothing_when_simulated(monkeypatch):
    from app.services.memory import enterprise_memory as em

    class _JunkStore:
        async def search(self, **_k):
            # Would return a "match" with a plausible cosine — must never surface.
            return [{"id": "x", "content": "junk", "metadata": {}, "similarity": 0.99}]

    monkeypatch.setattr(em, "get_vector_store", lambda: _JunkStore())

    async def _sim_router(tenant_id=None):
        r = LLMRouter()
        async def _no_provider(*_a, **_k):
            return False
        monkeypatch.setattr(r, "provider_available", _no_provider)
        return r
    monkeypatch.setattr(em, "get_tenant_router", _sim_router)

    out = await em.EnterpriseMemoryService.recall_similar_situations(
        None, "tenant_acme", "some situation"
    )
    assert out == [], "simulated embeddings must yield no semantic recall"


# ── hr knowledge base honesty ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hr_retrieve_falls_to_keyword_when_simulated(monkeypatch):
    from app.hr import knowledge_base as kb
    import app.core.polystore as polystore
    import app.services.llm_router as llm_router_mod

    class _JunkStore:
        async def search(self, **_k):
            return [{"content": "FABRICATED vector match", "similarity": 0.99}]

    # retrieve_context imports these names lazily inside the function, so patch
    # them at their source modules.
    monkeypatch.setattr(polystore, "get_vector_store", lambda: _JunkStore())

    async def _sim_router(tenant_id=None):
        r = LLMRouter()
        async def _no_provider(*_a, **_k):
            return False
        monkeypatch.setattr(r, "provider_available", _no_provider)
        return r
    monkeypatch.setattr(llm_router_mod, "get_tenant_router", _sim_router)

    # Seed a keyword-fallback corpus for this tenant.
    kb.HRKnowledgeBase._fallback_corpus["t1:handbook"] = ["Employees accrue 20 vacation days."]
    out = await kb.HRKnowledgeBase.retrieve_context("t1", "vacation days")
    assert "FABRICATED" not in out, "must not surface pseudo-vector matches"
    assert "vacation days" in out, "honest keyword fallback must still answer"


# ── route_task never auto-binds on a lexical hit ─────────────────────────────

@pytest.mark.asyncio
async def test_route_task_does_not_bind_on_lexical(monkeypatch):
    from app.agents.runtime import SkillRouter

    class _FakeVector:
        async def search_skills(self, *_a, **_k):
            # Lexical hit: similarity None. A high lexical_score must NOT auto-bind.
            return [{"skill_id": "x", "skill_db_id": "s1", "domain": "it",
                     "similarity": None, "lexical_score": 1.0, "retrieval_mode": "lexical"}]

    router = SkillRouter(registry_client=None, vector_store=_FakeVector())

    # Force the LLM classifier to abstain so only the fallback path is exercised.
    async def _abstain(*_a, **_k):
        return '{"selected_skill_id": "NONE", "confidence": 0.0}'
    monkeypatch.setattr(router.llm, "complete", _abstain)

    result = await router.route_task("do something", {"tenant_id": "t1"})
    assert result["route_type"] == "RAG_EXEC", (
        "a lexical (non-cosine) hit must never fuzzy-bind a skill"
    )
    assert result["skill"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
