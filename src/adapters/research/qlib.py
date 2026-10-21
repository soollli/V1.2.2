from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import importlib.metadata
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from ...core.contracts import AdapterInfo


class QlibUnavailable(RuntimeError):
    pass


@dataclass
class _CanonicalQlibDataset:
    """Minimal Qlib Dataset-compatible wrapper around the terminal's canonical panel."""

    frame: pd.DataFrame
    segments: dict[str, tuple[pd.Timestamp, pd.Timestamp]]

    def _slice(self, segment: str | slice) -> pd.DataFrame:
        if isinstance(segment, str):
            if segment not in self.segments:
                raise KeyError(segment)
            start, end = self.segments[segment]
            idx = self.frame.index.get_level_values("datetime")
            return self.frame[(idx >= start) & (idx <= end)]
        if isinstance(segment, slice):
            idx = self.frame.index.get_level_values("datetime")
            start = pd.Timestamp(segment.start, tz="UTC") if segment.start is not None else idx.min()
            end = pd.Timestamp(segment.stop, tz="UTC") if segment.stop is not None else idx.max()
            return self.frame[(idx >= start) & (idx <= end)]
        raise TypeError(f"unsupported segment: {type(segment).__name__}")

    def prepare(self, segment, col_set="feature", data_key=None):
        if isinstance(segment, (list, tuple)):
            return [self.prepare(x, col_set=col_set, data_key=data_key) for x in segment]
        df = self._slice(segment)
        if col_set in (None, "__all"):
            return df.copy()
        if isinstance(col_set, str):
            return df[col_set].copy()
        if isinstance(col_set, (list, tuple)):
            return pd.concat([df[x] for x in col_set], axis=1, keys=list(col_set))
        raise TypeError(f"unsupported col_set: {type(col_set).__name__}")


def _safe_spearman(a: pd.Series, b: pd.Series) -> float | None:
    x = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(x) < 3 or x["a"].nunique() < 2 or x["b"].nunique() < 2:
        return None
    v = x["a"].corr(x["b"], method="spearman")
    return None if pd.isna(v) else float(v)


def _feature_panel(
    closes: pd.DataFrame,
    *,
    momentum_fast: int = 5,
    momentum_slow: int = 20,
    vol_period: int = 20,
    min_assets: int = 3,
) -> pd.DataFrame:
    if closes is None or closes.empty:
        raise ValueError("close matrix is empty")
    px = closes.copy().sort_index()
    px = px.apply(pd.to_numeric, errors="coerce")
    px.index = pd.to_datetime(px.index, utc=True)
    px = px.dropna(axis=1, how="all")
    if px.shape[1] < min_assets:
        raise ValueError(f"Qlib ML research needs at least {min_assets} assets")

    ret1 = px.pct_change()
    mom_fast = px.pct_change(momentum_fast)
    mom_slow = px.pct_change(momentum_slow)
    vol = ret1.rolling(vol_period).std()
    reversal = -mom_fast
    rank_mom = mom_slow.rank(axis=1, pct=True) - 0.5
    rank_vol = -(vol.rank(axis=1, pct=True) - 0.5)

    matrices = {
        "ret_1": ret1,
        f"mom_{momentum_fast}": mom_fast,
        f"mom_{momentum_slow}": mom_slow,
        f"vol_{vol_period}": vol,
        f"reversal_{momentum_fast}": reversal,
        f"rank_mom_{momentum_slow}": rank_mom,
        f"rank_lowvol_{vol_period}": rank_vol,
    }
    rows = []
    for symbol in px.columns:
        block = pd.DataFrame({name: mat[symbol] for name, mat in matrices.items()}, index=px.index)
        block["instrument"] = symbol
        block["datetime"] = block.index
        rows.append(block.reset_index(drop=True))
    out = pd.concat(rows, ignore_index=True)
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    if out.empty:
        raise ValueError("Qlib feature panel is empty after warm-up")
    return out.set_index(["datetime", "instrument"]).sort_index().astype(float)


