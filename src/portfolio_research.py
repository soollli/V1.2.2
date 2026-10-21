"""Cross-sectional portfolio & CAPM research.

Deterministic native research layer for the terminal's small crypto universe:

- CAPM / SML diagnostics: one-pass OLS per asset against a market proxy
  (equal-weight universe index or BTCUSDT), alpha t-tests, two-pass SML fit.
- Portfolio candidates: equal-weight, minimum-variance, MVO with OAS-shrunk
  covariance and mu, and risk-parity (equal risk contribution), all fitted on
  expanding train windows only (no lookahead), reweighted once per
  walk-forward fold, with next-open style cost accounting.

Everything here is research evidence, not an order: results feed the
Promotion Gate through immutable run IDs (archive_research_run).
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

import numpy as np
import pandas as pd


def _minimize(fn, x0, **kwargs):
    """Lazy scipy import so the module (and run.py) still work without scipy.
    Only the constrained weight solvers need it; CAPM diagnostics are pure numpy."""
    try:
        from scipy.optimize import minimize
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "scipy is required for constrained portfolio solvers "
            "(min_variance / mvo_shrinkage / risk_parity). "
            "Install it with: pip install scipy  (or: pip install -r requirements.txt)"
        ) from exc
    return minimize(fn, x0, **kwargs)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except Exception:
        return None


_INTERVAL_RE = re.compile(r"^(\d+)([mhd])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def interval_seconds(interval: str) -> int:
    m = _INTERVAL_RE.match(str(interval).strip().lower())
    if not m:
        raise ValueError(f"unsupported interval: {interval!r}")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def bars_per_year(interval: str, annualization: str = "crypto_24x7") -> float:
    """Annualization factor for a bar grid. Crypto trades 24x7 (365 days);
    the stock convention is 252 trading days of 6.5h sessions."""
    seconds = interval_seconds(interval)
    if str(annualization) == "stock_252":
        return float(252 * 6.5 * 3600 / seconds)
    return float(365 * 86400 / seconds)


def default_portfolio_cfg() -> dict[str, Any]:
    return {
        "market_model": "ew",
        "capm_alpha_t": 2.0,
        "capm_min_sml_r2": 0.6,
        "candidates": ["equal_weight", "min_variance", "mvo_shrinkage", "risk_parity"],
        "walkforward_folds": 3,
        "train_fraction": 0.5,
        "weight_max": 0.5,
        "risk_aversion_gamma": 2.0,
        "fee_rate": 0.001,
        "slippage_bps": 2.0,
        "initial_quote": 10000.0,
    }


# ---------------------------------------------------------------------------
# covariance estimation (OAS shrinkage, closed form — no randomness)
# ---------------------------------------------------------------------------

def oas_covariance(rets: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf OAS shrinkage toward a scaled-identity target.

    rets: T x N simple returns. Returns (shrunk_cov, delta).
    Mirrors the closed-form OAS estimator (Chen, El Ghaoui & Larrard 2010).
    """
    rets = np.asarray(rets, dtype=float)
    T, N = rets.shape
    if T < N + 1:
        # Degenerate sample: keep sample cov but flag it to the caller.
        cov = np.cov(rets, rowvar=False, ddof=1)
        return cov, 0.0
    mean = rets.mean(axis=0)
    S = (rets - mean).T @ (rets - mean) / (T - 1)
    tr_s = float(np.trace(S))
    target = (tr_s / N) * np.eye(N)
    tr_s2 = float(np.trace(S @ S))
    a2 = tr_s2 - tr_s * tr_s
    b2 = float(np.sum((S - target) ** 2))
    if b2 <= 0:
        delta = 0.0
    else:
        delta = min(1.0, max(0.0, ((T + 1) / (T * (T + 3))) * a2 / b2))
    return (1.0 - delta) * S + delta * target, delta


# ---------------------------------------------------------------------------
# weight solvers (deterministic SLSQP on a fixed start point)
# ---------------------------------------------------------------------------

def _simplex_solve(objective, grad, n: int, w_max: float) -> tuple[np.ndarray, bool]:
    x0 = np.full(n, 1.0 / n)
    res = _minimize(
        objective,
        x0,
        method="SLSQP",
        jac=grad,
        bounds=[(0.0, w_max)] * n,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones(n)}],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    w = np.clip(res.x, 0.0, w_max)
    w = w / w.sum()
    return w, bool(res.success)


