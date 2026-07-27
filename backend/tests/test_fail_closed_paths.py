"""Regression tests for the fail-closed conversions from the swallowed-exception audit.

Three swallow sites sat on a security or gating path and failed OPEN:

* The PII log-redaction filter returned the ORIGINAL message when redaction
  raised, so a regex fault would emit exactly the text the control exists to
  scrub. It now suppresses the payload instead.
* The Autonomy Dial reverted to the platform default when its lookup threw. An
  executive who dialled a domain STRICTER than the default silently got the
  looser number during a datastore blip. It now holds the strictest threshold
  it has evidence for.
* The mission planner ignored a failed threshold lookup and planned autonomy
  against a hardcoded 0.82. It now plans a human checkpoint instead.
"""
import logging

import pytest

from app.core import logging as kaeos_logging
from app.services import autonomy_policy


# ── PII redaction filter fails closed ────────────────────────────────────

def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(name="t", level=logging.INFO, pathname=__file__,
                             lineno=1, msg=msg, args=(), exc_info=None)


def test_pii_filter_redacts_normally():
    rec = _record("user contact: alice@example.com")
    assert kaeos_logging.PIIRedactionFilter().filter(rec) is True
    assert "alice@example.com" not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()


def test_pii_filter_suppresses_payload_when_redaction_raises(monkeypatch):
    def boom(text):
        raise RuntimeError("regex engine fault")

    monkeypatch.setattr(kaeos_logging, "_redact_pii", boom)
    secret = "ssn 123-45-6789 for alice@example.com"
    rec = _record(secret)
    assert kaeos_logging.PIIRedactionFilter().filter(rec) is True
    out = rec.getMessage()
    assert secret not in out and "alice@example.com" not in out, \
        "a redaction fault must never emit the unredacted message"
    assert "suppressed" in out


def test_redact_pii_raises_rather_than_returning_unredacted(monkeypatch):
    """The inner helper must propagate, not swallow: swallowing would hand the
    caller unredacted text and defeat the filter's fail-closed branch."""
    class _Boom:
        def sub(self, *a, **k):
            raise RuntimeError("regex fault")

    monkeypatch.setattr(kaeos_logging, "_SENSITIVE_KEY_RE", _Boom())
    with pytest.raises(RuntimeError):
        kaeos_logging._redact_pii("token: abc123")


# ── Autonomy Dial holds the strictest known threshold ────────────────────

async def test_autonomy_dial_holds_stricter_cached_value_on_lookup_failure(monkeypatch):
    from app.core.config import get_settings
    default = get_settings().CONFIDENCE_AUTONOMOUS_EXEC
    stricter = 0.97
    assert stricter > default

    autonomy_policy._cache.clear()
    # Seed the cache as if a stricter dial had been read, then expire it.
    autonomy_policy._cache[("t_dial", "finance")] = (stricter, -1.0)

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("database unreachable")

        async def __aexit__(self, *a):
            return False

    import app.core.database as dbmod
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _BoomSession())

    val = await autonomy_policy.resolve_min_confidence("t_dial", "finance")
    assert val == pytest.approx(stricter), \
        "a failed dial lookup must not loosen a stricter configured threshold"
    autonomy_policy._cache.clear()


async def test_autonomy_dial_falls_back_to_default_when_nothing_known(monkeypatch):
    from app.core.config import get_settings
    default = get_settings().CONFIDENCE_AUTONOMOUS_EXEC
    autonomy_policy._cache.clear()

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("database unreachable")

        async def __aexit__(self, *a):
            return False

    import app.core.database as dbmod
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _BoomSession())

    val = await autonomy_policy.resolve_min_confidence("t_unknown", "finance")
    assert val == pytest.approx(default)
    # A failed read must not poison the cache with a guessed value.
    assert ("t_unknown", "finance") not in autonomy_policy._cache
    autonomy_policy._cache.clear()


# ── Mission planner fails closed on a failed threshold lookup ────────────

async def test_planner_adds_hitl_checkpoint_when_threshold_lookup_fails(db, monkeypatch):
    import uuid

    from app.models.domain import Skill
    from app.services.missions import planner

    t = "tenant_planner_fc"
    # A support skill (not high-consequence) whose confidence clears every
    # plausible threshold, so ONLY the failed lookup can force the checkpoint.
    db.add(Skill(id=str(uuid.uuid4()), skill_id=f"support_{uuid.uuid4().hex[:6]}",
                 tenant_id=t, department="support", domain="support",
                 status="ACTIVE", confidence=0.99))
    await db.commit()

    async def boom(tenant_id, domain):
        raise RuntimeError("autonomy policy store unreachable")

    # The planner imports the resolver inside plan_mission, so patch the source
    # module rather than a module-level name on the planner.
    monkeypatch.setattr(autonomy_policy, "resolve_min_confidence", boom)

    m = await planner.plan_mission(db, tenant_id=t, goal="update support tickets")
    from sqlalchemy import select
    from app.models.missions import MissionStep
    steps = (await db.execute(
        select(MissionStep).where(MissionStep.mission_id == m.id)
    )).scalars().all()
    assert steps, "planner produced no steps"
    assert all(s.hitl_required for s in steps), \
        "an unresolvable autonomy threshold must plan a human checkpoint"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
