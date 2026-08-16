"""Lending domain pack ships the servicing/collections surface.

Parse-level verification (no DB, no LLM, no servers): lending.yaml loads
through the exact DomainPackLoader parse/validate path DomainPackEngine uses,
and the servicing_collections capability, CollectionsAgent definition, and
collection_contact process are present, structurally valid, wired to FDCPA,
and bound to the real agent class/method. Deploy-to-DB agent creation goes
through the full WorkforceGenerator pipeline (WorkforceDeployment + department
state machine + DomainPack rows), which is exercised in the e2e workforce
lane, so this test deliberately stays at parse/validate level.
"""
import os

import yaml

from app.workforce.domain_packs.loader import PACKS_DIR, DomainPackLoader


def _load_lending_pack():
    with open(os.path.join(PACKS_DIR, "lending.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_lending_pack_valid_via_engine_parse_path():
    pack = _load_lending_pack()
    assert DomainPackLoader.validate_pack(pack) is True
    # The engine's sync path loads packs via load_all_built_in_packs;
    # lending must survive that path too (not just a direct file read).
    slugs = [p["slug"] for p in DomainPackLoader.load_all_built_in_packs()]
    assert "lending" in slugs


def test_servicing_collections_capability_present_and_fdcpa_wired():
    pack = _load_lending_pack()
    cap = next(c for c in pack["capabilities"] if c["id"] == "servicing_collections")
    assert cap["agents"] == ["collections_agent"]
    assert cap["processes"] == ["collection_contact"]
    assert "FDCPA" in cap["compliance"]
    assert "FDCPA" in pack["compliance_frameworks"]


def test_collections_agent_definition_matches_real_agent_class():
    pack = _load_lending_pack()
    agent_def = next(
        a for a in pack["agent_definitions"] if a["type"] == "collections_agent"
    )
    assert agent_def["capability"] == "servicing_collections"
    assert agent_def["persona"]

    from app.lending.agents.collections_agent import CollectionsAgent
    assert agent_def["name"] == CollectionsAgent.__name__


def test_collection_contact_process_binds_to_real_agent_method():
    pack = _load_lending_pack()
    proc = next(
        p for p in pack["process_definitions"] if p["id"] == "collection_contact"
    )
    assert proc["capability"] == "servicing_collections"
    assert proc["sla_hours"] > 0
    step = proc["steps"][0]
    assert step["type"] == "AGENT_ACTION"
    assert step["agent"] == "collections_agent"

    from app.lending.agents.collections_agent import CollectionsAgent
    assert callable(getattr(CollectionsAgent, step["method"]))


def test_capability_agent_references_all_resolve():
    """Every agent a lending capability references is a declared agent type,
    so WorkforceGenerator.deploy_agents can match a definition for each."""
    pack = _load_lending_pack()
    agent_types = {a["type"] for a in pack["agent_definitions"]}
    for cap in pack["capabilities"]:
        for agent in cap.get("agents", []):
            assert agent in agent_types, (
                f"capability {cap['id']} references undeclared agent {agent}"
            )


def test_capability_process_references_all_resolve():
    """Every process a lending capability references has a process_definition;
    the generator silently skips unresolvable ids (workforce_generator.py
    _ensure_capabilities_and_processes), so a dangler means a capability
    quietly deploys without its process."""
    pack = _load_lending_pack()
    proc_ids = {p["id"] for p in pack["process_definitions"]}
    for cap in pack["capabilities"]:
        for proc in cap.get("processes", []):
            assert proc in proc_ids, (
                f"capability {cap['id']} references undefined process {proc}"
            )


def test_fair_lending_scan_process_binds_to_real_agent_method():
    pack = _load_lending_pack()
    proc = next(
        p for p in pack["process_definitions"] if p["id"] == "fair_lending_scan"
    )
    assert proc["capability"] == "fair_lending_monitoring"
    step = proc["steps"][0]
    assert step["type"] == "AGENT_ACTION"
    assert step["agent"] == "underwriter_agent"

    from app.lending.agents.underwriter_agent import UnderwriterAgent
    assert callable(getattr(UnderwriterAgent, step["method"]))
