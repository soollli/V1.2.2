import numpy as np
import pandas as pd

from src.adapters.research.qlib import QlibResearchAdapter, build_qlib_panel, split_panel


def _closes(rows=180, assets=6):
    idx = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    x = np.arange(rows, dtype=float)
    data = {}
    for j in range(assets):
        # Different trends and cycles create stable cross-sectional variation.
        data[f"A{j}"] = 100 + (j + 1) * 0.03 * x + np.sin(x / (5 + j)) * (1 + j * 0.2)
    return pd.DataFrame(data, index=idx)


class FakeQlibLinearModel:
    """Test runtime with Qlib LinearModel's public fit/predict shape."""
    def __init__(self, estimator="ridge", alpha=1.0, fit_intercept=True, include_valid=False):
        self.fit_intercept = fit_intercept
        self.alpha = alpha
        self.beta = None

    def fit(self, dataset):
        df = dataset.prepare("train", col_set=["feature", "label"])
        x = df["feature"].values
        y = df["label"].values[:, 0]
        if self.fit_intercept:
            x = np.c_[x, np.ones(len(x))]
        reg = np.eye(x.shape[1]) * float(self.alpha)
        if self.fit_intercept:
            reg[-1, -1] = 0.0
        self.beta = np.linalg.pinv(x.T @ x + reg) @ x.T @ y
        return self

    def predict(self, dataset, segment="test"):
        x = dataset.prepare(segment, col_set="feature").values
        if self.fit_intercept:
            x = np.c_[x, np.ones(len(x))]
        idx = dataset.prepare(segment, col_set="feature").index
        return pd.Series(x @ self.beta, index=idx)


def test_build_qlib_panel_shape_and_segments():
    closes = _closes()
    panel = build_qlib_panel(closes, min_assets=5)
    assert list(panel.columns.levels[0]) == ["feature", "label"]
    assert panel.index.names == ["datetime", "instrument"]
    assert panel["feature"].shape[1] >= 7
    seg = split_panel(panel)
    assert seg["train"][1] < seg["valid"][0] <= seg["valid"][1] < seg["test"][0]


def test_qlib_adapter_runs_candidate_report_with_qlib_contract():
    closes = _closes()
    adapter = QlibResearchAdapter(model_factory=FakeQlibLinearModel)
    report = adapter.ml_report(closes, {"min_assets": 5, "forward_bars": 5, "alpha": 0.1})
    assert report["engine"] == "qlib"
    assert report["model"]["class"] == "qlib.contrib.model.linear.LinearModel"
    assert report["dataset"]["assets"] == 6
    assert report["test_metrics"]["samples"] > 0
    assert report["promotion"]["status"] == "CANDIDATE_ONLY"
    assert len(report["latest_test_ranking"]) == 6
