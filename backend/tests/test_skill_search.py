"""M5: the skill_embeddings READ path is live.

Every skill write embeds into skill_embeddings, but the sole reader
PolystoreEngine.search_skills had no non-test caller — a live write path feeding
a dead read path. GET /skills/search now wires it (honest hybrid cosine+lexical;
lexical-only under simulated embeddings, never a keyword hit dressed as cosine)."""
import pytest

from app.api.routes.skills import search_skills_semantic
from app.core.database import AsyncSessionLocal
from app.models.domain import Skill

TENANT = "tenant_m5"


@pytest.mark.asyncio
async def test_semantic_search_finds_a_relevant_skill():
    async with AsyncSessionLocal() as s:
        s.add(Skill(id="sk-m5-1", skill_id="finance_invoice_match", tenant_id=TENANT,
                    department="finance", domain="finance", status="ACTIVE",
                    confidence=0.8,
                    steps=[{"action": "match invoices to purchase orders"}]))
        s.add(Skill(id="sk-m5-2", skill_id="hr_offer_letter", tenant_id=TENANT,
                    department="hr", domain="hr", status="ACTIVE", confidence=0.8,
                    steps=[{"action": "draft an offer letter"}]))
        await s.commit()

    res = await search_skills_semantic(q="invoice matching", tenant_id=TENANT)
    assert res["count"] >= 1
    assert any("invoice" in r["skill_id"] for r in res["results"])


@pytest.mark.asyncio
async def test_empty_query_returns_no_results():
    res = await search_skills_semantic(q="   ", tenant_id=TENANT)
    assert res["count"] == 0