def build_qlib_panel(
    closes: pd.DataFrame,
    *,
    forward_bars: int = 5,
    momentum_fast: int = 5,
    momentum_slow: int = 20,
    vol_period: int = 20,
    min_assets: int = 3,
) -> pd.DataFrame:
    """Build a labeled Qlib-style panel with index (datetime, instrument)."""
    features = _feature_panel(
        closes,
        momentum_fast=momentum_fast,
        momentum_slow=momentum_slow,
        vol_period=vol_period,
        min_assets=min_assets,
    )
    px = closes.copy().sort_index().apply(pd.to_numeric, errors="coerce")
    px.index = pd.to_datetime(px.index, utc=True)
    fwd = px.shift(-int(forward_bars)) / px - 1.0
    label = fwd.stack(future_stack=True).rename("LABEL0")
    label.index.names = ["datetime", "instrument"]
    joined = features.join(label, how="left").replace([np.inf, -np.inf], np.nan).dropna()
    if joined.empty:
        raise ValueError("Qlib panel is empty after feature warm-up/label shift")
    return pd.concat({"feature": joined[features.columns], "label": joined[["LABEL0"]]}, axis=1)


def split_panel(
    panel: pd.DataFrame,
    train_fraction: float = 0.60,
    valid_fraction: float = 0.20,
    *,
    purge_bars: int = 0,
    embargo_bars: int = 0,
    return_meta: bool = False,
):
    """Chronological train/valid/test split with label-boundary purge/embargo.

    Purge removes observations before each future segment so a t->t+h label in
    train/valid cannot read prices that belong to validation/test.
    """
    times = pd.Index(panel.index.get_level_values("datetime").unique()).sort_values()
    if len(times) < 30:
        raise ValueError("Qlib ML research needs at least 30 aligned timestamps after feature warm-up")
    purge = max(0, int(purge_bars))
    embargo = max(0, int(embargo_bars))
    n = len(times)
    train_cut = max(12, int(n * float(train_fraction)))
    valid_len = max(6, int(n * float(valid_fraction)))
    valid_cut = min(n - 4, train_cut + valid_len)

    train_end_i = train_cut - purge - 1
    valid_start_i = train_cut + embargo
    valid_end_i = valid_cut - purge - 1
    test_start_i = valid_cut + embargo
    if train_end_i < 9 or valid_start_i > valid_end_i or test_start_i >= n:
        raise ValueError(
            f"not enough timestamps after purge/embargo: n={n} purge={purge} embargo={embargo}"
        )
    segments = {
        "train": (pd.Timestamp(times[0]), pd.Timestamp(times[train_end_i])),
        "valid": (pd.Timestamp(times[valid_start_i]), pd.Timestamp(times[valid_end_i])),
        "test": (pd.Timestamp(times[test_start_i]), pd.Timestamp(times[-1])),
    }
    meta = {
        "purge_bars": purge,
        "embargo_bars": embargo,
        "train_cut_index": train_cut,
        "valid_cut_index": valid_cut,
        "purged_before_valid": max(0, valid_start_i - train_end_i - 1),
        "purged_before_test": max(0, test_start_i - valid_end_i - 1),
        "timestamp_count": n,
    }
    return (segments, meta) if return_meta else segments


