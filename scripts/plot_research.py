#!/usr/bin/env python3
"""Render CAPM/portfolio research charts as one self-contained HTML file.

Deterministic: no randomness, no JavaScript, no CDN (consistent with the
project's no-vendor policy). Data comes from the cached Binance history
(plus one refresh page per symbol), so re-runs are fast.

Usage:
    python scripts/plot_research.py [--bars 5000] [--out PATH]
Writes research/results/charts/portfolio_capm.html by default and prints
the path. The HTML uses the host page's CSS variables when embedded in
Hermes desktop, and falls back to neutral colors when opened standalone.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.core.registry import AdapterRegistry  # noqa: E402
from src.factors import fetch_close_matrix  # noqa: E402
from src.portfolio_research import capm_report, portfolio_curves, default_portfolio_cfg  # noqa: E402

DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

# Series palette (fixed hex: readable on light & dark themes alike)
COLORS = {
    "equal_weight": "#8a8f98",
    "min_variance": "#4f8ff7",
    "mvo_shrinkage": "#e3b341",
    "risk_parity": "#67b26f",
    "btc_bh": "#8b5cf6",
    "sml": "#e05f67",
    "grid": "var(--border, #333)",
    "text": "var(--muted-foreground, #999)",
    "fg": "var(--foreground, #ddd)",
}


def _svg_line(points: list[tuple[float, float]], stroke: str, width: float = 2.0, dash: str = "") -> str:
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<polyline fill="none" stroke="{stroke}" stroke-width="{width}"{d} points="{pts}"/>'


def _nicks(symbols: list[str]) -> list[str]:
    return [s.replace("USDT", "") for s in symbols]


def _equity_series(curves: dict, initial: float) -> list[tuple[str, list[float], str, float, str]]:
    """Series definitions for the equity chart: (name, values, dash, width, color)."""
    out = []
    for cand, data in curves["candidates"].items():
        if cand == "equal_weight":
            out.append(("equal_weight (benchmark)", [v / initial * 100.0 for v in data["net"]], "2,4", 1.6, COLORS["equal_weight"]))
        else:
            out.append((cand, [v / initial * 100.0 for v in data["net"]], "", 2.2, COLORS.get(cand, "#4f8ff7")))
    if "BTCUSDT" in curves.get("buy_hold_prices", {}):
        prices = curves["buy_hold_prices"]["BTCUSDT"]
        p0 = prices[0]  # entry at the decision bar
        out.append(("BTC buy&hold", [p / p0 * 100.0 for p in prices[1:]], "1,5", 1.4, COLORS["btc_bh"]))
    return out


def legend_html(series: list) -> str:
    items = []
    for name, _vals, dash, width, color in series:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        items.append(
            f'<span class="lg"><svg width="22" height="8" aria-hidden="true">'
            f'<line x1="0" y1="4" x2="22" y2="4" stroke="{color}" stroke-width="{width}"{d}/></svg>{name}</span>'
        )
    return '<div class="legend">' + "".join(items) + "</div>"


def chart_equity(curves: dict, times: list[str], oos_folds: list[list[int]], initial: float) -> str:
    """OOS equity curves (normalized to 100) with fold boundaries."""
    W, H, PL, PR, PT, PB = 760, 300, 52, 14, 18, 34
    pw, ph = W - PL - PR, H - PT - PB
    series = _equity_series(curves, initial)
    n = len(times)
    if n < 2:
        return ""
    all_vals = [v for _, vals, _, _, _ in series for v in vals]
    lo, hi = min(all_vals) * 0.985, max(all_vals) * 1.015
    if hi - lo < 1e-9:
        hi = lo + 1.0

    def X(i): return PL + i / (n - 1) * pw

    def Y(v): return PT + (1.0 - (v - lo) / (hi - lo)) * ph

    svg = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">']
    # y gridlines (5)
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = Y(v)
        svg.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" stroke="{COLORS["grid"]}" stroke-width="1" opacity="0.5"/>')
        svg.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" text-anchor="end" font-size="11" fill="{COLORS["text"]}">{v:.1f}</text>')
    # x ticks (5)
    for k in range(5):
        i = int((n - 1) * k / 4)
        t = str(times[i])
        label = t[5:10].replace("-", "/")
        svg.append(f'<text x="{X(i):.1f}" y="{H-PB+18}" text-anchor="middle" font-size="11" fill="{COLORS["text"]}">{label}</text>')
    # fold boundaries
    for fi, (a, b) in enumerate(oos_folds):
        i = a - oos_folds[0][0]
        x = X(max(0, i))
        svg.append(f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{H-PB}" stroke="{COLORS["grid"]}" stroke-width="1" stroke-dasharray="3,3" opacity="0.8"/>')
        svg.append(f'<text x="{x+4:.1f}" y="{H-PB-5}" font-size="10" fill="{COLORS["text"]}">F{fi + 1}</text>')
    term_labels = []
    for name, vals, dash, width, color in series:
        pts = [(X(i), Y(v)) for i, v in enumerate(vals)]
        svg.append(_svg_line(pts, color, width, dash))
        svg.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" fill="{color}"/>')
        term_labels.append((name, Y(vals[-1]), color, vals[-1]))
    # Stacked terminal labels at the right edge: sorted by value, 13px min gap.
    term_labels.sort(key=lambda t: t[1])
    placed = []
    x_end = W - PR - 6
    for name, y, color, last in term_labels:
        y2 = y
        for py in placed:
            if y2 - py < 13:
                y2 = py + 13
        placed.append(y2)
        svg.append(f'<text x="{x_end}" y="{y2 + 3.5:.1f}" text-anchor="end" font-size="10.5" fill="{color}" font-weight="600" '
                   f'stroke="var(--card, #111)" stroke-width="3" paint-order="stroke">{name} {last:.1f}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def chart_drawdown(curves: dict, times: list[str]) -> str:
    """Cumulative drawdown (%) of the net curves, all candidates + EW."""
    W, H, PL, PR, PT, PB = 760, 210, 52, 14, 14, 30
    pw, ph = W - PL - PR, H - PT - PB
    n = len(times)
    if n < 2:
        return ""
    dd_series = []
    for cand, data in curves["candidates"].items():
        vals = data["net"]
        peak = vals[0]
        dd = []
        for v in vals:
            peak = max(peak, v)
            dd.append((v / peak - 1.0) * 100.0 if peak > 0 else 0.0)
        color = COLORS.get(cand, "#4f8ff7") if cand != "equal_weight" else "#8a8f98"
        dash = "2,4" if cand == "equal_weight" else ""
        dd_series.append((cand, dd, color, dash))
    lo = min(min(dd) for _, dd, _, _ in dd_series) * 1.05
    if lo > -0.5:
        lo = -0.5

    def X(i): return PL + i / (n - 1) * pw

    def Y(v): return PT + (1.0 - (v - lo) / (0.0 - lo)) * ph

    svg = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">']
    for k in range(4):
        v = lo + (0.0 - lo) * k / 3
        y = Y(v)
        svg.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" stroke="{COLORS["grid"]}" stroke-width="1" opacity="0.5"/>')
        svg.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" text-anchor="end" font-size="11" fill="{COLORS["text"]}">{v:.1f}%</text>')
    for name, dd, color, dash in dd_series:
        pts = [(X(i), Y(v)) for i, v in enumerate(dd)]
        svg.append(_svg_line(pts, color, 1.8, dash))
    # Stacked terminal labels at the right edge (sorted by value, 13px min gap).
    term = sorted(((name, Y(dd[-1]), color, dd[-1]) for name, dd, color, _dash in dd_series), key=lambda t: t[1])
    placed = []
    x_end = W - PR - 6
    for name, y, color, last in term:
        y2 = y
        for py in placed:
            if y2 - py < 13:
                y2 = py + 13
        placed.append(y2)
        svg.append(f'<text x="{x_end}" y="{y2 + 3.5:.1f}" text-anchor="end" font-size="10.5" fill="{color}" font-weight="600" '
                   f'stroke="var(--card, #111)" stroke-width="3" paint-order="stroke">{name} {last:.1f}%</text>')
    # Bottom-left: the top-left corner is occupied by the 0% start of all curves.
    svg.append(f'<text x="{PL + 4}" y="{H - PB + 16}" font-size="10" fill="{COLORS["text"]}">Cumulative drawdown from peak (net, cost-included)</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def chart_sml(capm: dict) -> str:
    """SML: beta vs annualized return with the two-pass fit line."""
    W, H, PL, PR, PT, PB = 760, 300, 52, 14, 18, 40
    pw, ph = W - PL - PR, H - PT - PB
    assets = capm["assets"]
    sml = capm["sml"]
    pts = [(a["beta"], a["ann_return_pct"]) for a in assets if a["beta"] is not None and a["ann_return_pct"] is not None]
    if not pts:
        return ""
    bs = [p[0] for p in pts]
    rs = [p[1] for p in pts]
    b0, b1 = min(bs), max(bs)
    r0, r1 = min(rs), max(rs)
    pad = max((b1 - b0) * 0.25, 0.05)
    padr = max((r1 - r0) * 0.2, 1.0)
    bx0, bx1, ry0, ry1 = b0 - pad, b1 + pad, r0 - padr, r1 + padr

    def X(b): return PL + (b - bx0) / (bx1 - bx0) * pw

    def Y(r): return PT + (1.0 - (r - ry0) / (ry1 - ry0)) * ph

    svg = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">']
    for k in range(5):
        v = ry0 + (ry1 - ry0) * k / 4
        y = Y(v)
        svg.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" stroke="{COLORS["grid"]}" stroke-width="1" opacity="0.5"/>')
        svg.append(f'<text x="{PL-8}" y="{y+3.5:.1f}" text-anchor="end" font-size="11" fill="{COLORS["text"]}">{v:.0f}%</text>')
    for k in range(5):
        v = bx0 + (bx1 - bx0) * k / 4
        x = X(v)
        svg.append(f'<text x="{x:.1f}" y="{H-PB+18}" text-anchor="middle" font-size="11" fill="{COLORS["text"]}">{v:.2f}</text>')
    # SML fit line
    a0 = sml.get("annualized_intercept_pct") or 0.0
    a1 = sml.get("annualized_slope_pct_per_beta") or 0.0
    svg.append(_svg_line([(X(bx0), Y(a0 + a1 * bx0)), (X(bx1), Y(a0 + a1 * bx1))], COLORS["sml"], 2.0, "5,4"))
    verdict_sig = set(capm["verdict"]["significant_alphas"])
    pts2 = [a for a in assets if a["beta"] is not None and a["ann_return_pct"] is not None]
    for a in pts2:
        sig = a["symbol"] in verdict_sig
        fill = COLORS["sml"] if sig else COLORS.get("min_variance", "#4f8ff7")
        svg.append(f'<circle cx="{X(a["beta"]):.1f}" cy="{Y(a["ann_return_pct"]):.1f}" r="5.5" fill="{fill}"/>')
    # Label layout: alternate above/below by beta rank, row-pack within each
    # band, then a cross-band pass; only emit text once positions are final.
    beta_rank = {id(a): i for i, a in enumerate(sorted(pts2, key=lambda x: x["beta"]))}
    # [x, y, nick, asset, above, line]
    specs = []
    for a in pts2:
        above = beta_rank[id(a)] % 2 == 0
        nick = _nicks([a["symbol"]])[0]
        specs.append([X(a["beta"]) + 9, 0.0, nick, a, above, 0])
    for above in (True, False):
        band = sorted([s for s in specs if s[4] == above], key=lambda s: s[3]["beta"])
        line, line_end = 0, -1e9
        for s in band:
            w = 6.0 * (len(s[2]) + 15)  # "nick β=0.72 αt=+0.8" at font 11
            if s[0] > line_end:
                line = 0
            else:
                line += 1
            line_end = s[0] + w
            s[5] = line
    for s in specs:
        base = Y(s[3]["ann_return_pct"]) - 8 if s[4] else Y(s[3]["ann_return_pct"]) + 16
        s[1] = base + s[5] * 16
    specs.sort(key=lambda t: t[0])
    for i in range(1, len(specs)):
        for j in range(i):
            px, py, pnick = specs[j][0], specs[j][1], specs[j][2]
            w = 6.0 * (len(pnick) + 15)
            if specs[i][0] < px + w and abs(specs[i][1] - py) < 18:
                specs[i][1] = py + 18
    for s in specs:
        a, nick = s[3], s[2]
        svg.append(f'<text x="{s[0]:.1f}" y="{s[1]:.1f}" font-size="11" fill="{COLORS["fg"]}" '
                   f'stroke="var(--card, #111)" stroke-width="3" paint-order="stroke">{nick} '
                   f'β={a["beta"]:.2f} αt={a["alpha_t"]:+.1f}</text>')
    svg.append(f'<text x="{PL}" y="{H-6}" font-size="10.5" fill="{COLORS["text"]}">Two-pass SML · R²={sml.get("r2")} · slope {a1:+.1f}%/β · intercept {a0:+.1f}%/yr (Rf=0, 365d) · red dot = significant α (|t|≥{capm["verdict"]["alpha_threshold_t"]})</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def _table(capm: dict, curves: dict) -> str:
    rows = []
    for cand, d in curves["candidates"].items():
        m = d["metrics"]
        rows.append(
            f'<tr><td>{cand}</td>'
            f'<td>{d["net_return_pct"]:+.2f}%</td>'
            f'<td>{m.get("annualized_return_pct"):.1f}%</td>'
            f'<td>{m.get("annualized_vol_pct"):.1f}%</td>'
            f'<td>{m.get("sharpe"):.2f}</td>'
            f'<td>{m.get("max_drawdown_pct"):.1f}%</td>'
            f'<td>{d.get("total_turnover_one_sided", 0):.2f}</td></tr>'
        )
    for a in capm["assets"]:
        rows.append(
            f'<tr class="cap"><td>{_nicks([a["symbol"]])[0]} CAPM</td>'
            f'<td>β={a["beta"]:.2f}</td><td>α={a["alpha_ann_pct"]:+.1f}%/yr</td>'
            f'<td>t={a["alpha_t"]:+.2f}</td><td>R²={a["r2"]:.2f}</td><td colspan="2"></td></tr>'
        )
    return ("<table><thead><tr><th>candidate / asset</th><th>OOS net</th><th>ann. ret</th>"
            "<th>ann. vol</th><th>sharpe</th><th>maxDD</th><th>turnover</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>")


def render_html(capm: dict, curves: dict, bars: int, interval: str) -> str:
    initial = curves.get("initial_quote", 10000.0)
    fold_lines = "".join(
        f'<li>F{k+1}: bars {a}-{b} ({(b-a)} bars)</li>'
        for k, (a, b) in enumerate(curves["folds"])
    )
    verdicts = []
    v = capm["verdict"]
    verdicts.append(f"CAPM pricing {'成立' if v['supports_capm_pricing'] else '不成立'}"
                    f"（SML R²={capm['sml']['r2']:.2f}，显著 α={v['significant_alphas'] or '无'}）")
    ew = curves["candidates"]["equal_weight"]["net_return_pct"]
    best = max(
        ((cand, d["net_return_pct"]) for cand, d in curves["candidates"].items() if cand != "equal_weight"),
        key=lambda t: t[1], default=None,
    )
    if best and best[1] > ew:
        verdicts.append(f"成本后跑赢等权（{ew:+.2f}%）：{best[0]}（{best[1]:+.2f}%）")
    else:
        verdicts.append("无候选成本后跑赢等权")
    series = _equity_series(curves, initial)
    body = f"""
