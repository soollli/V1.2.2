"""Deterministic tests for src/theory_backtests.py (four-theory backtest battery).

All synthetic data uses fixed RNG seeds; no network, no filesystem.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.theory_backtests import (
    adf_test,
    band_strategy_backtest,
    fit_garch,
    jarque_bera,
    ljung_box_test,
    theories_report,
    variance_ratio,
)


def _synth_closes(n: int = 800, m: int = 6, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.01, (n - 1, m))
    logs = np.zeros((n, m))
    for t in range(1, n):
        logs[t] = logs[t - 1] + np.log1p(rets[t - 1])
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    cols = [f"SYM{c}USDT" for c in range(m)]
    return pd.DataFrame(100.0 * np.exp(logs), index=idx, columns=cols)


# ------------------------------------------------------------------ unit tests


def test_adf_cointegrated_spread_vs_unit_root():
    rng = np.random.default_rng(11)
    trend = np.cumsum(rng.normal(0, 0.01, 800))
    a = trend + np.cumsum(rng.normal(0, 0.001, 800)) * 0.0
    # stationary component with AR(1) persistence
    s = np.zeros(800)
    for t in range(1, 800):
        s[t] = 0.95 * s[t - 1] + rng.normal(0, 0.01)
    a = trend + s
    b = trend + 0.8 * s + rng.normal(0, 0.005, 800)
    spread = a - b
    res = adf_test(spread)
    assert res["reject_5pct"] is True, res
    # a raw unit-root series must NOT be rejected
    res_u = adf_test(trend)
    assert res_u["reject_5pct"] is False, res_u


def test_ljung_box_autocorrelated_vs_white():
    rng = np.random.default_rng(5)
    n = 1200
    # returns constructed directly as AR(1) so their sample autocorr is strong
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.8 * x[t - 1] + rng.normal(0, 1.0)
    r = x / 10.0
    lb = ljung_box_test(r, [1, 3, 6, 12, 24])
    assert lb["p"] is not None and lb["p"] < 0.01, lb
    white = rng.standard_normal(n)
    lb_w = ljung_box_test(white / 100.0, [1, 3, 6, 12, 24])
    assert lb_w["p"] >= 0.05, lb_w


def test_variance_ratio_near_one_for_random_walk():
    rng = np.random.default_rng(9)
    r = rng.standard_normal(2000) / 30.0
    vr = variance_ratio(r, 5)
    assert vr["vr"] is not None and 0.75 <= vr["vr"] <= 1.25, vr
    assert vr["p"] is not None and vr["p"] >= 0.05, vr


def test_jarque_bera_normal_vs_fattails():
    rng = np.random.default_rng(13)
    normal = rng.standard_normal(2000) / 20.0
    jb_n = jarque_bera(normal)
    assert jb_n["p"] is not None and jb_n["p"] >= 0.01, jb_n
    fattail = rng.standard_t(3, 5000) / 20.0
    jb_f = jarque_bera(fattail)
    assert jb_f["p"] is not None and jb_f["p"] < 0.01, jb_f


def _garch_sim(n: int = 3000, omega: float = 1e-4, alpha: float = 0.1,
                beta: float = 0.88, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    v = omega / (1.0 - alpha - beta)
    r = np.empty(n)
    for t in range(n):
        r[t] = math.sqrt(v) * z[t]
        v = omega + alpha * r[t] ** 2 + beta * v
    return r


def test_garch_recovers_params_and_rejects_const_var():
    r = _garch_sim()
    fit = fit_garch(r)
    assert not fit.get("fit_failed"), fit
    assert 0.04 <= fit["alpha"] <= 0.25, fit
    assert 0.75 <= fit["beta"] <= 0.97, fit
    assert fit["rejects_const_var"] is True, fit
    assert fit["vol_half_life_bars"] is not None and fit["vol_half_life_bars"] > 2, fit


def test_band_strategy_flat_spread_has_no_trades_no_cost():
    closes = _synth_closes(n=400, m=2, seed=21)
    # make the two legs identical => spread constant => z==0 => no entry
    same = closes.iloc[:, 0].copy()
    df = pd.DataFrame({"ALPHAUSDT": same, "BETAUSDT": same,
                       "GAMMAUSDT": same, "DELTAUSDT": same,
                       "EPSUSDT": same, "ZETAUSDT": same},
                      index=closes.index, columns=["ALPHAUSDT", "BETAUSDT",
                                                   "GAMMAUSDT", "DELTAUSDT",
                                                   "EPSUSDT", "ZETAUSDT"])
    res = band_strategy_backtest(df, ("ALPHAUSDT", "BETAUSDT"),
                                 {"pairs": [["ALPHAUSDT", "BETAUSDT"]]}, "1h")
    assert res["trade_events"] == 0, res
    assert res["costs_paid_pct"] == 0.0, res
    assert res["net_return_pct"] == 0.0, res
    assert res["survives_cost_hurdle"] is False, res


def test_band_strategy_costs_reduce_profit():
    rng = np.random.default_rng(27)
    n = 1500
    # cointegrated pair with a mean-reverting spread
    v = np.zeros(n)
    phi = 0.9
    for t in range(1, n):
        v[t] = phi * v[t - 1] + rng.normal(0, 0.01)
    base = np.cumsum(rng.normal(0.0004, 0.008, n))
    a = base + v
    b = base
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    other = pd.DataFrame(np.column_stack([100.0 * np.exp(base)] * 4), index=idx,
                         columns=[f"X{i}USDT" for i in range(4)])
    df = pd.concat([
        pd.DataFrame({"ALPHAUSDT": 100.0 * np.exp(a), "BETAUSDT": 100.0 * np.exp(b)},
                     index=idx, columns=["ALPHAUSDT", "BETAUSDT"]),
        other,
    ], axis=1)
    res = band_strategy_backtest(df, ("ALPHAUSDT", "BETAUSDT"),
                                 {"pairs": [["ALPHAUSDT", "BETAUSDT"]]}, "1d")
    assert res["trade_events"] > 0, res
    assert res["gross_return_pct"] is not None
    assert res["net_return_pct"] < res["gross_return_pct"], res


def test_theories_report_smoke_and_structure():
    df = _synth_closes(n=1200)
    rep = theories_report(df, {}, "1h")
    for key in ("capm", "emh", "option_theory", "arbitrage", "overall"):
        assert key in rep, key
    assert rep["capm"]["verdict"]["supports_capm"] in (True, False)
    assert "mean_unpredictable" in rep["emh"]["verdict"]
    assert "normality_holds" in rep["option_theory"]["verdict"]
    assert rep["arbitrage"]["band_backtest"]["survives_cost_hurdle"] in (True, False)
    # determinism: same input -> same numeric content (excluding timestamp field)
    rep2 = theories_report(df, {}, "1h")
    for key in ("capm", "emh", "option_theory", "arbitrage", "overall"):
        assert rep[key] == rep2[key], f"non-deterministic section: {key}"


def test_cointegration_runs_for_configured_pairs():
    from src.theory_backtests import cointegration_pairs
    df = _synth_closes(n=1500, m=6, seed=33)
    cfg = {"pairs": [["SYM0USDT", "SYM1USDT"], ["SYM2USDT", "SYM3USDT"]]}
    rows = cointegration_pairs(df, cfg, "1h")
    assert len(rows) == 2, rows
    for row in rows:
        assert row["pair"] in ([["SYM0USDT", "SYM1USDT"], ["SYM2USDT", "SYM3USDT"]])
        assert "adf_stat" in row and "spread_half_life_days" in row
        assert "_logs" not in row
