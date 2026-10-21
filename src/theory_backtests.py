"""Four-theory backtest battery: CAPM, weak-form EMH, option-pricing (Black-Scholes
assumptions) and no-arbitrage (cointegration pairs) — all on the cross-sectional
universe with the project's cost model.

Everything is deterministic: fixed grids, no RNG. No lookahead: signals are computed
on data up to time t and positions are applied from t+1. Strategy accounting uses
the project's next-open convention (fee_rate + slippage_bps, one-sided per unit).
"""
from __future__ import annotations
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2

from src.portfolio_research import _safe_float, bars_per_year, capm_report, interval_seconds

# ADF tau(mu) asymptotic critical values (constant, no trend; n >= 150).
_ADF_CRIT = {"1pct": -3.473, "5pct": -2.877, "10pct": -2.580}


def default_theory_cfg() -> dict[str, Any]:
    return {
        "pairs": [["BTCUSDT", "ETHUSDT"], ["BNBUSDT", "SOLUSDT"],
                  ["XRPUSDT", "ADAUSDT"], ["BTCUSDT", "SOLUSDT"],
                  ["ETHUSDT", "BNBUSDT"], ["SOLUSDT", "ADAUSDT"]],
        "garch_is_bars": 2000,       # in-sample length for GARCH fit before OOS forecast eval
        "ewma_lambda": 0.94,
        "momentum_lags_bars": [1, 24, 168],
        "hedge_window_days": 14,
        "zscore_window_days": 28,
        "z_entry": 2.0,
        "z_exit": 0.0,
        "estimation_fraction": 0.5,
        "rebalance_bars": 168,       # weekly, 1h bars
        "fee_rate": 0.001,
        "slippage_bps": 2.0,
        "initial_quote": 10000.0,
        "max_trades": 5000,
    }


# ---------------------------------------------------------------- stats helpers


