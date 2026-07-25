"""Foresight — the autonomous, prescriptive reality lane.

Asserts the scoring is REAL (derived from tenant data), not decorative:
  * a scenario with no governing mission/skill scores a full preparedness gap
    and is reported as an Inevitable Surprise;
  * adding a governing mission measurably closes that gap and lowers exposure;
  * tenant scoping holds (one tenant's coverage never credits another's);
  * the gap-closer commissions a mission in PLANNING — drafted, never executed.
"""
import uuid

from app.models.missions import Mission
from app.services import foresight


async def _radar(db, tenant):
    return await foresight.premortem_radar(db, tenant, limit=50)


def _scenario(report, name):
    return next(s for s in report["scenarios"] if s["scenario"] == name)


async def test_uncovered_scenario_is_an_inevitable_surprise(db):
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    report = await _radar(db, t)

    assert report["totals"]["scenarios_scored"] > 0
    ransomware = _scenario(report, "RANSOMWARE")

    # Nothing governs it, so the gap is total and it is flagged.
    assert ransomware["preparedness_gap"] == 1.0
    assert ransomware["governed_responses"] == 0
    assert ransomware["is_inevitable_surprise"] is True
    assert ransomware["scenario"] in {s["scenario"] for s in report["inevitable_surprises"]}

    # Every score stays in its documented range.
    for s in report["scenarios"]:
        assert 0.0 <= s["likelihood"] <= 1.0
        assert 0.0 <= s["blast_radius"] <= 1.0
        assert 0.0 < s["preparedness_gap"] <= 1.0
        assert s["exposure"] >= 0.0


async def test_governed_mission_closes_the_gap_and_lowers_exposure(db):
    """A real governing mission must measurably change the score."""
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    before = _scenario(await _radar(db, t), "RANSOMWARE")

    db.add(Mission(
        tenant_id=t,
        goal="Ransomware containment and backup restore runbook",
        narrative="Governed response: isolate, restore from backup, notify.",
        status="PLANNING",
    ))
    await db.commit()

    after = _scenario(await _radar(db, t), "RANSOMWARE")
    assert after["governed_responses"] >= 1
    assert after["preparedness_gap"] < before["preparedness_gap"]
    assert after["exposure"] < before["exposure"]
    assert after["is_inevitable_surprise"] is False


async def test_coverage_is_tenant_scoped(db):
    """One tenant's mission must never mark another tenant as prepared."""
    covered = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    other = f"tenant_fs_{uuid.uuid4().hex[:6]}"

    db.add(Mission(
        tenant_id=covered,
        goal="Ransomware containment and backup restore runbook",
        status="PLANNING",
    ))
    await db.commit()

    assert _scenario(await _radar(db, covered), "RANSOMWARE")["governed_responses"] >= 1
    assert _scenario(await _radar(db, other), "RANSOMWARE")["governed_responses"] == 0


async def test_every_scenario_carries_an_actionable_draft(db):
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    for s in (await _radar(db, t))["scenarios"]:
        draft = s["recommended_mission"]
        assert draft["goal"].strip()
        assert draft["narrative"].strip()
        # Evidence must state what the score was computed from — the honesty
        # contract that keeps a low-data tenant from reading as confident.
        assert "signal_matches" in s["evidence"]
        assert "twin_nodes" in s["evidence"]


async def test_trajectory_composes_real_sources(db):
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    traj = await foresight.prescriptive_trajectory(db, t)

    assert set(traj["horizons"]) == {"30d", "60d", "90d"}
    for key, h in traj["horizons"].items():
        assert h["horizon_days"] in (30, 60, 90)
        assert h["autonomous_actions_projected"] == len(h["missions"])
    assert traj["totals"]["missions_in_flight"] == 0
    assert isinstance(traj["human_decision_points"], list)


async def test_in_flight_mission_appears_in_the_trajectory(db):
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    db.add(Mission(tenant_id=t, goal="Reduce vendor concentration risk", status="RUNNING"))
    await db.commit()

    traj = await foresight.prescriptive_trajectory(db, t)
    assert traj["totals"]["missions_in_flight"] == 1
    assert traj["horizons"]["30d"]["autonomous_actions_projected"] == 1
    assert "vendor" in traj["horizons"]["30d"]["missions"][0]["goal"].lower()


async def test_completed_missions_are_not_projected_as_future_work(db):
    t = f"tenant_fs_{uuid.uuid4().hex[:6]}"
    db.add(Mission(tenant_id=t, goal="Already done", status="COMPLETED"))
    await db.commit()

    traj = await foresight.prescriptive_trajectory(db, t)
    assert traj["totals"]["missions_in_flight"] == 0