def _feature_transform(panel: pd.DataFrame, segments: dict, winsor_q: float = 0.01):
    """Fit clipping/standardization only on train, then transform all segments."""
    train_start, train_end = segments["train"]
    idx = panel.index.get_level_values("datetime")
    train = panel.loc[(idx >= train_start) & (idx <= train_end), "feature"].copy()
    if train.empty:
        raise ValueError("empty training features")
    q = max(0.0, min(float(winsor_q), 0.20))
    lower = train.quantile(q) if q > 0 else pd.Series(-np.inf, index=train.columns)
    upper = train.quantile(1.0 - q) if q > 0 else pd.Series(np.inf, index=train.columns)
    clipped_train = train.clip(lower=lower, upper=upper, axis=1)
    mean = clipped_train.mean()
    std = clipped_train.std(ddof=0).replace(0, 1.0).fillna(1.0)

    out = panel.copy()
    feat = out["feature"].clip(lower=lower, upper=upper, axis=1)
    transformed = (feat - mean) / std
    # Assign column-by-column to avoid pandas MultiIndex alignment quirks.
    for col in transformed.columns:
        out[("feature", col)] = transformed[col].to_numpy()
    stats = {
        "winsor_quantile": q,
        "fit_segment": "train_only",
        "mean": {str(k): float(v) for k, v in mean.items()},
        "std": {str(k): float(v) for k, v in std.items()},
        "lower": {str(k): float(v) for k, v in lower.items()},
        "upper": {str(k): float(v) for k, v in upper.items()},
    }
    return out, stats


def _transform_current(features: pd.DataFrame, stats: dict) -> pd.DataFrame:
    cols = list(features.columns)
    lower = pd.Series(stats["lower"]).reindex(cols)
    upper = pd.Series(stats["upper"]).reindex(cols)
    mean = pd.Series(stats["mean"]).reindex(cols)
    std = pd.Series(stats["std"]).reindex(cols).replace(0, 1.0)
    return (features.clip(lower=lower, upper=upper, axis=1) - mean) / std


def _prediction_metrics(pred: pd.Series, labels: pd.Series) -> dict[str, Any]:
    joined = pd.concat([pred.rename("score"), labels.rename("label")], axis=1).dropna()
    if joined.empty:
        return {"samples": 0, "ic_mean": None, "icir": None, "ic_positive_pct": None, "mse": None}
    mse = float(((joined["score"] - joined["label"]) ** 2).mean())
    ics = []
    for _, grp in joined.groupby(level="datetime"):
        ic = _safe_spearman(grp["score"], grp["label"])
        if ic is not None:
            ics.append(ic)
    ic_mean = float(np.mean(ics)) if ics else None
    ic_std = float(np.std(ics, ddof=1)) if len(ics) > 1 else None
    icir = float(ic_mean / ic_std) if ic_mean is not None and ic_std not in (None, 0) else None
    positive = float(np.mean(np.array(ics) > 0) * 100) if ics else None
    return {
        "samples": int(len(joined)),
        "timestamps": int(joined.index.get_level_values("datetime").nunique()),
        "ic_observations": int(len(ics)),
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "icir": icir,
        "ic_positive_pct": positive,
        "overall_spearman": _safe_spearman(joined["score"], joined["label"]),
        "mse": mse,
    }


def _top_bottom_spread(pred: pd.Series, labels: pd.Series, frac: float = 0.30) -> dict[str, Any]:
    joined = pd.concat([pred.rename("score"), labels.rename("label")], axis=1).dropna()
    spreads = []
    for _, grp in joined.groupby(level="datetime"):
        if len(grp) < 4:
            continue
        n = max(1, int(math.ceil(len(grp) * frac)))
        ranked = grp.sort_values("score")
        spreads.append(float(ranked.tail(n)["label"].mean() - ranked.head(n)["label"].mean()))
    return {
        "observations": len(spreads),
        "mean_forward_spread_pct": float(np.mean(spreads) * 100) if spreads else None,
        "positive_spread_pct": float(np.mean(np.array(spreads) > 0) * 100) if spreads else None,
    }


def _selection_key(metrics: dict[str, Any]) -> tuple:
    ic = metrics.get("ic_mean")
    mse = metrics.get("mse")
    return (ic is not None, float(ic) if ic is not None else -1e99, -float(mse) if mse is not None else -1e99)


