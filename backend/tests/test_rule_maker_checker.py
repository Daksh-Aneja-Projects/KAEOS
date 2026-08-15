"""Maker-checker on rules (review theme E).

A rule - human- or AI-authored - lands NON-executable and starts steering
governed decisions only after a DIFFERENT authenticated identity validates it.
The regulatory engine's LLM interpretation of pasted directive text used to go
live instantly with is_executable=True; the validate endpoint used to record a
client-supplied validator string as identity.
"""
import uuid

from sqlalchemy import select

from app.models.domain import Rule


def _payload(statement="Refunds over $500 need manager approval"):
    return {
        "statement": statement,
        "domain": "support",
        "trigger_json": {"event": "refund_requested"},
        "action_json": {"action": "require_manager_approval"},
    }


async def test_new_rule_lands_non_executable(async_client, db):
    r = await async_client.post("/api/v1/rules", json=_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_executable"] is False

    row = (await db.execute(select(Rule).where(Rule.id == body["id"]))).scalar_one()
    assert row.authored_by, "the maker identity must be recorded"


async def test_validation_by_another_identity_makes_it_executable(async_client, db):
    r = await async_client.post("/api/v1/rules", json=_payload())
    rule_id = r.json()["id"]

    # DEV_MODE requests resolve to one principal; simulate a different maker
    # so the four-eyes check sees distinct identities.
    row = (await db.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    row.authored_by = "someone-else@acme"
    await db.commit()

    v = await async_client.put(f"/api/v1/rules/{rule_id}/validate", json={
        "validator_role": "dept_head", "validator_hash": "ignored-client-text",
        "new_tier": "VALIDATED_DH"})
    assert v.status_code == 200, v.text
    assert v.json()["is_executable"] is True

    db.expire_all()  # the route wrote via its own session; drop cached state
    refreshed = (await db.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    # Non-repudiation: the recorded validator is the AUTHENTICATED principal,
    # never the client-supplied string.
    assert "ignored-client-text" not in (refreshed.validated_by or [])
    assert refreshed.validated_by, "validator identity must be recorded"


async def test_maker_cannot_validate_their_own_rule(async_client, db):
    r = await async_client.post("/api/v1/rules", json=_payload())
    rule_id = r.json()["id"]
    # Same DEV_MODE principal authored it, so validating as that principal
    # must be refused.
    v = await async_client.put(f"/api/v1/rules/{rule_id}/validate", json={
        "validator_role": "dept_head", "validator_hash": "x",
        "new_tier": "VALIDATED_DH"})
    assert v.status_code == 403
    row = (await db.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    assert row.is_executable is False


async def test_regulatory_rules_land_as_draft(db, monkeypatch):
    """The LLM's interpretation of pasted regulatory text must not execute
    until a human validates it."""
    from app.services.regulatory_engine import RegulatoryEngine

    async def fake_complete(self, prompt=None, **kwargs):
        return ('{"applies": true, "statement": "Retain audit logs 7 years", '
                '"domain": "compliance", "trigger_condition": "always", '
                '"action": "enforce_retention", "confidence": 0.9}')

    from app.services.llm_router import LLMRouter
    monkeypatch.setattr(LLMRouter, "complete", fake_complete)

    from app.services.regulatory_engine import RegulatoryUpdate

    t = f"tenant_reg_{uuid.uuid4().hex[:6]}"
    await RegulatoryEngine.ingest_new_regulation(
        db,
        RegulatoryUpdate(
            framework_name="SOX_2026",
            directive_text="Sec 103: audit logs shall be retained seven years.",
            urgency="high",
        ),
        tenant_id=t,
    )

    rows = (await db.execute(select(Rule).where(Rule.tenant_id == t))).scalars().all()
    assert rows, "the directive should synthesize at least one rule"
    for row in rows:
        assert row.is_executable is False
        assert row.authored_by == "regulatory_engine"