def adf_test(x: np.ndarray) -> dict[str, Any]:
    """Augmented Dickey-Fuller, lag=4, constant, no trend. Returns stat + reject flags."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 20:
        return {"stat": None, "reject_5pct": None, "note": "n<20"}
    n = min(n, 2000)
    x = x[-n:]
    dx = np.diff(x)
    # row j (t = j+5): y = Δx_t = dx[j+4]; lags Δx_{t-i} = dx[j+4-i]; x_{t-1} = x[j+4]
    n_use = len(dx) - 4
    y = dx[4:]
    dep = np.column_stack([
        np.ones(n_use),
        dx[3:3 + n_use], dx[2:2 + n_use], dx[1:1 + n_use], dx[0:n_use],
        x[4:4 + n_use],
    ])
    rho = np.zeros(6)
    try:
        beta, *_ = np.linalg.lstsq(dep, y, rcond=None)
        rho = beta
    except np.linalg.LinAlgError:
        return {"stat": None, "reject_5pct": None, "note": "lstsq_failed"}
    resid = y - dep @ beta
    dof = max(len(y) - 6, 1)
    cov = np.linalg.pinv(dep.T @ dep) * (float(resid @ resid) / dof)
    se = math.sqrt(cov[5, 5]) if cov.shape[0] > 5 else 0.0
    stat = rho[5] / se if se > 0 else None
    if stat is None:
        return {"stat": None, "reject_5pct": None, "note": "zero_se"}
    return {
        "stat": _safe_float(stat),
        "crit_5pct": _ADF_CRIT["5pct"],
        "reject_5pct": bool(stat < _ADF_CRIT["5pct"]),
        "reject_10pct": bool(stat < _ADF_CRIT["10pct"]),
    }


def ljung_box_test(r: np.ndarray, lags: list[int] = (1, 3, 6, 12, 24)) -> dict[str, Any]:
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    T = len(r)
    if T < 30:
        return {"Q": None, "p": None, "note": "n<30"}
    lags = sorted(int(k) for k in lags if int(k) < T)
    s = float(np.mean(r))
    denom = float(np.sum((r - s) ** 2))
    q = 0.0
    for k in lags:
        if k >= T:
            continue
        acorr = float(np.sum((r[:T - k] - s) * (r[k:] - s))) / denom
        q += acorr * acorr / (T - k)
    q = T * (T + 2.0) * q
    p = float(chi2.sf(q, len(lags)))
    return {"Q": _safe_float(q), "p": _safe_float(p), "lags": lags}


def variance_ratio(r: np.ndarray, k: int) -> dict[str, Any]:
    """Lo-MacKinlay variance ratio on (daily) returns."""
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < k + 10:
        return {"vr": None, "t": None, "p": None, "k": int(k)}
    ksum = np.lib.stride_tricks.sliding_window_view(r, k).sum(axis=1)  # (n-k+1,)
    vr = float(np.var(ksum) / (k * np.var(r))) if np.var(r) > 0 else None
    if vr is None:
        return {"vr": None, "t": None, "p": None, "k": int(k)}
    n_obs = len(r) - k + 1
    var_vr = float(sum((4 * k - 4 * j + 1) * j for j in range(1, k + 1)) / (3.0 * n_obs))
    t = (vr - 1.0) / math.sqrt(var_vr) if var_vr > 0 else None
    p = 2.0 * (1.0 - _norm_cdf(abs(t))) if t is not None else None
    return {"vr": _safe_float(vr), "t": _safe_float(t), "p": _safe_float(p), "k": int(k), "n": int(n)}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def jarque_bera(r: np.ndarray) -> dict[str, Any]:
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 30:
        return {"jb": None, "p": None, "note": "n<30"}
    m = float(np.mean(r))
    v = float(np.var(r, ddof=1))
    if v <= 0:
        return {"jb": None, "p": None, "note": "zero_variance"}
    s3 = float(np.mean((r - m) ** 3)) / v ** 1.5
    s4 = float(np.mean((r - m) ** 4)) / (v ** 2)
    jb = n / 6.0 * (s3 * s3 + (s4 - 3.0) ** 2 / 4.0)
    return {"jb": _safe_float(jb), "p": _safe_float(float(chi2.sf(jb, 2))), "skew": _safe_float(s3),
            "excess_kurt": _safe_float(s4 - 3.0), "n": int(n)}


def _garch_loglik(params: tuple[float, float, float], r: np.ndarray) -> float:
    omega, alpha, beta = params
    # infeasible region: return a large penalty instead of crashing
    if omega < 1e-8 or alpha < 1e-6 or beta < 1e-6 or alpha + beta >= 0.999:
        return -1e12
    n = len(r)
    v = omega / (1.0 - alpha - beta)
    logl = 0.0
    for t in range(n):
        if v <= 1e-12:
            return -1e12
        logl += -0.5 * (math.log(v) + r[t] * r[t] / v)
        v = omega + alpha * r[t] ** 2 + beta * v
    return -0.5 * n * math.log(2.0 * math.pi) + logl


def _const_loglik(r: np.ndarray) -> float:
    v = float(np.mean(r ** 2))
    if v <= 0:
        return -1e12
    return -0.5 * len(r) * (math.log(2.0 * math.pi) + math.log(v) + 1.0)


def fit_garch(r: np.ndarray, grid: list[tuple[float, float, float]] | None = None) -> dict[str, Any]:
    """Deterministic GARCH(1,1) MLE: fixed grid + Nelder-Mead polish on the top-5 starts."""
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    m = float(np.mean(r))
    r = (r - m) / float(np.std(r, ddof=1))  # standardize: variance 1
    n = len(r)
    if n < 200:
        return {"fit_failed": True, "n": int(n)}
    if grid is None:
        grid = [(o, a, b) for o in (0.001, 0.005, 0.02)
                for a in (0.05, 0.1, 0.2, 0.4)
                for b in (0.7, 0.8, 0.9, 0.95)
                if o + a + b < 0.999]
    scored = []
    for start in grid:
        if start[1] + start[2] >= 0.999:
            continue
        scored.append((_garch_loglik(start, r), start))
    if not scored:
        return {"fit_failed": True, "n": int(n)}
    scored.sort(key=lambda t: t[0], reverse=True)
    from scipy.optimize import minimize
    best_ll, best_cand = scored[0]
    for ll0, start in scored[:5]:
        try:
            res = minimize(lambda p: -_garch_loglik(tuple(float(x) for x in p), r), list(start),
                           method="Nelder-Mead", options={"xatol": 1e-9, "maxiter": 400, "adaptive": True})
            cand = (max(float(res.x[0]), 1e-8), max(float(res.x[1]), 1e-6), max(float(res.x[2]), 1e-6))
            if cand[1] + cand[2] >= 0.999:
                continue
            ll = _garch_loglik(cand, r)
            if ll > best_ll + 1e-9:
                best_ll, best_cand = ll, cand
        except Exception:
            continue
    omega, alpha, beta = best_cand
    lr = 2.0 * (best_ll - _const_loglik(r))
    p = float(chi2.sf(max(lr, 0.0), 2))
    ab = alpha + beta
    half_life = math.log(0.5) / math.log(ab) if 0 < ab < 1 else None
    return {
        "omega": _safe_float(omega), "alpha": _safe_float(alpha), "beta": _safe_float(beta),
        "persistence": _safe_float(ab),
        "vol_half_life_bars": _safe_float(half_life),
        "lr_vs_const_var": _safe_float(lr),
        "lr_p": _safe_float(p),
        "rejects_const_var": bool(lr > chi2.ppf(0.95, 2)),
        "n": int(n),
    }


def garch_forecast_eval(r: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any]:
    """OOS one-step-ahead vol forecast: GARCH(IS fit) vs EWMA; Diebold-Mariani t."""
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    is_len = int(min(cfg.get("garch_is_bars", 2000), n // 2))
    lam = float(cfg.get("ewma_lambda", 0.94))
    if is_len < 500 or n - is_len < 200:
        return {"dm_t": None, "note": "short_sample"}
    fit = fit_garch(r[:is_len])
    if fit.get("fit_failed"):
        return {"dm_t": None, "note": "garch_fit_failed"}
    omega, alpha, beta = fit["omega"], fit["alpha"], fit["beta"]
    oos = r[is_len:]
    # GARCH OOS path in observation units: rescale omega from the standardized fit
    # (alpha/beta are dimensionless and carry over).
    scale2 = float(np.mean(r ** 2))
    alpha, beta = fit["alpha"], fit["beta"]
    omega_obs = fit["omega"] * scale2
    v = scale2
    err_g = np.empty(len(oos))
    for i, rt in enumerate(oos):
        err_g[i] = v - rt * rt
        v = omega_obs + alpha * rt * rt + beta * v
    # EWMA
    lam = lam
    v = float(np.mean(r[:is_len] ** 2))
    err_e = np.empty(len(oos))
    for i, rt in enumerate(oos):
        err_e[i] = v - rt * rt
        v = lam * v + (1.0 - lam) * rt * rt
    D = err_g * err_g - err_e * err_e
    t_dm = float(np.mean(D)) / (float(np.std(D, ddof=1)) / math.sqrt(len(D))) if len(D) > 2 else None
    return {
        "is_bars": int(is_len), "oos_bars": int(len(oos)),
        "garch_rmse": _safe_float(float(np.sqrt(np.mean(err_g ** 2)))),
        "ewma_rmse": _safe_float(float(np.sqrt(np.mean(err_e ** 2)))),
        "dm_t": _safe_float(t_dm),
        "dm_note": "positive t_dm => EWMA better (lower squared error)",
    }


# ---------------------------------------------------------------- EMH helpers


def _pool_daily(closes: pd.DataFrame, interval: str) -> tuple[np.ndarray, int]:
    """Cross-sectional mean log return, resampled to daily by stride."""
    bpy_day = int(round(86400.0 / interval_seconds(interval)))
    logs = np.log(closes.values.astype(float))
    daily = logs[::bpy_day]
    pool = daily.mean(axis=1)
    return np.diff(pool), bpy_day


def _correlation_t(x: np.ndarray, k: int) -> dict[str, Any]:
    n = len(x) - k
    if n < 30:
        return {"r": None, "t": None, "note": "n<30"}
    a = x[:n] - x[:n].mean()
    b = x[k:k + n] - x[k:k + n].mean()
    denom = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
    r = float(np.sum(a * b)) / denom if denom > 0 else 0.0
    t = r * math.sqrt((n - 2.0) / max(1.0 - r * r, 1e-12))
    return {"r": _safe_float(r), "t": _safe_float(t)}


# ---------------------------------------------------------------- CAPM: tercile sort


def capm_tercile_backtest(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                          annualization: str = "crypto_24x7") -> dict[str, Any]:
    """Classical SML empirical test: sort OOS assets into terciles by in-sample beta,
    compare mean returns across terciles (no lookahead: beta estimated on first 50%)."""
    c = {**default_theory_cfg(), **(cfg or {})}
    rets = closes.pct_change().dropna(how="any")
    symbols = [str(x) for x in rets.columns]
    R = rets.values
    T = len(R)
    bpy = bars_per_year(interval, annualization)
    if T < 120:
        raise ValueError(f"tercile backtest needs >= 120 bars, got {T}")
    mret = R.mean(axis=1)
    split = int(T * float(c.get("estimation_fraction", 0.5)))
    est_m = mret[:split]
    beta_of = {}
    for j, sym in enumerate(symbols):
        x, y = est_m, R[:split, j]
        ss_xx = float(np.sum((est_m - est_m.mean()) ** 2))
        beta_of[sym] = float(np.sum((est_m - est_m.mean()) * (y - y.mean())) / ss_xx) if ss_xx > 0 else 0.0
    ranked = sorted(symbols, key=lambda s: beta_of[s])
    k = len(ranked) // 3
    terciles: list[list[str]] = []
    for i in range(0, k * 3, k):
        terciles.append(ranked[i:i + k])
    oos = R[split:]
    out: dict[str, Any] = {"estimation_bars": int(split), "terciles": []}
    ann_means = []
    for ti, grp in enumerate(terciles):
        idx = [symbols.index(g) for g in grp]
        pr = np.column_stack([oos[:, j] for j in idx]).mean(axis=1)  # equal-weight
        ann = float(pr.mean()) * bpy * 100
        ann_means.append(ann)
        out["terciles"].append({
            "tercile": ti + 1, "assets": grp,
            "mean_betas": [_safe_float(beta_of[g]) for g in grp],
            "ann_return_pct": _safe_float(ann),
        })
    # monotonicity: correlation of tercile rank with mean return
    if len(ann_means) == 3:
        ranks = np.array([0.5, 1.0, 1.5], float)
        vals = np.array(ann_means, float)
        mono_r = float(np.corrcoef(ranks, vals)[0, 1]) if np.std(vals) > 0 else None
    else:
        mono_r = None
    out["monotonicity_corr"] = _safe_float(mono_r)
    out["beta_gradient_check"] = (
        "low<high" if mono_r is not None and mono_r > 0 else ("low>high (reversal)" if mono_r is not None and mono_r < 0 else "inconclusive"))
    return out


# ---------------------------------------------------------------- cointegration / pairs


def cointegration_pairs(closes: pd.DataFrame, cfg: dict[str, Any], interval: str) -> list[dict[str, Any]]:
    """Rolling-hedge cointegration diagnostics for candidate pairs (daily stride)."""
    c = {**default_theory_cfg(), **(cfg or {})}
    W = int(c.get("hedge_window_days", 14))
    stride = int(round(86400.0 / interval_seconds(interval)))
    logs = np.log(closes.values.astype(float))
    daily_a = logs[::stride]
    Td = len(daily_a)
    rows = []
    for pair in c.get("pairs", []):
        if len(pair) != 2:
            continue
        sa, sb = str(pair[0]), str(pair[1])
        if sa not in closes.columns or sb not in closes.columns:
            continue
        ia, ib = list(closes.columns).index(sa), list(closes.columns).index(sb)
        a, b = daily_a[:, ia], daily_a[:, ib]
        beta_roll = np.full(Td, np.nan)
        z_win = int(c.get("zscore_window_days", 28))
        spread = np.full(Td, np.nan)
        for i in range(W, Td):
            xa = a[i - W:i]
            xb = b[i - W:i]
            sol = np.linalg.lstsq(np.column_stack([xb, np.ones(W)]), xa, rcond=None)[0]
            beta_roll[i] = sol[0]
            spread[i] = a[i] - sol[0] * b[i]
        # AR(1) half-life on the spread (diagnostic, full sample)
        s_ok = spread[~np.isnan(spread)]
        ds = np.diff(s_ok)
        phi, res = None, None
        if len(s_ok) > 30:
            xreg = s_ok[:-1]
            phi_hat = float(np.dot(ds, xreg) / np.dot(xreg, xreg)) if float(np.dot(xreg, xreg)) > 0 else None
            phi = phi_hat
        half_life = None
        if phi is not None and 0.0 < phi < 1.0:
            half_life = math.log(0.5) / math.log(phi)
        adf = adf_test(s_ok)
        # rolling z-score
        z = np.full(Td, np.nan)
        for i in range(W + z_win, Td):
            seg = spread[i - z_win:i]
            sd = float(np.std(seg, ddof=1))
            z[i] = (spread[i] - float(np.mean(seg))) / sd if sd > 1e-9 else 0.0
        rows.append({
            "pair": [sa, sb],
            "adf_stat": adf.get("stat"),
            "adf_reject_5pct": adf.get("reject_5pct"),
            "ar1_phi": _safe_float(phi),
            "spread_half_life_days": _safe_float(half_life),
            "best_beta_roll": _safe_float(float(np.nanmean(beta_roll))),
            "best_z": _safe_float(float(np.nanmax(np.abs(z))) if not np.all(np.isnan(z)) else None),
        })
    # Best cointegration first: reject unit root on the spread, strongest stat.
    rows.sort(key=lambda r: (0 if r["adf_reject_5pct"] else 1,
                             -abs(r["adf_stat"] or 0.0)))
    return rows


def band_strategy_backtest(closes: pd.DataFrame, pair: tuple[str, str], cfg: dict[str, Any],
                           interval: str, annualization: str = "crypto_24x7") -> dict[str, Any]:
    """Spread band strategy on the cointegrated pair, daily positions (t signal -> t+1),
    cost hurdle per unit of position change on both legs."""
    c = {**default_theory_cfg(), **(cfg or {})}
    sa, sb = str(pair[0]), str(pair[1])
    stride = int(round(86400.0 / interval_seconds(interval)))
    W = int(c.get("hedge_window_days", 14))
    ZW = int(c.get("zscore_window_days", 28))
    ze, zx = float(c.get("z_entry", 2.0)), float(c.get("z_exit", 0.0))
    fee = float(c.get("fee_rate", 0.001))
    slip = float(c.get("slippage_bps", 2.0)) / 1e4
    unit_cost = fee + slip  # per leg; a unit of |Δpos| touches 2 legs
    notional = float(c.get("initial_quote", 10000.0))
    logs = np.log(closes.values.astype(float))
    daily = logs[::stride]
    Td = len(daily)
    ia, ib = list(closes.columns).index(sa), list(closes.columns).index(sb)
    a, b = daily[:, ia], daily[:, ib]
    beta_roll = np.full(Td, np.nan)
    spread = np.full(Td, np.nan)
    for i in range(W, Td):
        xa, xb = a[i - W:i], b[i - W:i]
        sol = np.linalg.lstsq(np.column_stack([xb, np.ones(W)]), xa, rcond=None)[0]
        beta_roll[i] = sol[0]
        spread[i] = a[i] - sol[0] * b[i]
    z = np.full(Td, np.nan)
    for i in range(W + ZW, Td):
        seg = spread[i - ZW:i]
        sd = float(np.std(seg, ddof=1))
        z[i] = (spread[i] - float(np.mean(seg))) / sd if sd > 1e-9 else 0.0
    # positions decided on z_t, applied on t+1 (no lookahead)
    pos = np.zeros(Td)
    cur = 0.0
    start = W + ZW
    for i in range(start, Td - 1):
        if np.isnan(z[i]):
            continue
        if cur == 0.0:
            if z[i] < -ze:
                cur = 1.0
            elif z[i] > ze:
                cur = -1.0
        elif cur == 1.0 and z[i] > zx:
            cur = 0.0
        elif cur == -1.0 and z[i] < -zx:
            cur = 0.0
        pos[i + 1] = cur
    daily_ret_a = np.diff(a)
    daily_ret_b = np.diff(b)
    # spread ret on day t (transition t-1 -> t) with the beta in force on t
    spread_ret = np.full(Td, np.nan)
    valid = np.where(~np.isnan(beta_roll))[0]
    valid = valid[valid >= 1]
    for i in valid:
        spread_ret[i] = daily_ret_a[i - 1] - beta_roll[i] * daily_ret_b[i - 1]
    pnl = pos * spread_ret
    pnl = np.nan_to_num(pnl, nan=0.0)
    dpos = np.diff(pos, prepend=0.0)
    # Single cost-consistent pass: gross equity in quote units, absolute costs on
    # initial notional (project convention), one trade event per |Δpos|.
    gross_eq = notional
    cum_cost = 0.0
    eq_curve = np.empty(Td)
    eq_curve[:start] = notional
    trades = 0
    for i in range(start, Td):
        gross_eq *= (1.0 + pnl[i]) if pnl[i] > -0.999 else 0.0
        cum_cost += notional * abs(dpos[i]) * unit_cost * 2.0
        eq_curve[i] = gross_eq - cum_cost
        if abs(dpos[i]) > 1e-9:
            trades += 1
    gross_pnl = gross_eq - notional
    net_pnl = eq_curve[-1] - notional
    eq = eq_curve
    rets_daily = np.diff(eq[start:]) / eq[start:-1]
    rets_daily = np.clip(rets_daily, -0.999, None)
    bpy_day = 365.0 if annualization == "crypto_24x7" else 252.0
    n_days = Td - start
    ann_ret = ((eq[-1] / notional) ** (bpy_day / max(n_days, 1)) - 1.0) * 100 if eq[-1] > 0 else -100.0
    ann_vol = float(np.std(rets_daily, ddof=1)) * math.sqrt(bpy_day) * 100 if len(rets_daily) > 2 else 0.0
    sharpe = ann_ret / ann_vol if ann_vol > 1e-9 else None
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq / peak - 1.0)) * 100
    out = {
        "pair": [sa, sb],
        "hedge_beta_mean": _safe_float(float(np.nanmean(beta_roll))),
        "trade_events": int(trades),
        "gross_return_pct": _safe_float(gross_pnl / notional * 100),
        "net_return_pct": _safe_float(net_pnl / notional * 100),
        "costs_paid_pct": _safe_float(cum_cost / notional * 100),
        "annualized_return_pct": _safe_float(ann_ret),
        "annualized_vol_pct": _safe_float(ann_vol),
        "sharpe": _safe_float(sharpe),
        "max_drawdown_pct": _safe_float(dd),
        "survives_cost_hurdle": bool(net_pnl > 0.0),
        "cost_convention": "fee + slippage per leg, 2 legs per unit of |Δpos|, charged on initial notional",
        "no_lookahead": "position on day t uses z-score of data up to t-1",
    }
    return out


def long_short_tercile_backtest(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                                annualization: str = "crypto_24x7") -> dict[str, Any]:
    """Cross-sectional long high-beta / short low-beta terciles: check the edge is NOT
    riskless (no pure arbitrage) — report vol + net after costs."""
    c = {**default_theory_cfg(), **(cfg or {})}
    rets = closes.pct_change().dropna(how="any")
    R = rets.values
    symbols = [str(x) for x in rets.columns]
    T = len(R)
    bpy = bars_per_year(interval, annualization)
    split = int(T * float(c.get("estimation_fraction", 0.5)))
    mret = R.mean(axis=1)
    est_m = mret[:split]
    beta_of = {}
    for j, sym in enumerate(symbols):
        x, y = est_m, R[:split, j]
        ss_xx = float(np.sum((est_m - est_m.mean()) ** 2))
        beta_of[sym] = float(np.sum((est_m - est_m.mean()) * (y - y.mean())) / ss_xx) if ss_xx > 0 else 0.0
    ranked = sorted(symbols, key=lambda s: beta_of[s])
    k = max(len(ranked) // 3, 1)
    longs, shorts = ranked[-k:], ranked[:k]
    oos = R[split:]
    fee = float(c.get("fee_rate", 0.001))
    unit_cost = fee + float(c.get("slippage_bps", 2.0)) / 1e4
    notional = float(c.get("initial_quote", 10000.0))
    li = [symbols.index(x) for x in longs]
    si = [symbols.index(x) for x in shorts]
    # daily long-short return (fixed equal weights; cost charged once at entry,
    # 2 legs, on initial notional — project absolute-cost convention)
    ls_daily = np.column_stack([oos[:, j] for j in li]).mean(axis=1) - \
        np.column_stack([oos[:, j] for j in si]).mean(axis=1)
    gross_eq = 1.0
    eq_curve = np.empty(len(oos))
    entry_cost = notional * 2.0 * unit_cost  # open long leg + short leg
    for i, r in enumerate(ls_daily):
        gross_eq *= (1.0 + r) if r > -0.999 else 0.0
        eq_curve[i] = notional * gross_eq - entry_cost
    eq = eq_curve
    rets_clean = np.clip(np.diff(eq) / eq[:-1], -0.999, None)
    bpy_day = bpy
    ann_vol = float(np.std(rets_clean, ddof=1)) * math.sqrt(bpy_day) * 100 if len(rets_clean) > 2 else 0.0
    ann_ret = (eq[-1] / notional) ** (bpy_day / max(len(eq) - 1, 1)) - 1.0
    sharpe = ann_ret * 100.0 / ann_vol if ann_vol > 1e-9 else None
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq / peak - 1.0)) * 100
    return {
        "longs": longs, "shorts": shorts,
        "gross_ann_pct": _safe_float(float(np.mean(ls_daily)) * bpy * 100.0),
        "net_return_pct": _safe_float((eq[-1] - notional) / notional * 100.0),
        "costs_paid_pct": _safe_float(entry_cost / notional * 100.0),
        "annualized_return_pct": _safe_float(ann_ret * 100.0),
        "annualized_vol_pct": _safe_float(ann_vol),
        "sharpe": _safe_float(sharpe),
        "max_drawdown_pct": _safe_float(dd),
        "riskless": bool(ann_vol < 1.0),
        "note": "a pure arbitrage would have ~0 vol and positive net; this is a long/short factor spread",
    }


# ---------------------------------------------------------------- main report


def theories_report(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                    annualization: str = "crypto_24x7") -> dict[str, Any]:
    from datetime import datetime, timezone
    c = {**default_theory_cfg(), **(cfg or {})}
    rets = closes.pct_change().dropna(how="any")
    symbols = [str(x) for x in rets.columns]
    R = rets.values
    bpy = bars_per_year(interval, annualization)
    pool_daily, _stride = _pool_daily(closes, interval)

    # ---- 1. CAPM (asset pricing) ----
    capm_sml = capm_report(closes, c, interval, annualization)
    tercile = capm_tercile_backtest(closes, c, interval, annualization)
    sml = capm_sml["sml"]
    capm_verdict = {
        "two_pass_sml_r2": sml.get("r2"),
        "two_pass_sml_slope_pct_per_beta": sml.get("annualized_slope_pct_per_beta"),
        "supports_sml_fit": bool(capm_sml["verdict"]["sml_fit_ok"]),
        "no_significant_alpha": len(capm_sml["verdict"]["significant_alphas"]) == 0,
        "tercile_monotonicity": tercile["monotonicity_corr"],
        "supports_capm": bool(capm_sml["verdict"]["supports_capm_pricing"]),
    }

    # ---- 2. EMH (weak form) ----
    lb_1h = ljung_box_test(R.mean(axis=1), [1, 3, 6, 12, 24])
    lb_1d = ljung_box_test(pool_daily, [1, 2, 5, 10])
    vr = [variance_ratio(pool_daily, k) for k in (2, 5, 10)]
    mom = {}
    pool_1h = R.mean(axis=1)
    for lag in c.get("momentum_lags_bars", [1, 24, 168]):
        t_res = _correlation_t(pool_1h, int(lag))
        mom[str(lag)] = {"corr_next_bar": t_res["r"], "t": t_res["t"],
                         "interpretation": "momentum" if (t_res["t"] or 0) > 1.5 else
                                           ("reversal" if (t_res["t"] or 0) < -1.5 else "unpredictable")}
    garch_pool = fit_garch(pool_daily)
    garch_forecast = garch_forecast_eval(pool_daily, c)
    emh_verdict = {
        "mean_unpredictable": bool(
            (lb_1h.get("p") is None or lb_1h["p"] >= 0.05)
            and (lb_1d.get("p") is None or lb_1d["p"] >= 0.05)
            and all(abs(mom[str(l)].get("t") or 0.0) < 1.5 for l in mom)
            and all((v.get("p") or 1.0) >= 0.05 for v in vr)),
        "volatility_clustering": bool(garch_pool.get("rejects_const_var")),
        "garch_inconclusive": bool(garch_pool.get("fit_failed")),
        "note": ("weak-form EMH (return means) vs volatility clustering; "
                 "GARCH effect rejects constant-variance but is consistent with weak-form efficiency"),
    }

    # ---- 3. Option pricing (Black-Scholes assumptions) ----
    stride = int(round(86400.0 / interval_seconds(interval)))
    jb_daily = {}
    for sym in symbols:
        r_daily = np.diff(np.log(closes[sym].values.astype(float))[::stride])
        jb_daily[sym] = jarque_bera(r_daily)
    garch_assets = {sym: fit_garch(np.diff(np.log(closes[sym].values.astype(float))[::stride])).get("rejects_const_var")
                    for sym in symbols}
    bs_verdict = {
        "normality_holds": all(
            jb_daily[s].get("p") is not None and jb_daily[s]["p"] >= 0.05 for s in symbols),
        "const_var_holds": all(garch_assets[s] is not True for s in symbols),
        "notes": "no option market data in this project; tests the *assumptions* "
                 "(Gaussian returns, constant sigma) on spot daily returns",
    }

    # ---- 4. Arbitrage (no free lunch) ----
    coint = cointegration_pairs(closes, c, interval)
    best = coint[0] if coint else None
    band = band_strategy_backtest(closes, (best["pair"][0], best["pair"][1]), c, interval, annualization) \
        if best else {"pair": [], "net_return_pct": None, "survives_cost_hurdle": False}
    lts = long_short_tercile_backtest(closes, c, interval, annualization)
    arb_verdict = {
        "pure_arbitrage_found": False,
        "note": "band strategy is a *statistical* arbitrage (cointegration): it has vol and "
                "costs, so it is not a riskless 'free lunch'; net<=0 confirms no exploitable edge",
        "stat_arb_exploitable": bool(band.get("survives_cost_hurdle") and (band.get("sharpe") or 0) > 1.0),
    }

    overall = {
        "capm_supported": capm_verdict["supports_capm"],
        "emh_weak_form": emh_verdict["mean_unpredictable"],
        "emh_vol_clustering_rejected_const_var": emh_verdict["volatility_clustering"],
        "bs_assumptions_hold": bs_verdict["normality_holds"] and bs_verdict["const_var_holds"],
        "no_free_lunch_holds": not arb_verdict["pure_arbitrage_found"] and not arb_verdict["stat_arb_exploitable"],
    }
    return {
        "universe": symbols,
        "bars": int(len(R)),
        "interval": str(interval),
        "annualization": str(annualization),
        "bars_per_year": _safe_float(bpy),
        "capm": {"sml": sml, "assets": capm_sml["assets"], "tercile": tercile, "verdict": capm_verdict},
        "emh": {"ljung_box_1h": lb_1h, "ljung_box_1d": lb_1d, "variance_ratio": vr,
                 "momentum": mom, "garch": garch_pool, "garch_forecast": garch_forecast,
                 "verdict": emh_verdict},
        "option_theory": {"jarque_bera_daily": jb_daily, "garch_reject_const_var": garch_assets,
                          "verdict": bs_verdict},
        "arbitrage": {"cointegration": coint,
                      "band_backtest": band, "long_short_tercile": lts, "verdict": arb_verdict},
        "overall": overall,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