<section>
  <h2>Portfolio &amp; CAPM 研究图表</h2>
  <p class="meta">{bars} bars · {interval} · train {curves['train_len_bars']} + {len(curves['folds'])} walk-forward folds · OAS 协方差 · next-open 成本（0.1% fee + 2bps slip）· 365d 年化 · 生成于缓存行情（重跑: python scripts/plot_research.py）</p>
  <ol class="verdicts">{''.join(f'<li>{x}</li>' for x in verdicts)}</ol>
  <h3>OOS 净值曲线（等权=100 起）</h3>
  {legend_html(series)}
  {chart_equity(curves, curves['oos_times'], curves['folds'], initial)}
  <h3>回撤</h3>
  {chart_drawdown(curves, curves['oos_times'])}
  <h3>CAPM / SML（β vs 年化收益）</h3>
  {chart_sml(capm)}
  {_table(capm, curves)}
  <p class="meta">folds: {fold_lines.replace('<li>', '').replace('</li>', '')} · 6 资产 universe 属探索性结果；执行前须过 Promotion Gate（immutable run ID）+ 人类审批。</p>
</section>
"""
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        "*{box-sizing:border-box}body{margin:0;font-family:var(--font, ui-sans-serif, system-ui, sans-serif);color:var(--foreground, #ddd)}"
        "section{font-family:inherit}"
        "h2{font-size:16px;margin:0 0 4px}h3{font-size:13px;margin:14px 0 2px;color:var(--muted-foreground, #aaa)}"
        ".meta{font-size:11px;color:var(--muted-foreground, #999);margin:2px 0 8px}"
        ".verdicts{font-size:12px;margin:4px 0;list-style-position:inside}"
        ".legend{display:flex;flex-wrap:wrap;gap:14px;font-size:11px;color:var(--muted-foreground, #999);margin:2px 0 4px}"
        ".lg{display:inline-flex;align-items:center;gap:4px}"
        "table{border-collapse:collapse;font-size:11.5px;margin-top:10px}"
        "th,td{border:1px solid var(--border, #333);padding:3px 8px;text-align:right}"
        "th:first-child,td:first-child{text-align:left}"
        "th{color:var(--muted-foreground, #999);font-weight:600}"
        "tr.cap td{color:var(--muted-foreground, #999)}"
        "</style></head><body>" + body + "</body></html>"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Render CAPM/portfolio research charts to self-contained HTML")
    p.add_argument("--bars", type=int, default=5000)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--out", default="")
    args = p.parse_args()

    s = load_settings(args.config)
    rcfg = s.raw.get("factor_research", {})
    pcfg = s.raw.get("portfolio_research", {})
    universe = list(pcfg.get("universe", rcfg.get("universe", DEFAULT_UNIVERSE)))
    interval = str(pcfg.get("interval", rcfg.get("interval", "1h")))
    annualization = str(s.raw.get("research", {}).get("annualization", "crypto_24x7"))
    md = AdapterRegistry(s).data(use_testnet=False)
    closes = fetch_close_matrix(md, universe, interval, args.bars)
    if closes.empty or closes.shape[1] < 5:
        print("need >= 5 aligned symbols; check network/universe/bars", file=sys.stderr)
        return 2
    capm = capm_report(closes, pcfg, interval, annualization)
    curves = portfolio_curves(closes, pcfg, interval, annualization)
    out = Path(args.out) if args.out else s.root / "research" / "results" / "charts" / "portfolio_capm.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(capm, curves, args.bars, interval), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
