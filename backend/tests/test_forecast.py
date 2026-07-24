"""v4 IP-5 — Precog forecaster.

Pure OLS-trend forecaster with residual-based confidence bands. Deterministic,
no LLM. Verifies trend direction, band ordering, clamping, gap handling, and the
honest insufficient-history path.
"""
import pytest

from app.services.forecast import linear_forecast


def test_upward_trend_projects_higher_with_bands():
    fc = linear_forecast([0.5, 0.55, 0.6, 0.65, 0.7], horizon=3)
    assert fc["insufficient"] is False
    assert fc["slope"] > 0
    assert len(fc["forecast"]) == 3
    # Monotonic upward projection.
    yhats = [p["yhat"] for p in fc["forecast"]]
    assert yhats[0] < yhats[1] < yhats[2]
    # Bands bracket the point estimate.
    for p in fc["forecast"]:
        assert p["lo"] <= p["yhat"] <= p["hi"]


def test_downward_trend_projects_lower():
    fc = linear_forecast([0.9, 0.85, 0.8, 0.75, 0.7], horizon=2)
    assert fc["slope"] < 0
    assert fc["forecast"][-1]["yhat"] < 0.7


def test_clamp01_keeps_rates_in_unit_interval():
    fc = linear_forecast([0.9, 0.93, 0.96, 0.99], horizon=10, clamp01=True)
    for p in fc["forecast"]:
        assert 0.0 <= p["lo"] <= 1.0
        assert 0.0 <= p["hi"] <= 1.0
        assert 0.0 <= p["yhat"] <= 1.0


def test_no_clamp_allows_volume_above_one():
    fc = linear_forecast([10.0, 20.0, 30.0, 40.0], horizon=2, clamp01=False)
    assert fc["forecast"][-1]["yhat"] > 40.0


def test_insufficient_history_is_honest():
    fc = linear_forecast([0.8, None, 0.82], horizon=5)
    assert fc["insufficient"] is True
    assert fc["forecast"] == []


def test_gaps_do_not_distort_trend():
    # Missing middle observations; trend still recovered from the 4 real points.
    fc = linear_forecast([0.5, None, 0.7, None, 0.8, 0.9], horizon=1)
    assert fc["insufficient"] is False
    assert fc["slope"] > 0


def test_perfect_line_has_high_r2():
    fc = linear_forecast([0.1, 0.2, 0.3, 0.4, 0.5], horizon=1, clamp01=False)
    assert fc["r2"] == pytest.approx(1.0, abs=1e-6)
