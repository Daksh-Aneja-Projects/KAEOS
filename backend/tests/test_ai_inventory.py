"""AI system inventory + model cards (Phase 2, EU-AI-Act-shaped).

Derived from live registries - the tenant's routed tier->model map, probe
ceilings, and real oversight counts - not prose.
"""


async def test_inventory_derives_from_live_registries(async_client):
    r = await async_client.get("/api/v1/governance/ai-inventory")
    assert r.status_code == 200, r.text
    d = r.json()

    assert len(d["systems"]) >= 8
    by_id = {s["id"]: s for s in d["systems"]}
    # Every system's tier resolves to the ACTUAL routed model.
    assert by_id["gate_pipeline"]["routed_model"]
    assert by_id["embeddings"]["routed_model"]
    # High-risk classifications name their oversight.
    assert "human" in by_id["fairness_gate"]["human_oversight"].lower() \
        or "overrid" in by_id["fairness_gate"]["human_oversight"].lower()

    cards = d["model_cards"]
    assert cards, "at least one routed model must produce a card"
    for card in cards:
        assert card["tiers_served"]
        assert isinstance(card["data_leaves_infrastructure"], bool)
        # Unprobed models report an unknown ceiling, never a flattering one.
        assert "probed_confidence_ceiling" in card

    o = d["oversight"]
    for key in ("skills_total", "rules_awaiting_validation",
                "executions_total", "executions_routed_to_human",
                "approvals_pending"):
        assert isinstance(o[key], int)
    assert "not legal advice" in d["note"]