def _project_capped(w: np.ndarray, w_max: float) -> np.ndarray:
    """Project weights onto the capped simplex: [0, w_max] and sum == 1 (water-filling)."""
    n = len(w)
    w = np.clip(np.asarray(w, dtype=float), 0.0, None).copy()
    if w.sum() <= 0:
        return np.full(n, 1.0 / n)
    w = w / w.sum()
    for _ in range(200):
        over = w > w_max + 1e-12
        if not over.any():
            break
        w[over] = w_max
        free = ~over
        deficit = 1.0 - float(w.sum())
        if deficit <= 1e-15:
            break
        if not free.any() or w[free].sum() <= 0:
            if not free.any():
                return np.full(n, 1.0 / n)
            w[free] = deficit / float(free.sum())
            break
        w[free] += deficit * (w[free] / w[free].sum())
    return w


def equal_weight(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


def min_variance_weights(cov: np.ndarray, w_max: float) -> tuple[np.ndarray, bool]:
    n = len(cov)
    cov = np.asarray(cov, dtype=float)

    def f(w):
        return float(w @ cov @ w)

    def g(w):
        return 2.0 * (cov @ w)

    return _simplex_solve(f, g, n, w_max)


def mvo_weights(mu: np.ndarray, cov: np.ndarray, gamma: float, w_max: float) -> tuple[np.ndarray, bool]:
    """Maximize w'mu - gamma/2 * w'covw under long-only + cap constraints."""
    n = len(cov)
    cov = np.asarray(cov, dtype=float)
    mu = np.asarray(mu, dtype=float)
    gamma = max(0.1, float(gamma))

    def f(w):
        return float(-w @ mu + 0.5 * gamma * w @ cov @ w)

    def g(w):
        return -mu + gamma * (cov @ w)

    return _simplex_solve(f, g, n, w_max)


def _erc_uncapped(cov: np.ndarray) -> np.ndarray:
    """Uncapped equal-risk-contribution weights via log-space Newton.

    Solves w_i (Σw)_i == c for all i (c = mean risk contribution) on the
    simplex, using y = log-weights (softmax keeps the simplex feasible).
    Deterministic: zero start, backtracking line search."""
    n = len(cov)
    y = np.zeros(n)

    def _softmax(yy: np.ndarray) -> np.ndarray:
        m = float(np.max(yy))
        e = np.exp(yy - m)
        return e / e.sum()

    def _F(yy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        w = _softmax(yy)
        port = cov @ w
        rc = w * port
        return rc - float(rc.mean()), w

    F, w = _F(y)
    for _ in range(200):
        if float(np.max(np.abs(F))) < 1e-13 * max(1.0, abs(float(F.mean())) + 1e-300):
            break
        port = cov @ w
        J = np.empty((n, n))
        for i in range(n):
            J[i] = w[i] * (port[i] * np.eye(n)[i] - w * port[i] + cov[i, i] * cov[i] - port[i] * cov[i])
        try:
            step = np.linalg.solve(J, -F)
        except np.linalg.LinAlgError:
            break
        t = 1.0
        for _ in range(30):
            y_try = y + t * step
            F_try, w_try = _F(y_try)
            if float(np.max(np.abs(F_try))) < float(np.max(np.abs(F))) or t < 1e-8:
                F, w, y = F_try, w_try, y_try
                break
            t /= 2.0
        else:
            break
    return w


def risk_parity_weights(cov: np.ndarray, w_max: float) -> tuple[np.ndarray, bool]:
    """Equal-risk-contribution (ERC) portfolio, with a weight cap if needed.

    Uncapped ERC is solved exactly (Newton, log-space). If the cap binds,
    the violating assets are pinned at w_max and the remaining budget is
    allocated as ERC over the uncapped set (standard capped-ERC behavior).
    """
    n = len(cov)
    w_max = max(w_max, 1.0 / n)
    w = _erc_uncapped(cov)
    if float(w.max()) <= w_max + 1e-12:
        return _project_capped(w, w_max), True
    pinned = w > w_max
    free_idx = np.where(~pinned)[0]
    budget = 1.0 - int(pinned.sum()) * w_max
    if len(free_idx) == 0 or budget <= 0:
        return _project_capped(w, w_max), True
    w_free = _erc_uncapped(cov[np.ix_(free_idx, free_idx)])
    out = np.zeros(n)
    out[pinned] = w_max
    out[free_idx] = w_free * budget
    out = _project_capped(out, w_max)
    feasible = abs(float(out.sum()) - 1.0) < 1e-9 and float(out.max()) <= w_max + 1e-9
    return out, feasible


def portfolio_risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    port_vol = math.sqrt(max(float(w @ cov @ w), 1e-18))
    return w * (cov @ w) / port_vol


def fit_weights(candidate: str, window_ret: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any]:
    """Fit one candidate on a train window. Deterministic; no lookahead."""
    window_ret = np.asarray(window_ret, dtype=float)
    n = window_ret.shape[1]
    w_max = max(1.0 / n, float(cfg.get("weight_max", 0.5)))
    cov, delta = oas_covariance(window_ret)
    out: dict[str, Any] = {"candidate": candidate, "oas_delta": _safe_float(delta), "n_train_bars": int(window_ret.shape[0])}
    if candidate == "equal_weight":
        w, ok = equal_weight(n), True
    elif candidate == "min_variance":
        w, ok = min_variance_weights(cov, w_max)
    elif candidate == "mvo_shrinkage":
        mu = window_ret.mean(axis=0)
        w, ok = mvo_weights(mu, cov, float(cfg.get("risk_aversion_gamma", 2.0)), w_max)
    elif candidate == "risk_parity":
        w, ok = risk_parity_weights(cov, w_max)
    else:
        raise ValueError(f"unknown candidate: {candidate}")
    out["weights"] = _project_capped(w, w_max)
    out["solver_ok"] = ok or False
    return out


# ---------------------------------------------------------------------------
# walk-forward OOS accounting with next-open style costs
# ---------------------------------------------------------------------------

def _walkforward_bounds(T: int, cfg: dict[str, Any]) -> tuple[int, list[tuple[int, int]]]:
    T = int(T)
    folds = max(1, int(cfg.get("walkforward_folds", 3)))
    train_len = int(round(T * float(cfg.get("train_fraction", 0.5))))
    train_len = min(max(train_len, 30), T - folds)
    oos_total = T - train_len
    if oos_total < folds:
        raise ValueError(f"not enough bars for {folds} walk-forward folds (T={T})")
    base, rem = divmod(oos_total, folds)
    spans, start = [], train_len
    for k in range(folds):
        length = base + (1 if rem and k == folds - 1 else 0)
        spans.append((start, start + length))
        start += length
    return train_len, spans


def _equity_run(rets: np.ndarray, folds: list[tuple[int, int]], symbols: list[str],
                cfg: dict[str, Any], candidate: str, bpy: float,
                record_curves: bool = False) -> dict[str, Any]:
    """Apply fold weights across OOS spans. Weights decided at the close of
    the last train/fold bar fill at the next open, so they accrue from the
    first OOS return row of each span; rebalance cost is charged on that bar."""
    fee = float(cfg.get("fee_rate", 0.001))
    slip = float(cfg.get("slippage_bps", 2.0)) / 10_000.0
    initial = float(cfg.get("initial_quote", 10000.0))

    # Decide each fold's weights from past data only.
    fold_specs = []
    for k, (a, b) in enumerate(folds):
        fit = rets[:a]
        if fit.shape[0] < 30:
            raise ValueError("train window too short for covariance estimation")
        fit_out = fit_weights(candidate, fit, cfg)
        fold_specs.append({"k": k, "a": int(a), "b": int(b), "w": fit_out["weights"], "fit": fit_out})

    turnover_total = 0.0
    costs_quote = 0.0
    net = initial
    gross = initial
    prev_w = np.zeros(rets.shape[1])
    equity_net: list[float] = [initial]
    equity_gross: list[float] = [initial]
    fold_details = []
    for spec in fold_specs:
        a, b, w = spec["a"], spec["b"], spec["w"]
        turnover = float(np.abs(w - prev_w).sum())  # k=0 deploys from full cash
        cost_frac = turnover * (fee + slip)
        turnover_total += turnover
        seg_start = net
        costs_quote += cost_frac * seg_start
        prev_w = w
        for t in range(a, b):
            mult = 1.0 + float(w @ rets[t])
            gross *= mult
            if t == a:
                mult *= 1.0 - cost_frac
            net *= mult
            equity_net.append(net)
            equity_gross.append(gross)
        fold_details.append({
            "fold": spec["k"],
            "span": [a, b],
            "net_return_pct": _safe_float((net / seg_start - 1.0) * 100),
            "turnover_one_sided": _safe_float(turnover),
            "cost_frac_pct": _safe_float(cost_frac * 100),
            "solver_ok": spec["fit"]["solver_ok"],
            "oas_delta": spec["fit"]["oas_delta"],
            "weights": {sym: _safe_float(round(float(x), 6)) for sym, x in zip(symbols, w)},
        })
    metrics = _metrics(np.array(equity_net), bpy)
    out = {
        "initial_quote": _safe_float(initial),
        "final_quote": _safe_float(net),
        "gross_quote": _safe_float(gross),
        "gross_return_pct": _safe_float((gross / initial - 1.0) * 100),
        "net_return_pct": _safe_float((net / initial - 1.0) * 100),
        "total_turnover_one_sided": _safe_float(turnover_total),
        "costs_quote": _safe_float(costs_quote),
        "metrics": metrics,
        "folds": fold_details,
    }
    if record_curves:
        out["net_curve"] = equity_net[1:]
        out["gross_curve"] = equity_gross[1:]
    return out


def _metrics(equity: np.ndarray, bpy: float) -> dict[str, Any]:
    rets = np.diff(equity) / equity[:-1]
    total = float(equity[-1] / equity[0] - 1.0)
    n = len(rets)
    peak = np.maximum.accumulate(equity)
    dd = float(((equity - peak) / peak).min())
    mean_r = float(rets.mean())
    std_r = float(rets.std(ddof=1)) if n > 1 else 0.0
    return {
        "return_pct": _safe_float(total * 100),
        "annualized_return_pct": _safe_float(((1 + total) ** (bpy / n) - 1) * 100 if total > -1 else None),
        "annualized_vol_pct": _safe_float(std_r * math.sqrt(bpy) * 100 if n > 1 else None),
        "sharpe": _safe_float(mean_r / std_r * math.sqrt(bpy) if std_r > 0 else None),
        "max_drawdown_pct": _safe_float(dd * 100),
    }


def portfolio_report(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                     annualization: str = "crypto_24x7") -> dict[str, Any]:
    cfg = {**default_portfolio_cfg(), **(cfg or {})}
    symbols = [str(c) for c in closes.columns]
    rets = closes.pct_change().values
    T = len(rets) - 1  # first row is NaN
    if T < 100:
        raise ValueError(f"portfolio research needs >= 100 aligned bars, got {T}")
    if len(symbols) < 4:
        raise ValueError(f"portfolio research needs >= 4 aligned assets, got {len(symbols)}")
    R = np.nan_to_num(rets[1:], nan=0.0)
    bpy = bars_per_year(interval, annualization)
    train_len, spans = _walkforward_bounds(T, cfg)
    known = set(default_portfolio_cfg()["candidates"])
    candidates = [str(c) for c in cfg.get("candidates", default_portfolio_cfg()["candidates"])]
    unknown = [c for c in candidates if c not in known]
    if unknown:
        raise ValueError(f"unknown portfolio candidate(s): {unknown}")
    if not candidates:
        candidates = ["mvo_shrinkage"]
    runs: dict[str, Any] = {}
    for cand in candidates:
        runs[cand] = _equity_run(R, spans, symbols, cfg, cand, bpy)
    bench = runs.get("equal_weight") or _equity_run(R, spans, symbols, cfg, "equal_weight", bpy)

    # Per-asset buy & hold over the OOS span (gross — no costs, entry proxy is
    # the close at the first OOS bar; labeled as a benchmark, not a strategy).
    oos_closes = closes.iloc[spans[0][0]:]  # close rows from first OOS bar
    bh = {sym: _safe_float(float(oos_closes[sym].iloc[-1] / oos_closes[sym].iloc[0] - 1.0) * 100) for sym in symbols}

    # ---- final structured payload ----
    payload: dict[str, Any] = {
        "universe": symbols,
        "bars": int(T),
        "interval": str(interval),
        "annualization": str(annualization),
        "bars_per_year": _safe_float(bpy),
        "train_len_bars": int(train_len),
        "folds": [f"{a}:{b}" for a, b in spans],
        "candidates": list(candidates),
        "weight_max": _safe_float(cfg.get("weight_max")),
        "risk_aversion_gamma": _safe_float(cfg.get("risk_aversion_gamma")),
        "fee_rate": _safe_float(cfg.get("fee_rate")),
        "slippage_bps": _safe_float(cfg.get("slippage_bps")),
        "benchmark_equal_weight": {
            "net_return_pct": bench["net_return_pct"],
            "gross_return_pct": bench["gross_return_pct"],
            "metrics": bench["metrics"],
            "total_turnover_one_sided": bench["total_turnover_one_sided"],
            "costs_quote": bench["costs_quote"],
            "folds": bench["folds"],
        },
        "buy_and_hold_pct": bh,
        "candidates_report": {},
        "verdict": {},
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "discipline_note": (
            "Walk-forward portfolio candidates. Weights are fitted on expanding train windows only, "
            "rebalanced once per fold with next-open style cost accounting. 6-asset universe is "
            "exploratory; OOS evidence must pass the Promotion Gate before execution."
        ),
    }
    for cand in candidates:
        r = runs[cand]
        payload["candidates_report"][cand] = r
        beats = (r["net_return_pct"] is not None and bench["net_return_pct"] is not None
                 and r["net_return_pct"] > bench["net_return_pct"])
        payload["verdict"][cand] = {
            "beats_equal_weight_net": bool(beats),
            "net_return_pct": r["net_return_pct"],
            "gross_return_pct": r["gross_return_pct"],
            "oos_positive_fold_ratio": _safe_float(
                sum(1 for f in r["folds"] if (f["net_return_pct"] or 0) > 0) / len(r["folds"])
            ),
            "total_turnover_one_sided": r["total_turnover_one_sided"],
        }
    return payload


def portfolio_curves(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                     annualization: str = "crypto_24x7") -> dict[str, Any]:
    """Bar-level OOS equity curves for charting (not archived into runs).

    Same math as portfolio_report; additionally returns per-bar net/gross
    equity for each candidate (equal_weight is always included as the
    benchmark), OOS close timestamps, fold boundaries, and per-asset OOS
    price series for buy & hold overlays.
    """
    cfg = {**default_portfolio_cfg(), **(cfg or {})}
    symbols = [str(c) for c in closes.columns]
    rets = closes.pct_change().values
    T = len(rets) - 1
    if T < 100:
        raise ValueError(f"portfolio research needs >= 100 aligned bars, got {T}")
    if len(symbols) < 4:
        raise ValueError(f"portfolio research needs >= 4 aligned assets, got {len(symbols)}")
    R = np.nan_to_num(rets[1:], nan=0.0)
    bpy = bars_per_year(interval, annualization)
    train_len, spans = _walkforward_bounds(T, cfg)
    known = set(default_portfolio_cfg()["candidates"])
    candidates = [str(c) for c in cfg.get("candidates", default_portfolio_cfg()["candidates"])]
    unknown = [c for c in candidates if c not in known]
    if unknown:
        raise ValueError(f"unknown portfolio candidate(s): {unknown}")
    all_cands = list(candidates) + (["equal_weight"] if "equal_weight" not in candidates else [])

    curves: dict[str, Any] = {}
    for cand in all_cands:
        run = _equity_run(R, spans, symbols, cfg, cand, bpy, record_curves=True)
        curves[cand] = {
            "net": [round(float(x), 2) for x in run["net_curve"]],
            "gross": [round(float(x), 2) for x in run["gross_curve"]],
            "net_return_pct": run["net_return_pct"],
            "metrics": run["metrics"],
            "folds": run["folds"],
        }
    oos_closes = closes.iloc[spans[0][0]:]
    # net_curve[i] is the equity after return row spans[0][0]+i, i.e. at close
    # C[spans[0][0]+1+i] — align timestamps with the curves, not the entry bar.
    oos_times = [str(t) for t in closes.index[spans[0][0] + 1:]]
    return {
        "universe": symbols,
        "oos_times": oos_times,
        "folds": [[int(a), int(b)] for a, b in spans],
        "train_len_bars": int(train_len),
        "initial_quote": float(cfg.get("initial_quote", 10000.0)),
        "bars_per_year": _safe_float(bpy),
        "candidates": curves,
        "buy_hold_prices": {sym: [round(float(x), 2) for x in oos_closes[sym].values] for sym in symbols},
    }


# ---------------------------------------------------------------------------
# CAPM / SML diagnostics
# ---------------------------------------------------------------------------

def capm_report(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                annualization: str = "crypto_24x7") -> dict[str, Any]:
    cfg = {**default_portfolio_cfg(), **(cfg or {})}
    symbols = [str(c) for c in closes.columns]
    rets = closes.pct_change().dropna(how="any")
    if len(rets) < 30:
        raise ValueError(f"CAPM research needs >= 30 aligned bars, got {len(rets)}")
    bpy = bars_per_year(interval, annualization)
    market_model = str(cfg.get("market_model", "ew")).lower()
    if market_model == "btc":
        if "BTCUSDT" not in symbols:
            raise ValueError("market_model=btc requires BTCUSDT in the universe")
        mret = rets["BTCUSDT"].values
        market_name = "BTCUSDT"
    else:
        mret = rets.mean(axis=1).values
        market_name = "equal-weight universe index"

    R = rets.values
    T = len(R)
    rows = []
    betas, means = [], []
    for j, sym in enumerate(symbols):
        r = R[:, j]
        ss_xx = float(np.sum((mret - mret.mean()) ** 2))
        beta = float(np.sum((mret - mret.mean()) * (r - r.mean())) / ss_xx) if ss_xx > 0 else 0.0
        alpha_bar = float(r.mean() - beta * mret.mean())
        resid = r - (alpha_bar + beta * mret)
        ssr = float(np.sum(resid ** 2))
        sse_df = max(T - 2, 1)
        sigma2 = ssr / sse_df
        tstat = alpha_bar / math.sqrt(sigma2 * (1.0 / T + float(mret.mean()) ** 2 / ss_xx)) if ss_xx > 0 else None
        sst = float(np.sum((r - r.mean()) ** 2))
        r2 = 1.0 - ssr / sst if sst > 0 else None
        rows.append({
            "symbol": sym,
            "beta": _safe_float(beta),
            "alpha_ann_pct": _safe_float(alpha_bar * bpy * 100),
            "alpha_t": _safe_float(tstat),
            "r2": _safe_float(r2),
            "ann_return_pct": _safe_float(float(r.mean()) * bpy * 100),
            "ann_vol_pct": _safe_float(float(np.std(r, ddof=1)) * math.sqrt(bpy) * 100 if T > 1 else None),
            "capm_implied_ann_pct": _safe_float(beta * float(mret.mean()) * bpy * 100),  # Rf = 0
        })
        betas.append(beta)
        means.append(float(r.mean()) * bpy)
    betas = np.array(betas)
    means = np.array(means)
    x = np.column_stack([np.ones(len(betas)), betas])
    (sml_a, sml_b), *_ = np.linalg.lstsq(x, means, rcond=None)
    resid = means - x @ np.array([sml_a, sml_b])
    sst = float(np.sum((means - means.mean()) ** 2))
    sml_r2 = 1.0 - float(np.sum(resid ** 2)) / sst if sst > 0 else None
    t_thresh = float(cfg.get("capm_alpha_t", 2.0))
    sig = [row["symbol"] for row in rows if row["alpha_t"] is not None and abs(row["alpha_t"]) >= t_thresh]
    sml_ok = sml_r2 is not None and sml_r2 >= float(cfg.get("capm_min_sml_r2", 0.6))
    payload = {
        "universe": symbols,
        "bars": int(T),
        "interval": str(interval),
        "annualization": str(annualization),
        "bars_per_year": _safe_float(bpy),
        "market_model": market_model,
        "market_proxy": market_name,
        "market_ann_return_pct": _safe_float(float(mret.mean()) * bpy * 100),
        "assets": rows,
        "sml": {
            "annualized_intercept_pct": _safe_float(sml_a * 100),
            "annualized_slope_pct_per_beta": _safe_float(sml_b * 100),
            "r2": _safe_float(sml_r2),
            "minimum_r2": _safe_float(cfg.get("capm_min_sml_r2", 0.6)),
        },
        "verdict": {
            "alpha_threshold_t": t_thresh,
            "significant_alphas": sig,
            "sml_fit_ok": bool(sml_ok),
            "supports_capm_pricing": bool(sml_ok and not sig),
            "note": (
                "Two-pass simplified CAPM on a 6-asset universe. A passing SML fit with no significant "
                "alphas means cross-sectional mean returns are priced by beta alone; significant alphas "
                "mark CAPM deviations and factor-research leads."
            ),
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    return payload


def analyze_portfolio_research(closes: pd.DataFrame, cfg: dict[str, Any], interval: str,
                               annualization: str = "crypto_24x7") -> dict[str, Any]:
    """Top-level entry used by run.py: run both CAPM and portfolio in one report."""
    capm = capm_report(closes, cfg, interval, annualization)
    portfolio = portfolio_report(closes, cfg, interval, annualization)
    return {"capm": capm, "portfolio": portfolio}
