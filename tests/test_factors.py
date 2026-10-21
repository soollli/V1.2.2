import numpy as np
import pandas as pd
from src.factors import analyze_factor_matrix, factor_matrices, compute_ic_series, forward_returns


def synthetic_closes(n=180):
    t = pd.date_range('2026-01-01', periods=n, freq='h', tz='UTC')
    x = np.arange(n)
    data = {}
    for i, sym in enumerate(['BTC','ETH','BNB','SOL','XRP','ADA']):
        data[sym] = 100 + (i+1)*0.02*x + 2*np.sin(x/(8+i)) + i
    return pd.DataFrame(data, index=t)


def test_cross_sectional_factor_report():
    closes = synthetic_closes()
    r = analyze_factor_matrix(closes, momentum_period=12, vol_period=12, reversal_period=4, forward_windows=[5,10], min_assets=5)
    assert len(r['universe']) == 6
    assert r['rows']
    assert {'factor','forward_bars','ic_mean','icir'} <= set(r['rows'][0])
    assert 'ram:5' in r['grouped_ic']
