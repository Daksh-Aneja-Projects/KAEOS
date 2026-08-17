"""DEPARTMENT-CAPABILITY-CONTRACT conformance gate (§06).

Invariant: **declared == enforceable by construction.** Every compliance
framework a seeded department DECLARES it enforces (``Department.compliance_frameworks``,
the single source in ``seed_departments()``) must resolve to a REGISTERED
deterministic checker in ``app.compliance.registry``. A declared control that
maps to NO checker is a dead control - it reads as "enforced" in the UI/story
but silently never runs. This is the exact class of the dead ``SLA`` tag bug.

If this gate fails, either register the checker or stop declaring the tag.
"""
from datetime import datetime, timezone

import app.core.seed as seed
from app.compliance.registry import get


def _seeded_departments():
    # NOW is a module global set only inside the async seed_database(); the
    # pure builder needs it populated to construct the Department rows.
    seed.NOW = datetime.now(timezone.utc)
    return seed.seed_departments()


def _declared_tags():
    """(department slug, declared framework tag) for every seeded department."""
    return [(d.slug, tag)
            for d in _seeded_departments()
            for tag in (d.compliance_frameworks or [])]


def test_seed_departments_is_populated():
    """Guard the source: the builder silently returned [] for its whole life."""
    depts = _seeded_departments()
    assert depts, "seed_departments() returned no departments"


def test_every_declared_compliance_tag_has_a_registered_checker():
    """The contract: no department may declare a control the registry can't run."""
    dead = [(slug, tag) for slug, tag in _declared_tags() if get(tag) is None]
    assert not dead, (
        "Declared compliance tags with NO backing checker (dead controls - they "
        "never run yet the department claims to enforce them): "
        + ", ".join(f"{slug}:{tag}" for slug, tag in dead)
        + ". Register a checker in app/compliance/checkers/ or drop the tag."
    )


def test_detection_catches_a_bogus_tag():
    """Prove the gate has teeth: a fabricated tag must resolve to no checker,
    so pointing a department at it above would trip the contract test."""
    assert get("THIS_TAG_HAS_NO_CHECKER") is None
