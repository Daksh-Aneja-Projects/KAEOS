"""Precog — a small, honest forecaster over KAEOS's real time-series.

No LLM, no black box: an ordinary-least-squares linear trend with a residual-based
prediction interval. It forecasts the north-star (safe-autonomy-rate) and volume N
periods out with confidence bands, from the real daily series. When history is too
short to fit a trend, it says so rather than inventing a curve.
"""
from __future__ import annotations

import math
from typing import Optional


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Slope + intercept via least squares. Assumes len(xs) == len(ys) >= 2."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    return slope, intercept


def linear_forecast(
    values: list[Optional[float]],
    horizon: int = 14,
    *,
    clamp01: bool = True,
    min_points: int = 4,
) -> dict:
    """Forecast `horizon` steps beyond a series of observed values.

    `values` may contain None (missing observations) — those are dropped for the
    fit but the fit is indexed by the ORIGINAL position so gaps do not distort the
    trend. Returns history (index-aligned), a forecast with 95% bands, the slope,
    and R². `insufficient` is True when fewer than `min_points` real observations
    exist to fit a trend.
    """
    obs = [(i, float(v)) for i, v in enumerate(values) if v is not None]
    if len(obs) < min_points:
        return {"insufficient": True, "reason": f"need >= {min_points} observations, have {len(obs)}",
                "history": [{"t": i, "y": (None if v is None else round(float(v), 4))} for i, v in enumerate(values)],
                "forecast": [], "slope": None, "r2": None, "horizon": horizon}

    xs = [float(i) for i, _ in obs]
    ys = [v for _, v in obs]
    slope, intercept = _ols(xs, ys)

    # Residuals -> prediction interval.
    resid = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    n = len(ys)
    dof = max(1, n - 2)
    s_err = math.sqrt(sum(r * r for r in resid) / dof)
    mx = sum(xs) / n
    sxx = sum((x - mx) ** 2 for x in xs) or 1.0

    # R² (goodness of fit).
    my = sum(ys) / n
    ss_tot = sum((y - my) ** 2 for y in ys) or 1.0
    ss_res = sum(r * r for r in resid)
    r2 = max(0.0, 1.0 - ss_res / ss_tot)

    def _clamp(v: float) -> float:
        return min(1.0, max(0.0, v)) if clamp01 else v

    last_x = int(xs[-1])
    forecast = []
    for h in range(1, horizon + 1):
        x = last_x + h
        yhat = slope * x + intercept
        # 95% prediction interval for a new observation at x.
        se = s_err * math.sqrt(1.0 + 1.0 / n + (x - mx) ** 2 / sxx)
        margin = 1.96 * se
        forecast.append({
            "t": x,
            "yhat": round(_clamp(yhat), 4),
            "lo": round(_clamp(yhat - margin), 4),
            "hi": round(_clamp(yhat + margin), 4),
        })

    return {
        "insufficient": False,
        "history": [{"t": i, "y": (None if v is None else round(float(v), 4))} for i, v in enumerate(values)],
        "forecast": forecast,
        "slope": round(slope, 6),
        "r2": round(r2, 4),
        "horizon": horizon,
        "note": "OLS linear trend with a 95% residual-based prediction interval.",
    }
