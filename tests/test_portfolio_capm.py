import numpy as np
import pandas as pd

from src.portfolio_research import (
    bars_per_year,
    capm_report,
    equal_weight,
    fit_weights,
    interval_seconds,
    oas_covariance,
    portfolio_report,
    portfolio_risk_contributions,
    risk_parity_weights,
)

SYMBOLS = ["AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT"]
BETAS = [0.6, 0.9, 1.2, 1.5, 0.8, 1.1]


def synthetic_panel(n=600, seed=7, market_drift=0.0005, market_vol=0.001, idio_vol=0.0008):
    """Crypto-style panel: each asset = beta_i * market + idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    m = rng.normal(market_drift, market_vol, n)
    data = {}
    for i, sym in enumerate(SYMBOLS):
        eps = rng.normal(0.0, idio_vol, n)
        r = BETAS[i] * m + eps
        data[sym] = 100.0 * np.exp(np.cumsum(r))
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(data, index=idx)


def test_interval_and_annualization():
    assert interval_seconds("1h") == 3600
    assert interval_seconds("4h") == 14400
    assert abs(bars_per_year("1h") - 8760.0) < 1e-9
    assert abs(bars_per_year("4h") - 2190.0) < 1e-9
    assert abs(bars_per_year("1h", "stock_252") - (252 * 6.5)) < 1e-9


def test_oas_covariance_is_psd_and_shrinks():
    rng = np.random.default_rng(1)
    X = rng.normal(0.0, 1.0, size=(400, 6))
    cov, delta = oas_covariance(X)
    assert 0.0 <= delta <= 1.0
    assert np.linalg.eigvalsh(cov).min() > -1e-10
    sample = np.cov(X.T, ddof=1)
    target = (float(np.trace(sample)) / 6.0) * np.eye(6)
    assert np.abs(cov - target).max() <= np.abs(sample - target).max()


def test_capm_recovers_betas_and_prices_the_cross_section():
    closes = synthetic_panel()
    rep = capm_report(closes, {"market_model": "ew"}, "1h")
    assert rep["bars"] == len(closes) - 1
    got = {row["symbol"]: row["beta"] for row in rep["assets"]}
    for sym, beta in zip(SYMBOLS, BETAS):
        assert abs(got[sym] - beta) < 0.15, (sym, got[sym], beta)
    assert rep["sml"]["r2"] is not None and rep["sml"]["r2"] > 0.9
    assert rep["verdict"]["significant_alphas"] == []
    assert rep["verdict"]["supports_capm_pricing"] is True


def test_capm_detects_injected_alpha():
    closes = synthetic_panel()
    rets = closes.pct_change().dropna(how="any")
    rets["CUSDT"] = rets["CUSDT"] + 0.0004  # constant unexplained alpha
    closes2 = 100.0 * (1.0 + rets).cumprod()
    rep = capm_report(closes2, {"market_model": "ew", "capm_alpha_t": 2.0}, "1h")
    by_sym = {r["symbol"]: r for r in rep["assets"]}
    assert by_sym["CUSDT"]["alpha_t"] > 2.0
    assert "CUSDT" in rep["verdict"]["significant_alphas"]
    assert rep["verdict"]["supports_capm_pricing"] is False


def test_fit_weights_feasible_and_respect_cap():
    closes = synthetic_panel(n=400)
    rets = closes.pct_change().dropna().values
    cfg = {"weight_max": 0.5}
    for cand in ["equal_weight", "min_variance", "mvo_shrinkage", "risk_parity"]:
        out = fit_weights(cand, rets, cfg)
        w = out["weights"]
        assert abs(float(w.sum()) - 1.0) < 1e-9
        assert w.min() >= -1e-12
        assert w.max() <= 0.5 + 1e-9
    assert np.allclose(fit_weights("equal_weight", rets, cfg)["weights"], 1.0 / 6)


def test_risk_parity_equal_risk_contributions():
    closes = synthetic_panel(n=400)
    rets = closes.pct_change().dropna().values
    cov, _ = oas_covariance(rets)
    w, ok = risk_parity_weights(cov, 1.0)  # uncapped: exact ERC
    assert ok
    rc = portfolio_risk_contributions(w, cov)
    rc_norm = rc / rc.sum()  # normalized contributions sum to 1
    assert abs(float(rc_norm.mean()) - 1.0 / 6) < 1e-9
    assert float(np.max(np.abs(rc_norm - 1.0 / 6))) < 1e-6
    # capped variant stays feasible
    w_c, ok_c = risk_parity_weights(cov, 0.5)
    assert ok_c
    assert w_c.max() <= 0.5 + 1e-9 and abs(float(w_c.sum()) - 1.0) < 1e-9


def test_mvo_tilts_to_high_return_asset():
    n = 500
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    hot = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.008, n)))
    base = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.008, n)))
    data = {"HOTHOT": hot}
    for j in range(5):
        data[f"FLAT{j}"] = base * (1.0 + j * 0.01)
    closes = pd.DataFrame(data, index=idx)
    rets = closes.pct_change().dropna().values
    w = fit_weights("mvo_shrinkage", rets, {"risk_aversion_gamma": 5.0, "weight_max": 0.6})["weights"]
    assert int(w.argmax()) == 0  # the hot asset gets the largest weight


def test_portfolio_report_cost_and_turnover_accounting():
    closes = synthetic_panel(n=400)
    cfg = {"candidates": ["equal_weight"], "walkforward_folds": 3, "train_fraction": 0.5}
    rep = portfolio_report(closes, cfg, "1h")
    bench = rep["benchmark_equal_weight"]
    # fold 0 deploys from full cash -> one-sided turnover exactly 1.0
    assert abs(bench["folds"][0]["turnover_one_sided"] - 1.0) < 1e-9
    # equal-weight weights never change -> total turnover stays at 1.0
    assert abs(bench["total_turnover_one_sided"] - 1.0) < 1e-9
    assert bench["costs_quote"] > 0.0
    assert bench["net_return_pct"] <= bench["gross_return_pct"] + 1e-9
    # OOS spans tile the data from train_len to the end
    spans = [f["span"] for f in bench["folds"]]
    assert spans[0][0] == rep["train_len_bars"]
    assert spans[-1][1] == rep["bars"]
    for i in range(len(spans) - 1):
        assert spans[i][1] == spans[i + 1][0]


def test_portfolio_weights_do_not_look_ahead():
    closes = synthetic_panel(n=500)
    cfg = {"candidates": ["min_variance"], "walkforward_folds": 3, "train_fraction": 0.5, "weight_max": 0.5}
    rep_full = portfolio_report(closes, cfg, "1h")
    spans = [tuple(map(int, s.split(":"))) for s in rep_full["folds"]]
    a0 = spans[0][0]
    mutated = closes.copy()
    # Fold-0 fit window is rets[0:a0] = close bars C[0..a0]. Mutating C[a0] or
    # earlier would change the weights (by design, that IS the fit data);
    # C[a0+1:] is OOS data and must not influence fold-0 weights.
    mutated.iloc[a0 + 1:] = 0.5  # constant prices -> zero returns
    rep_mut = portfolio_report(mutated, cfg, "1h")
    w_full = rep_full["candidates_report"]["min_variance"]["folds"][0]["weights"]
    w_mut = rep_mut["candidates_report"]["min_variance"]["folds"][0]["weights"]
    assert w_full == w_mut  # fold-0 weights must be identical: no lookahead


def test_portfolio_rejects_short_history():
    closes = synthetic_panel(n=80)
    try:
        portfolio_report(closes, {}, "1h")
        raise AssertionError("expected ValueError for short history")
    except ValueError:
        pass


def test_unknown_candidate_rejected():
    closes = synthetic_panel(n=400)
    try:
        portfolio_report(closes, {"candidates": ["magic_bullet"]}, "1h")
        raise AssertionError("expected ValueError for unknown candidate")
    except ValueError:
        pass


def test_portfolio_curves_shapes_and_alignment():
    from src.portfolio_research import portfolio_curves
    closes = synthetic_panel(n=400)
    cfg = {"candidates": ["min_variance", "risk_parity"], "walkforward_folds": 3, "train_fraction": 0.5}
    c = portfolio_curves(closes, cfg, "1h")
    # benchmark is always available even when not requested
    assert "equal_weight" in c["candidates"]
    for cand, data in c["candidates"].items():
        assert len(data["net"]) == len(c["oos_times"])
        assert len(data["gross"]) == len(c["oos_times"])
        assert data["net"][0] <= data["net"][-1] * 10  # sane scale
    # OOS spans tile from train_len to end
    spans = c["folds"]
    assert spans[0][0] == c["train_len_bars"]
    assert spans[-1][1] == len(closes) - 1
    for i in range(len(spans) - 1):
        assert spans[i][1] == spans[i + 1][0]
    # buy & hold prices align with oos_times (entry bar + 1)
    for sym in c["universe"]:
        assert len(c["buy_hold_prices"][sym]) == len(closes) - c["train_len_bars"]