class QlibResearchAdapter:
    info = AdapterInfo(
        kind="ml_research",
        name="qlib",
        provider="Microsoft Qlib",
        description="Qlib forecast-model adapter with purged time splits and candidate-only promotion",
        live_money=False,
    )

    def __init__(self, model_factory: Callable[..., Any] | None = None):
        self._model_factory = model_factory

    @staticmethod
    def package_detected() -> bool:
        return importlib.util.find_spec("qlib") is not None

    @staticmethod
    def version() -> str | None:
        for name in ("pyqlib", "qlib"):
            try:
                return importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                continue
        return None

    def _factory(self):
        if self._model_factory is not None:
            return self._model_factory
        if not self.package_detected():
            raise QlibUnavailable("Qlib is not installed. Run: pip install -r requirements-qlib.txt")
        try:
            return importlib.import_module("qlib.contrib.model.linear").LinearModel
        except Exception as exc:
            raise QlibUnavailable(f"Qlib LinearModel unavailable: {type(exc).__name__}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        detected = self.package_detected() if self._model_factory is None else True
        return {
            "ok": bool(detected),
            "adapter": self.info.name,
            "package_detected": detected,
            "version": self.version() if self._model_factory is None else "test-runtime",
            "model": "qlib.contrib.model.linear.LinearModel",
            "data_mode": "terminal_canonical_dataframe_dataset",
            "uses_qlib_bin_store": False,
            "purged_time_split": True,
            "validation_model_selection": True,
            "current_inference_separated_from_labeled_test": True,
            "promotion_policy": "candidate_only_until_native_oos_walkforward_passes",
        }

    def ml_report(self, closes: pd.DataFrame, cfg: dict | None = None) -> dict[str, Any]:
        cfg = dict(cfg or {})
        forward = int(cfg.get("forward_bars", 5))
        kwargs = dict(
            momentum_fast=int(cfg.get("momentum_fast", 5)),
            momentum_slow=int(cfg.get("momentum_slow", 20)),
            vol_period=int(cfg.get("vol_period", 20)),
            min_assets=int(cfg.get("min_assets", 5)),
        )
        panel = build_qlib_panel(closes, forward_bars=forward, **kwargs)
        segments, split_meta = split_panel(
            panel,
            train_fraction=float(cfg.get("train_fraction", 0.60)),
            valid_fraction=float(cfg.get("valid_fraction", 0.20)),
            purge_bars=int(cfg.get("purge_bars", forward)),
            embargo_bars=int(cfg.get("embargo_bars", 1)),
            return_meta=True,
        )
        panel, transform_stats = _feature_transform(panel, segments, winsor_q=float(cfg.get("winsor_quantile", 0.01)))
        dataset = _CanonicalQlibDataset(panel, segments)
        estimator = str(cfg.get("estimator", "ridge")).lower()
        base_alpha = float(cfg.get("alpha", 1.0 if estimator in {"ridge", "lasso"} else 0.0))
        alpha_grid = cfg.get("alpha_grid", [0.01, 0.1, 1.0, 10.0] if estimator in {"ridge", "lasso"} else [base_alpha])
        alphas = sorted({float(x) for x in alpha_grid}) if estimator in {"ridge", "lasso"} else [0.0]
        factory = self._factory()

        validation_rows = []
        best = None
        valid_labels = dataset.prepare("valid", col_set="label").iloc[:, 0]
        for alpha in alphas:
            model = factory(
                estimator=estimator,
                alpha=alpha,
                fit_intercept=bool(cfg.get("fit_intercept", True)),
                include_valid=False,
            )
            model.fit(dataset)
            valid_pred = model.predict(dataset, segment="valid")
            metrics = _prediction_metrics(valid_pred, valid_labels)
            row = {"alpha": alpha, **metrics}
            validation_rows.append(row)
            key = _selection_key(metrics)
            if best is None or key > best[0]:
                best = (key, alpha)
        selected_alpha = best[1] if best is not None else base_alpha

        # Refit selected model on train+valid; Qlib LinearModel explicitly uses
        # include_valid=True for this final fit. Test remains untouched.
        model = factory(
            estimator=estimator,
            alpha=selected_alpha,
            fit_intercept=bool(cfg.get("fit_intercept", True)),
            include_valid=True,
        )
        model.fit(dataset)
        pred = model.predict(dataset, segment="test")
        labels = dataset.prepare("test", col_set="label").iloc[:, 0]
        metrics = _prediction_metrics(pred, labels)
        spread = _top_bottom_spread(pred, labels, frac=float(cfg.get("portfolio_fraction", 0.30)))

        labeled = pd.concat([pred.rename("score"), labels.rename("label")], axis=1).dropna()
        labeled_rows = []
        labeled_timestamp = None
        if not labeled.empty:
            labeled_timestamp = labeled.index.get_level_values("datetime").max()
            tail = labeled.xs(labeled_timestamp, level="datetime").sort_values("score", ascending=False)
            for symbol, row in tail.head(20).iterrows():
                labeled_rows.append({
                    "symbol": str(symbol),
                    "score": float(row["score"]),
                    "realized_forward_return_pct": float(row["label"] * 100),
                })

        # Current inference deliberately uses feature-only rows at the latest
        # available timestamp. It has no future return label by definition.
        current_features = _feature_panel(closes, **kwargs)
        current_t = current_features.index.get_level_values("datetime").max()
        current_raw = current_features.xs(current_t, level="datetime", drop_level=False)
        current_x = _transform_current(current_raw, transform_stats)
        current_frame = pd.concat(
            {
                "feature": current_x,
                "label": pd.DataFrame({"LABEL0": np.nan}, index=current_x.index),
            },
            axis=1,
        )
        current_dataset = _CanonicalQlibDataset(current_frame, {"current": (pd.Timestamp(current_t), pd.Timestamp(current_t))})
        current_pred = model.predict(current_dataset, segment="current").sort_values(ascending=False)
        current_rows = [
            {"symbol": str(symbol), "score": float(score), "realized_forward_return_pct": None}
            for (_, symbol), score in current_pred.head(20).items()
        ]

        return {
            "engine": "qlib",
            "provider": "Microsoft Qlib",
            "qlib_version": self.version() if self._model_factory is None else "test-runtime",
            "model": {
                "class": "qlib.contrib.model.linear.LinearModel",
                "estimator": estimator,
                "selected_alpha": selected_alpha,
                "fit_intercept": bool(cfg.get("fit_intercept", True)),
                "final_fit_uses_train_plus_valid": True,
            },
            "validation_selection": {
                "criterion": "maximize cross-sectional validation IC; tie-break lower MSE",
                "candidates": validation_rows,
                "selected_alpha": selected_alpha,
            },
            "dataset": {
                "mode": "terminal_canonical_dataframe_dataset",
                "assets": int(closes.shape[1]),
                "input_timestamps": int(len(closes)),
                "panel_rows": int(len(panel)),
                "feature_count": int(panel["feature"].shape[1]),
                "features": [str(x) for x in panel["feature"].columns],
                "forward_bars": forward,
                "segments": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in segments.items()},
                "split_integrity": split_meta,
                "preprocessing": {
                    "fit_segment": transform_stats["fit_segment"],
                    "winsor_quantile": transform_stats["winsor_quantile"],
                    "standardized_with_train_statistics_only": True,
                },
            },
            "test_metrics": metrics,
            "top_bottom_forward_spread": spread,
            "latest_labeled_test": {
                "timestamp": pd.Timestamp(labeled_timestamp).isoformat() if labeled_timestamp is not None else None,
                "ranking": labeled_rows,
            },
            # Backward-compatible alias for the V1.2 dashboard API.
            "latest_test_ranking": labeled_rows,
            "current_inference": {
                "timestamp": pd.Timestamp(current_t).isoformat(),
                "ranking": current_rows,
                "future_label_available": False,
            },
            "promotion": {
                "status": "CANDIDATE_ONLY",
                "required_next": [
                    "native benchmark comparison",
                    "native out-of-sample validation",
                    "native walk-forward validation",
                    "execution-cost stress test",
                ],
            },
            "discipline_note": "Purged splits + validation selection + untouched test. Current scores have no realized future label and are not trade permission.",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        }
