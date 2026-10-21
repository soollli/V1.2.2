from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import csv
import json
import math
import webbrowser
from urllib.parse import urlparse, parse_qs

import pandas as pd

from .config import Settings
from .core.registry import AdapterRegistry
from .monitor import build_status, build_research_bundle, mode_path
from .strategy import rsi


ALLOWED_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}


def _num(v, default=0.0):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def _read_trade_markers(path: Path, n: int = 300) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))[-n:]
        out = []
        for row in rows:
            out.append({
                "time": row.get("time_utc", ""),
                "side": row.get("side", ""),
                "price": _num(row.get("price")),
                "qty": _num(row.get("base_qty")),
                "reason": row.get("reason", ""),
            })
        return out
    except Exception:
        return []


def build_chart_payload(settings: Settings, mode: str = "paper", interval: str | None = None,
                        limit: int = 240, market=None) -> dict:
    """Return browser-friendly chart data. Read-only: never places orders."""
    interval = interval or settings.market["interval"]
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    limit = max(60, min(int(limit), 500))
    use_testnet = mode == "binance_testnet"
    market = market or AdapterRegistry(settings).data(use_testnet=use_testnet)
    df = market.klines(settings.market["symbol"], interval, limit)
    if df.empty:
        return {"symbol": settings.market["symbol"], "interval": interval, "candles": [], "trades": []}

    strategy = settings.strategy
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=int(strategy.get("fast_ema", 9)), adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=int(strategy.get("slow_ema", 21)), adjust=False).mean()
    df["rsi"] = rsi(df["close"], int(strategy.get("rsi_period", 14)))

    candles = []
    for _, row in df.iterrows():
        ts = pd.Timestamp(row["open_time"])
        candles.append({
            "time": ts.isoformat(),
            "ts": int(ts.timestamp() * 1000),
            "open": _num(row["open"]),
            "high": _num(row["high"]),
            "low": _num(row["low"]),
            "close": _num(row["close"]),
            "volume": _num(row["volume"]),
            "ema_fast": _num(row["ema_fast"], None),
            "ema_slow": _num(row["ema_slow"], None),
            "rsi": _num(row["rsi"], None),
        })

    trades_path = mode_path(settings, "trades_file", mode)
    trades = _read_trade_markers(trades_path)
    return {
        "symbol": settings.market["symbol"],
        "interval": interval,
        "mode": mode,
        "fast_ema": int(strategy.get("fast_ema", 9)),
        "slow_ema": int(strategy.get("slow_ema", 21)),
        "rsi_period": int(strategy.get("rsi_period", 14)),
        "candles": candles,
        "trades": trades,
    }


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>AI Quant Terminal</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{color-scheme:dark;--bg:#081018;--panel:#0d1722;--panel2:#0a131c;--line:#1d2b3a;--text:#e5edf5;--muted:#8194a8;--green:#20c997;--red:#ff647c;--gold:#f6c85f;--blue:#62a8ff;--cyan:#52d3ff}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.shell{min-height:100vh}.topbar{height:58px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 18px;background:#09131d;position:sticky;top:0;z-index:5}
.brand{font-weight:800;letter-spacing:.02em}.topmeta{display:flex;gap:12px;align-items:center;color:var(--muted);font-size:13px}.status{padding:5px 9px;border-radius:999px;background:#142130}.status.ok{color:var(--green)}.status.bad{color:var(--red)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:1px;background:var(--line);min-height:calc(100vh - 58px)}.main,.side{background:var(--bg)}
.instrument{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line);background:var(--panel2);flex-wrap:wrap}
.sym{font-size:22px;font-weight:800}.quote{color:var(--muted);font-size:12px;margin-left:7px}.price{font-size:22px;font-weight:800}.tf{display:flex;gap:4px;flex-wrap:wrap}.tf button{border:0;background:transparent;color:var(--muted);padding:7px 10px;border-radius:7px;cursor:pointer}.tf button:hover,.tf button.active{background:#162331;color:var(--text)}
.chartbox{background:#081018;border-bottom:1px solid var(--line);position:relative}.charthead{height:38px;display:flex;align-items:center;gap:14px;padding:0 16px;color:var(--muted);font-size:12px}.legend b{font-weight:700}.canvaswrap{height:490px;position:relative}.canvaswrap.small{height:145px;border-top:1px solid #13202d}.canvaswrap canvas{width:100%;height:100%;display:block}.lwcchart{position:absolute;inset:0}.fallback-chart{display:none}.chart-attrib{font-size:10px;color:var(--muted);padding:4px 12px 7px;text-align:right}.chart-attrib a{color:var(--cyan);text-decoration:none}.tooltip{position:absolute;display:none;pointer-events:none;background:#0d1722ee;border:1px solid #2a3b4e;border-radius:8px;padding:7px 9px;font-size:12px;line-height:1.55;z-index:4;box-shadow:0 8px 22px #0008}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border-bottom:1px solid var(--line)}.metric{background:var(--panel2);padding:13px 14px}.mk{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}.mv{font-size:18px;font-weight:750;margin-top:4px}.mv.small{font-size:14px}
.side{display:flex;flex-direction:column}.sideblock{border-bottom:1px solid var(--line);padding:14px}.side h3{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:0 0 12px}.row{display:flex;justify-content:space-between;gap:12px;padding:6px 0;font-size:13px}.row span:first-child{color:var(--muted)}
.trades{overflow:auto;max-height:315px}.trade{display:grid;grid-template-columns:44px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid #13202d;font-size:12px}.buy{color:var(--green)}.sell{color:var(--red)}.events{font:11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#a8b7c7;white-space:pre-wrap;max-height:250px;overflow:auto}
.errbar{display:none;padding:8px 16px;background:#3b1820;color:#ffc1ca;font-size:12px;border-bottom:1px solid #642333}
@media(max-width:980px){.layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:1fr 1fr}.sideblock{border-right:1px solid var(--line)}.metrics{grid-template-columns:repeat(2,1fr)}}
.tabs{display:flex;gap:4px;padding:8px 16px;border-bottom:1px solid var(--line);background:#09131d;position:sticky;top:58px;z-index:4}.tab{border:0;background:transparent;color:var(--muted);padding:8px 12px;border-radius:7px;cursor:pointer;font-weight:700;font-size:12px;letter-spacing:.04em}.tab.active,.tab:hover{background:#162331;color:var(--text)}.view{display:none}.view.active{display:block}.research-wrap{padding:16px}.research-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.panel{background:var(--panel2);border:1px solid var(--line);border-radius:10px;overflow:hidden}.panel.wide{grid-column:1/-1}.ph{padding:11px 13px;border-bottom:1px solid var(--line);font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);display:flex;justify-content:space-between}.pb{padding:12px}.rcanvas{height:260px}.rcanvas canvas{width:100%;height:100%;display:block}.statgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line)}.stat{background:var(--panel2);padding:12px}.tablewrap{overflow:auto;max-height:330px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:8px 9px;border-bottom:1px solid #172432;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-weight:650;position:sticky;top:0;background:var(--panel2)}.triage{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.triage-card{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:15px}.triage-title{font-size:12px;color:var(--muted);text-transform:uppercase}.triage-state{font-size:20px;font-weight:800;margin:8px 0}.oktxt{color:var(--green)}.warntxt{color:var(--gold)}.badtxt{color:var(--red)}.note{color:var(--muted);font-size:12px;line-height:1.55}.journal{display:grid;gap:8px}.journal-item{padding:9px;border:1px solid #172432;border-radius:7px;font-size:12px}.empty{color:var(--muted);font-size:12px;padding:10px}
@media(max-width:980px){.research-grid{grid-template-columns:1fr}.panel.wide{grid-column:auto}.triage{grid-template-columns:1fr}.statgrid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.side{display:block}.metrics{grid-template-columns:1fr 1fr}.canvaswrap{height:400px}.topmeta .hide-sm{display:none}.instrument{align-items:flex-start}.tf{width:100%}.tabs{overflow:auto}.statgrid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body><div class="shell">
<div class="topbar"><div class="brand">AI QUANT <span style="color:var(--cyan)">TERMINAL</span></div><div class="topmeta"><span id="mode">-</span><span class="hide-sm" id="strategy">-</span><span id="run" class="status">...</span></div></div>
<div id="err" class="errbar"></div>
<div class="tabs" id="tabs"><button class="tab active" data-view="tradeView">TRADE</button><button class="tab" data-view="researchView">RESEARCH</button><button class="tab" data-view="diagView">DIAGNOSTICS</button><button class="tab" data-view="systemView">SYSTEM</button></div>
<div id="tradeView" class="view active"><div class="layout"><main class="main">
  <div class="instrument"><div><span class="sym" id="symbol">BTCUSDT</span><span class="quote">SPOT · PAPER</span></div><div class="price" id="lastPrice">-</div><div class="tf" id="timeframes"><button data-tf="1m" class="active">1m</button><button data-tf="5m">5m</button><button data-tf="15m">15m</button><button data-tf="1h">1h</button><button data-tf="4h">4h</button></div></div>
  <section class="chartbox">
    <div class="charthead"><span id="ohlc">O - H - L - C -</span><span class="legend" id="emaLegend">EMA</span></div>
    <div class="canvaswrap"><div id="priceChartLwc" class="lwcchart"></div><canvas id="priceChart" class="fallback-chart"></canvas><div id="tooltip" class="tooltip"></div></div>
    <div class="canvaswrap small"><div id="rsiChartLwc" class="lwcchart"></div><canvas id="rsiChart" class="fallback-chart"></canvas></div>
    <div class="chart-attrib">Charts powered by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></div>
  </section>
  <section class="metrics">
    <div class="metric"><div class="mk">Position</div><div class="mv" id="pos">-</div></div>
    <div class="metric"><div class="mk">Avg entry</div><div class="mv" id="entry">-</div></div>
    <div class="metric"><div class="mk">Realized PnL</div><div class="mv" id="rpnl">-</div></div>
    <div class="metric"><div class="mk">Unrealized PnL</div><div class="mv" id="upnl">-</div></div>
    <div class="metric"><div class="mk">Quote balance</div><div class="mv small" id="cash">-</div></div>
    <div class="metric"><div class="mk">Last signal</div><div class="mv small" id="signal">-</div></div>
    <div class="metric"><div class="mk">Research return</div><div class="mv small" id="rret">-</div></div>
    <div class="metric"><div class="mk">Buy & Hold</div><div class="mv small" id="bret">-</div></div>
  </section>
</main>
<aside class="side">
  <div class="sideblock"><h3>Account</h3><div class="row"><span>Engine</span><b id="engine">-</b></div><div class="row"><span>Marked equity</span><b id="equity">-</b></div><div class="row"><span>Last update</span><b id="updated">-</b></div><div class="row"><span>Excess return</span><b id="exret">-</b></div><div class="row"><span>Research max DD</span><b id="rdd">-</b></div></div>
  <div class="sideblock"><h3>Recent Trades</h3><div class="trades" id="trades"><span style="color:var(--muted)">No trades yet.</span></div></div>
  <div class="sideblock"><h3>Events</h3><div class="events" id="events">loading...</div></div>
</aside></div></div>
<div id="researchView" class="view"><div class="research-wrap">
  <div class="statgrid">
    <div class="stat"><div class="mk">Strategy return</div><div class="mv" id="rrReturn">-</div></div>
    <div class="stat"><div class="mk">Buy & Hold</div><div class="mv" id="rrBench">-</div></div>
    <div class="stat"><div class="mk">Excess</div><div class="mv" id="rrExcess">-</div></div>
    <div class="stat"><div class="mk">Max drawdown</div><div class="mv" id="rrDD">-</div></div>
    <div class="stat"><div class="mk">Sharpe-like</div><div class="mv small" id="rrSharpe">-</div></div>
    <div class="stat"><div class="mk">Profit factor</div><div class="mv small" id="rrPF">-</div></div>
    <div class="stat"><div class="mk">Win rate</div><div class="mv small" id="rrWin">-</div></div>
    <div class="stat"><div class="mk">Orders</div><div class="mv small" id="rrOrders">-</div></div>
  </div>
  <div class="research-grid" style="margin-top:12px">
    <div class="panel wide"><div class="ph"><span>Strategy vs Buy & Hold</span><span id="researchStamp">run: python run.py research --bars 1000</span></div><div class="rcanvas"><canvas id="equityChart"></canvas></div></div>
    <div class="panel"><div class="ph"><span>Drawdown</span></div><div class="rcanvas"><canvas id="drawdownChart"></canvas></div></div>
    <div class="panel"><div class="ph"><span>Rolling Sharpe-like</span></div><div class="rcanvas"><canvas id="rollingChart"></canvas></div></div>
    <div class="panel"><div class="ph"><span>OOS Parameter Scan</span><span>test first</span></div><div class="pb tablewrap"><table><thead><tr><th>EMA</th><th>Train %</th><th>OOS %</th><th>Excess %</th><th>Gap</th></tr></thead><tbody id="scanRows"></tbody></table></div></div>
    <div class="panel"><div class="ph"><span>Walk-forward</span><span id="wfStability">-</span></div><div class="pb tablewrap"><table><thead><tr><th>Fold</th><th>EMA</th><th>Train %</th><th>OOS %</th><th>DD %</th></tr></thead><tbody id="wfRows"></tbody></table></div></div>
    <div class="panel wide"><div class="ph"><span>Crypto Factor Lab · Cross-sectional Spearman IC</span><span>python run.py factors --bars 1000</span></div><div class="pb tablewrap"><table><thead><tr><th>Factor</th><th>Forward bars</th><th>IC mean</th><th>ICIR</th><th>IC&gt;0</th><th>N</th></tr></thead><tbody id="factorRows"></tbody></table><div class="note" id="factorNote"></div></div></div>
    <div class="panel wide"><div class="ph"><span>Qlib ML Candidate Lab</span><span>purged train/valid/test</span></div><div class="pb"><div class="statgrid" style="margin-bottom:10px"><div class="stat"><div class="mk">Test IC</div><div class="mv small" id="qlibIC">-</div></div><div class="stat"><div class="mk">ICIR</div><div class="mv small" id="qlibICIR">-</div></div><div class="stat"><div class="mk">IC &gt; 0</div><div class="mv small" id="qlibPos">-</div></div><div class="stat"><div class="mk">Top-Bottom spread</div><div class="mv small" id="qlibSpread">-</div></div></div><div class="note" id="qlibCurrentTime">Current inference: -</div><div class="tablewrap"><table><thead><tr><th>Asset</th><th>Current Qlib score</th><th>Future label</th></tr></thead><tbody id="qlibRows"></tbody></table></div><div class="note" id="qlibNote">Current inference has no future label and is not trade permission.</div></div></div>
    <div class="panel wide"><div class="ph"><span>Promotion Gate</span><span>research evidence → execution eligibility</span></div><div class="pb"><div class="row"><span>Status</span><b id="promotionState">NO TICKET</b></div><div class="row"><span>Ticket</span><b id="promotionTicket">-</b></div><div class="note" id="promotionReasons">Run promotion-check with immutable strategy + walk-forward run IDs. A promotion ticket is evidence, not an order.</div></div></div>
    <div class="panel wide"><div class="ph"><span>Experiment Journal</span><span>hypothesis → acceptance → result</span></div><div class="pb journal" id="journal"></div></div>
  </div>
</div></div>
<div id="diagView" class="view"><div class="research-wrap">
  <div class="triage">
    <div class="triage-card"><div class="triage-title">1 · Execution</div><div class="triage-state" id="diagExec">-</div><div class="note" id="diagExecNote">先查成交、滑点和费用。</div></div>
    <div class="triage-card"><div class="triage-title">2 · Market regime</div><div class="triage-state" id="diagRegime">-</div><div class="note" id="diagRegimeNote">再判断市场是否进入高波动状态。</div></div>
    <div class="triage-card"><div class="triage-title">3 · Strategy</div><div class="triage-state" id="diagStrategy">-</div><div class="note" id="diagStrategyNote">最后才怀疑策略和参数稳定性。</div></div>
  </div>
  <div class="panel" style="margin-top:12px"><div class="ph"><span>Diagnostic rule</span></div><div class="pb note">顺序固定：执行落差（外） → 市场状态（中） → 策略设计（内）。不要因为一段亏损就直接改参数。阈值来自 config.yaml，修改阈值也应写进实验记录。</div></div>
</div></div>
<div id="systemView" class="view"><div class="research-wrap">
  <div class="panel"><div class="ph"><span>Core V1 · Active Adapters</span><span>stable boundaries</span></div><div class="pb" id="activeAdapters"></div></div>
  <div class="panel" style="margin-top:12px"><div class="ph"><span>Optional Integration Slots</span><span>detected ≠ enabled</span></div><div class="pb tablewrap"><table><thead><tr><th>Integration</th><th>Layer</th><th>Package</th><th>Enabled</th><th>Purpose</th></tr></thead><tbody id="integrationRows"></tbody></table></div></div>
  <div class="panel" style="margin-top:12px"><div class="ph"><span>Agent Safety Plane</span><span>Agnes/Hermes ≠ broker</span></div><div class="pb" id="agentPolicy"></div><div class="pb tablewrap"><table><thead><tr><th>Skill</th><th>Permission</th><th>Min autonomy</th><th>Market mutation</th></tr></thead><tbody id="agentSkillRows"></tbody></table></div></div>
  <div class="panel" style="margin-top:12px"><div class="ph"><span>Safety Invariant</span></div><div class="pb note">Core V1.2.2 has no live-money command. Agnes/Hermes use a simple agent loop plus deterministic skills. Agent execution must pass the Action Gateway, a non-expired Promotion Ticket, autonomy policy and (by default) human trade approval. The gateway never owns broker secrets and does not dispatch orders in this alpha.</div></div>
</div></div>
</div>
<script>
const $=id=>document.getElementById(id); const fmt=(n,d=2)=>{n=Number(n);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:d}):'-'};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let interval='1m', chartData=null, hoverIndex=null, statusData=null, researchData=null, capabilityData=null;
let lwcPriceChart=null,lwcRsiChart=null,lwcCandle=null,lwcFast=null,lwcSlow=null,lwcVolume=null,lwcRsi=null,lwcMarkers=null,lwcResizeBound=false;
function lwcReady(){return !!(window.LightweightCharts&&LightweightCharts.createChart&&LightweightCharts.CandlestickSeries)}
function destroyLwc(){try{if(lwcPriceChart)lwcPriceChart.remove();if(lwcRsiChart)lwcRsiChart.remove()}catch(e){}lwcPriceChart=lwcRsiChart=lwcCandle=lwcFast=lwcSlow=lwcVolume=lwcRsi=lwcMarkers=null}
function initLwc(){if(!lwcReady())return false;if(lwcPriceChart&&lwcRsiChart)return true;const pc=$('priceChartLwc'),rc=$('rsiChartLwc');pc.style.display='block';rc.style.display='block';$('priceChart').style.display='none';$('rsiChart').style.display='none';const base={autoSize:true,layout:{background:{type:'solid',color:'#081018'},textColor:'#8194a8',attributionLogo:true},grid:{vertLines:{color:'#111e2a'},horzLines:{color:'#111e2a'}},crosshair:{mode:0},rightPriceScale:{borderColor:'#1d2b3a'},timeScale:{borderColor:'#1d2b3a',timeVisible:true,secondsVisible:false}};lwcPriceChart=LightweightCharts.createChart(pc,base);lwcCandle=lwcPriceChart.addSeries(LightweightCharts.CandlestickSeries,{upColor:'#20c997',downColor:'#ff647c',borderVisible:false,wickUpColor:'#20c997',wickDownColor:'#ff647c'});lwcFast=lwcPriceChart.addSeries(LightweightCharts.LineSeries,{color:'#f6c85f',lineWidth:1,priceLineVisible:false,lastValueVisible:false});lwcSlow=lwcPriceChart.addSeries(LightweightCharts.LineSeries,{color:'#62a8ff',lineWidth:1,priceLineVisible:false,lastValueVisible:false});lwcVolume=lwcPriceChart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'',lastValueVisible:false,priceLineVisible:false});lwcPriceChart.priceScale('').applyOptions({scaleMargins:{top:0.78,bottom:0}});lwcPriceChart.priceScale('right').applyOptions({scaleMargins:{top:0.05,bottom:0.22}});lwcRsiChart=LightweightCharts.createChart(rc,{...base,rightPriceScale:{borderColor:'#1d2b3a',scaleMargins:{top:.12,bottom:.12}},timeScale:{borderColor:'#1d2b3a',timeVisible:true,secondsVisible:false}});lwcRsi=lwcRsiChart.addSeries(LightweightCharts.LineSeries,{color:'#52d3ff',lineWidth:1,priceLineVisible:false,lastValueVisible:true,autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:100}})});[30,50,70].forEach(v=>lwcRsi.createPriceLine({price:v,color:v===50?'#1e2c3a':'#25384a',lineWidth:1,lineStyle:v===50?0:2,axisLabelVisible:true,title:''}));lwcPriceChart.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r)try{lwcRsiChart.timeScale().setVisibleLogicalRange(r)}catch(e){}});lwcPriceChart.subscribeCrosshairMove(param=>{if(!param?.time||!lwcCandle)return;const d=param.seriesData.get(lwcCandle);if(!d)return;const sec=Number(param.time),a=chartData?.candles?.find(x=>Math.floor(x.ts/1000)===sec);if(a)$('ohlc').textContent=`O ${nice(a.open)}  H ${nice(a.high)}  L ${nice(a.low)}  C ${nice(a.close)} · RSI ${fmt(a.rsi,1)}`});return true}
function renderLwc(){if(!chartData||!chartData.candles?.length||!initLwc())return false;const d=chartData.candles,toT=x=>Math.floor(x.ts/1000);lwcCandle.setData(d.map(x=>({time:toT(x),open:x.open,high:x.high,low:x.low,close:x.close})));lwcFast.setData(d.filter(x=>x.ema_fast!=null).map(x=>({time:toT(x),value:x.ema_fast})));lwcSlow.setData(d.filter(x=>x.ema_slow!=null).map(x=>({time:toT(x),value:x.ema_slow})));lwcVolume.setData(d.map(x=>({time:toT(x),value:x.volume,color:x.close>=x.open?'rgba(32,201,151,.35)':'rgba(255,100,124,.35)'})));lwcRsi.setData(d.filter(x=>x.rsi!=null).map(x=>({time:toT(x),value:x.rsi})));const markers=(chartData.trades||[]).map(t=>{const ms=Date.parse(t.time);if(!Number.isFinite(ms))return null;const buy=t.side==='BUY';return {time:Math.floor(ms/1000),position:buy?'belowBar':'aboveBar',color:buy?'#20c997':'#ff647c',shape:buy?'arrowUp':'arrowDown',text:buy?'B':'S'}}).filter(Boolean).sort((a,b)=>a.time-b.time);if(lwcMarkers){lwcMarkers.setMarkers(markers)}else if(LightweightCharts.createSeriesMarkers){lwcMarkers=LightweightCharts.createSeriesMarkers(lwcCandle,markers,{autoScale:true})}lwcPriceChart.timeScale().fitContent();lwcRsiChart.timeScale().fitContent();return true}
function renderTradeCharts(){if(renderLwc())return;$('priceChartLwc').style.display='none';$('rsiChartLwc').style.display='none';$('priceChart').style.display='block';$('rsiChart').style.display='block';drawPrice();drawRsi()}
function setupCanvas(canvas){const r=canvas.getBoundingClientRect(),d=window.devicePixelRatio||1; canvas.width=Math.max(1,Math.round(r.width*d));canvas.height=Math.max(1,Math.round(r.height*d));const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);return {c,w:r.width,h:r.height};}
function line(c,pts,stroke,width=1){if(!pts.length)return;c.beginPath();let started=false;for(const p of pts){if(!p||!Number.isFinite(p[1])){started=false;continue} if(!started){c.moveTo(p[0],p[1]);started=true}else c.lineTo(p[0],p[1])}c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}
function nice(v){if(Math.abs(v)>=1000)return fmt(v,2);if(Math.abs(v)>=1)return fmt(v,4);return fmt(v,8)}
function drawPrice(){if(!chartData||!chartData.candles?.length)return;const cv=$('priceChart'),{c,w,h}=setupCanvas(cv),d=chartData.candles; c.clearRect(0,0,w,h);const M={l:10,r:72,t:8,b:54},volH=72,priceB=h-M.b-volH;const hi=Math.max(...d.map(x=>x.high)),lo=Math.min(...d.map(x=>x.low)),pad=(hi-lo||1)*.07,max=hi+pad,min=lo-pad;const pw=w-M.l-M.r,cw=pw/d.length,x=i=>M.l+(i+.5)*cw,y=v=>M.t+(max-v)/(max-min)*(priceB-M.t);const vmax=Math.max(...d.map(x=>x.volume),1);
 c.font='11px system-ui';c.textAlign='left';c.textBaseline='middle'; for(let j=0;j<=5;j++){const yy=M.t+(priceB-M.t)*j/5,val=max-(max-min)*j/5;c.strokeStyle='#172432';c.lineWidth=1;c.beginPath();c.moveTo(M.l,yy);c.lineTo(w-M.r,yy);c.stroke();c.fillStyle=css('--muted');c.fillText(nice(val),w-M.r+8,yy)}
 for(let i=0;i<d.length;i++){const a=d[i],xx=x(i),up=a.close>=a.open,col=up?css('--green'):css('--red');c.strokeStyle=col;c.lineWidth=1;c.beginPath();c.moveTo(xx,y(a.high));c.lineTo(xx,y(a.low));c.stroke();const yo=y(a.open),yc=y(a.close),bh=Math.max(1,Math.abs(yc-yo)),bw=Math.max(1,Math.min(10,cw*.68));c.fillStyle=col;c.fillRect(xx-bw/2,Math.min(yo,yc),bw,bh);const vh=(a.volume/vmax)*(volH-15);c.globalAlpha=.34;c.fillRect(xx-bw/2,h-M.b-vh,bw,vh);c.globalAlpha=1}
 line(c,d.map((a,i)=>[x(i),a.ema_fast==null?NaN:y(a.ema_fast)]),css('--gold'),1.35);line(c,d.map((a,i)=>[x(i),a.ema_slow==null?NaN:y(a.ema_slow)]),css('--blue'),1.35);
 const t0=d[0].ts,t1=d[d.length-1].ts;for(const tr of chartData.trades||[]){const tt=Date.parse(tr.time);if(!Number.isFinite(tt)||tt<t0||tt>t1)continue;let idx=Math.max(0,Math.min(d.length-1,Math.round((tt-t0)/(t1-t0||1)*(d.length-1))));const xx=x(idx),yy=y(tr.price||d[idx].close),buy=tr.side==='BUY',col=buy?css('--green'):css('--red');c.fillStyle=col;c.beginPath();if(buy){c.moveTo(xx,yy-14);c.lineTo(xx-6,yy-4);c.lineTo(xx+6,yy-4)}else{c.moveTo(xx,yy+14);c.lineTo(xx-6,yy+4);c.lineTo(xx+6,yy+4)}c.closePath();c.fill();c.font='bold 10px system-ui';c.textAlign='center';c.fillText(buy?'B':'S',xx,buy?yy-21:yy+22)}
 const labels=5; c.textAlign='center';for(let j=0;j<labels;j++){const idx=Math.round(j*(d.length-1)/(labels-1)),a=d[idx],dt=new Date(a.ts),txt=interval.endsWith('m')?dt.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):dt.toLocaleString([],{month:'2-digit',day:'2-digit',hour:'2-digit'});c.fillStyle=css('--muted');c.fillText(txt,x(idx),h-18)}
 if(hoverIndex!=null&&d[hoverIndex]){const xx=x(hoverIndex),a=d[hoverIndex];c.strokeStyle='#60758a';c.setLineDash([4,4]);c.beginPath();c.moveTo(xx,M.t);c.lineTo(xx,h-M.b);c.stroke();c.setLineDash([]);$('ohlc').textContent=`O ${nice(a.open)}  H ${nice(a.high)}  L ${nice(a.low)}  C ${nice(a.close)}  Vol ${fmt(a.volume,2)}`}
 cv._geom={d,x,y,M,priceB,cw};
}
function drawRsi(){if(!chartData||!chartData.candles?.length)return;const cv=$('rsiChart'),{c,w,h}=setupCanvas(cv),d=chartData.candles,M={l:10,r:72,t:10,b:24},pw=w-M.l-M.r,cw=pw/d.length,x=i=>M.l+(i+.5)*cw,y=v=>M.t+(100-v)/100*(h-M.t-M.b);c.clearRect(0,0,w,h);for(const v of [30,50,70]){const yy=y(v);c.strokeStyle=v===50?'#1e2c3a':'#25384a';c.setLineDash(v===50?[]:[4,4]);c.beginPath();c.moveTo(M.l,yy);c.lineTo(w-M.r,yy);c.stroke();c.setLineDash([]);c.fillStyle=css('--muted');c.font='10px system-ui';c.fillText(String(v),w-M.r+8,yy+3)}line(c,d.map((a,i)=>[x(i),a.rsi==null?NaN:y(a.rsi)]),css('--cyan'),1.25);c.fillStyle=css('--muted');c.font='10px system-ui';c.fillText(`RSI ${chartData.rsi_period}`,14,16)}
function bindHover(){const cv=$('priceChart'),tip=$('tooltip');cv.onmousemove=e=>{if(!cv._geom)return;const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,g=cv._geom,idx=Math.floor((mx-g.M.l)/g.cw);if(idx<0||idx>=g.d.length){hoverIndex=null;tip.style.display='none';drawPrice();return}hoverIndex=idx;const a=g.d[idx];tip.innerHTML=`<b>${new Date(a.ts).toLocaleString()}</b><br>O ${nice(a.open)} &nbsp; H ${nice(a.high)}<br>L ${nice(a.low)} &nbsp; C ${nice(a.close)}<br>EMA${chartData.fast_ema} ${nice(a.ema_fast)} · EMA${chartData.slow_ema} ${nice(a.ema_slow)}<br>RSI ${fmt(a.rsi,1)}`;tip.style.display='block';tip.style.left=Math.min(r.width-210,Math.max(8,e.clientX-r.left+12))+'px';tip.style.top=Math.max(8,e.clientY-r.top-8)+'px';drawPrice()};cv.onmouseleave=()=>{hoverIndex=null;tip.style.display='none';drawPrice();$('ohlc').textContent='O - H - L - C -'};}

function drawSeriesCanvas(id, seriesList, zeroLine=null){const cv=$(id);if(!cv)return;const {c,w,h}=setupCanvas(cv);c.clearRect(0,0,w,h);const all=seriesList.flatMap(s=>s.values.filter(Number.isFinite));if(!all.length){c.fillStyle=css('--muted');c.font='12px system-ui';c.fillText('No research series yet',14,22);return}let min=Math.min(...all),max=Math.max(...all);if(zeroLine!=null){min=Math.min(min,zeroLine);max=Math.max(max,zeroLine)}if(max===min){max+=1;min-=1}const pad=(max-min)*.08;max+=pad;min-=pad;const M={l:44,r:12,t:12,b:28},n=Math.max(...seriesList.map(s=>s.values.length)),x=i=>M.l+i/(Math.max(1,n-1))*(w-M.l-M.r),y=v=>M.t+(max-v)/(max-min)*(h-M.t-M.b);c.font='10px system-ui';c.fillStyle=css('--muted');c.textAlign='right';for(let j=0;j<=4;j++){const v=max-(max-min)*j/4,yy=y(v);c.strokeStyle='#172432';c.beginPath();c.moveTo(M.l,yy);c.lineTo(w-M.r,yy);c.stroke();c.fillText(fmt(v,2),M.l-6,yy+3)}if(zeroLine!=null){c.strokeStyle='#52677d';c.setLineDash([4,4]);c.beginPath();c.moveTo(M.l,y(zeroLine));c.lineTo(w-M.r,y(zeroLine));c.stroke();c.setLineDash([])}for(const s of seriesList){line(c,s.values.map((v,i)=>[x(i),v==null?NaN:y(v)]),s.color,s.width||1.6)}c.textAlign='left';let lx=M.l;for(const s of seriesList){c.fillStyle=s.color;c.fillRect(lx,7,10,2);c.fillStyle=css('--muted');c.fillText(s.name,lx+14,10);lx+=85}}
function renderResearch(x){const rr=x.research?.latest_strategy_report||{},rs=rr.strategy||{},rb=rr.benchmark_buy_hold||{},ts=rr.timeseries?.rows||[];$('rrReturn').textContent=rr.generated_utc?fmt(rs.return_pct,3)+'%':'-';$('rrBench').textContent=rr.generated_utc?fmt(rb.return_pct,3)+'%':'-';$('rrExcess').textContent=rr.generated_utc?fmt(rr.excess_return_pct,3)+'%':'-';$('rrDD').textContent=rr.generated_utc?fmt(rs.max_drawdown_pct,3)+'%':'-';$('rrSharpe').textContent=fmt(rs.sharpe_like,3);$('rrPF').textContent=fmt(rs.profit_factor,3);$('rrWin').textContent=rs.win_rate_pct==null?'-':fmt(rs.win_rate_pct,1)+'%';$('rrOrders').textContent=rs.orders??'-';$('researchStamp').textContent=rr.generated_utc?rr.generated_utc.replace('T',' ').slice(0,19):'run: python run.py research --bars 1000';drawSeriesCanvas('equityChart',[{name:'Strategy',values:ts.map(r=>r.equity_index),color:css('--cyan')},{name:'BuyHold',values:ts.map(r=>r.benchmark_index),color:css('--gold')}],100);drawSeriesCanvas('drawdownChart',[{name:'Drawdown %',values:ts.map(r=>r.drawdown_pct),color:css('--red')}],0);drawSeriesCanvas('rollingChart',[{name:'Rolling Sharpe',values:ts.map(r=>r.rolling_sharpe),color:css('--blue')}],0);
 const scan=x.research?.latest_parameter_scan?.rows||[];$('scanRows').innerHTML=scan.slice(0,12).map(r=>`<tr><td>${r.fast_ema}/${r.slow_ema}</td><td>${fmt(r.train_return_pct,2)}</td><td>${fmt(r.test_return_pct,2)}</td><td>${fmt(r.test_excess_return_pct,2)}</td><td>${fmt(r.generalization_gap_pct,2)}</td></tr>`).join('')||'<tr><td colspan="5">Run scan</td></tr>';
 const wf=x.research?.latest_walkforward||{},folds=wf.folds||[];$('wfStability').textContent=wf.parameter_variation_ratio==null?'-':'variation '+fmt(wf.parameter_variation_ratio,2);$('wfRows').innerHTML=folds.map(r=>`<tr><td>${r.fold}</td><td>${r.selected_fast_ema}/${r.selected_slow_ema}</td><td>${fmt(r.train_return_pct,2)}</td><td>${fmt(r.oos_return_pct,2)}</td><td>${fmt(r.oos_max_drawdown_pct,2)}</td></tr>`).join('')||'<tr><td colspan="5">Run walkforward</td></tr>';
 const fr=x.research?.latest_factor_report||{},frows=fr.rows||[];$('factorRows').innerHTML=frows.slice(0,20).map(r=>`<tr><td>${r.factor}</td><td>${r.forward_bars}</td><td>${fmt(r.ic_mean,4)}</td><td>${fmt(r.icir,3)}</td><td>${r.ic_positive_pct==null?'-':fmt(r.ic_positive_pct,1)+'%'}</td><td>${r.observations}</td></tr>`).join('')||'<tr><td colspan="6">Run factors</td></tr>';$('factorNote').textContent=fr.discipline_note||'IC is a research filter, not a trading signal by itself.';
 const qr=x.research?.latest_qlib_ml_report||{},qm=qr.test_metrics||{},qs=qr.top_bottom_forward_spread||{},ci=qr.current_inference||{},qrows=ci.ranking||[];$('qlibIC').textContent=fmt(qm.ic_mean,4);$('qlibICIR').textContent=fmt(qm.icir,3);$('qlibPos').textContent=qm.ic_positive_pct==null?'-':fmt(qm.ic_positive_pct,1)+'%';$('qlibSpread').textContent=qs.mean_forward_spread_pct==null?'-':fmt(qs.mean_forward_spread_pct,3)+'%';$('qlibCurrentTime').textContent='Current inference: '+(ci.timestamp||'-')+' · future label unavailable';$('qlibRows').innerHTML=qrows.map(r=>`<tr><td>${r.symbol}</td><td>${fmt(r.score,5)}</td><td>N/A</td></tr>`).join('')||'<tr><td colspan="3">Install Qlib and run qlib-ml</td></tr>';$('qlibNote').textContent=qr.discipline_note||'Qlib candidates must pass native OOS / walk-forward / execution-cost validation.';
 const pt=x.research?.latest_promotion_ticket||{};$('promotionState').textContent=pt.status||'NO TICKET';$('promotionState').className=(pt.passed?'oktxt':(pt.status?'badtxt':'warntxt'));$('promotionTicket').textContent=pt.ticket_id||'-';$('promotionReasons').textContent=(pt.reasons&&pt.reasons.length)?pt.reasons.join(' · '):(pt.passed?`PASSED · expires ${pt.expires_utc||'-'} · still requires agent policy/approval`:'Run promotion-check with immutable strategy + walk-forward run IDs.');
 const j=x.research?.journal||[];$('journal').innerHTML=j.slice().reverse().map(r=>`<div class="journal-item"><b>${(r.timestamp_utc||'').slice(0,19)}</b><br><span class="note">H:</span> ${r.hypothesis||'-'}<br><span class="note">Accept:</span> ${r.acceptance_criteria||'-'}<br><span class="note">Result:</span> ${r.result||'-'}<br><span class="note">Conclusion:</span> ${r.conclusion||'-'}</div>`).join('')||'<div class="empty">No experiment journal yet.</div>';}
function setDiag(id,state,kind){const e=$(id);e.textContent=state;e.className='triage-state '+kind}
function renderDiagnostics(x){const ex=x.execution||{},cfg=x.monitoring||{},st=x.state||{},rr=x.research?.latest_strategy_report||{},ts=rr.timeseries||{},wf=x.research?.latest_walkforward||{};const slip=ex.avg_slippage_bps,slipLimit=cfg.slippage_alert_bps??10;if(st.reconciliation_required){setDiag('diagExec','HALTED · RECONCILE','badtxt');$('diagExecNote').textContent=st.reconciliation_note||'Exchange/local position mismatch; automatic orders are blocked.'}else if(slip==null){setDiag('diagExec','WAITING DATA','warntxt');$('diagExecNote').textContent=`${ex.fills||0} fills. Stops/take-profit are client-side in this alpha.`}else if(Math.abs(slip)>slipLimit){setDiag('diagExec','CHECK','badtxt');$('diagExecNote').textContent=`Avg slippage ${fmt(slip,2)} bps > ${fmt(slipLimit,1)} bps threshold.`}else{setDiag('diagExec','HEALTHY','oktxt');$('diagExecNote').textContent=`Avg slippage ${fmt(slip,2)} bps · fees ${fmt(ex.fees_quote,3)} quote · client-side stops.`}
 const regime=ts.market_regime||'NO DATA';setDiag('diagRegime',regime,regime==='HIGH_VOL'?'warntxt':(regime==='NO DATA'?'warntxt':'oktxt'));$('diagRegimeNote').textContent=ts.latest_market_vol_annualized_pct==null?'Run research to classify volatility regime.':`Latest vol ${fmt(ts.latest_market_vol_annualized_pct,1)}% vs sample median ${fmt(ts.median_market_vol_annualized_pct,1)}%.`;
 const sh=ts.latest_rolling_sharpe,th=cfg.sharpe_alert_threshold??0,variation=wf.parameter_variation_ratio;let bad=sh!=null&&sh<th;if(bad){setDiag('diagStrategy','CHECK','badtxt')}else if(sh==null){setDiag('diagStrategy','NO DATA','warntxt')}else{setDiag('diagStrategy','OBSERVE','oktxt')}$('diagStrategyNote').textContent=`Rolling Sharpe ${fmt(sh,2)} (threshold ${fmt(th,2)}); WF parameter variation ${fmt(variation,2)}. Do not retune from PnL alone.`}

function renderSystem(x){if(!x)return;const core=x.core||{};const defs=[['market_data','MARKET DATA'],['research_data','RESEARCH DATA'],['research','NATIVE RESEARCH'],['ml_research','ML RESEARCH'],['execution','EXECUTION']];const items=defs.map(([k,label])=>{const a=core[k]||{};const availability=a.available===false?' · unavailable':(a.available===true?' · available':'');return `<div class="row"><span>${label}</span><b>${a.name||'-'} · ${a.provider||'-'}${availability}</b></div><div class="note" style="padding:0 0 8px">${a.description||''}</div>`}).join('');$('activeAdapters').innerHTML=items||'<div class="empty">No adapters.</div>';const opt=x.optional_integrations||{};$('integrationRows').innerHTML=Object.entries(opt).map(([name,a])=>`<tr><td>${name}</td><td>${a.kind||'-'}</td><td>${a.python_package_detected?'detected':'not installed'}</td><td>${a.enabled?'YES':'NO'}</td><td style="text-align:left">${a.purpose||''}</td></tr>`).join('')||'<tr><td colspan="5">No optional slots.</td></tr>';const ag=x.agent_safety||{},p=ag.policy||{},g=ag.gateway||{};const cb=ag.circuit_breaker||{},si=ag.secret_isolation||{},ci=ag.capital_isolation||{};$('agentPolicy').innerHTML=`<div class="row"><span>Architecture</span><b>${ag.architecture||'-'}</b></div><div class="row"><span>Autonomy</span><b>${p.level||'-'} · level ${p.rank??'-'}</b></div><div class="row"><span>Trade approval</span><b>${p.trade_approval_required?'REQUIRED':'OFF'}</b></div><div class="row"><span>Circuit breaker</span><b>${cb.state||'NORMAL'}${cb.reason?' · '+cb.reason:''}</b></div><div class="row"><span>Live money</span><b>${p.live_money_enabled?'ENABLED':'DISABLED'}</b></div><div class="row"><span>Broker secret access</span><b>${g.broker_secret_access?'YES':'NO'}</b></div><div class="row"><span>Restricted agent CLI</span><b>${si.restricted_agent_cli||'-'}</b></div><div class="row"><span>Broker-level agent account</span><b>${ci.broker_side_dedicated_agent_account?'YES':'NOT YET'}</b></div><div class="row"><span>Decision receipts</span><b>${g.decision_receipts?'ON':'OFF'}</b></div>`;const skills=ag.skills?.skills||[];$('agentSkillRows').innerHTML=skills.map(a=>`<tr><td>${a.name}</td><td>${a.permission}</td><td>${a.min_autonomy}</td><td>${a.mutates_market_state?'YES':'NO'}</td></tr>`).join('')||'<tr><td colspan="4">No skills.</td></tr>';}
async function refreshCapabilities(){try{const r=await fetch('/api/capabilities',{cache:'no-store'}),x=await r.json();capabilityData=x;renderSystem(x)}catch(e){}}
async function refreshChart(){try{const r=await fetch(`/api/chart?interval=${encodeURIComponent(interval)}&limit=240`,{cache:'no-store'});if(!r.ok)throw new Error(await r.text());chartData=await r.json();$('symbol').textContent=chartData.symbol;$('emaLegend').innerHTML=`<b style="color:var(--gold)">EMA ${chartData.fast_ema}</b> · <b style="color:var(--blue)">EMA ${chartData.slow_ema}</b> · Volume`;renderTradeCharts();$('err').style.display='none'}catch(e){$('err').textContent='Chart data error: '+e;$('err').style.display='block'}}
async function refreshResearch(){try{const r=await fetch('/api/research',{cache:'no-store'}),x=await r.json();researchData=x;renderResearch(x);if(statusData)renderDiagnostics({...statusData,research:x.research})}catch(e){}}
async function refreshStatus(){try{const r=await fetch('/api/status',{cache:'no-store'}),x=await r.json(),s=x.state;statusData=x;$('mode').textContent=x.mode.toUpperCase();$('strategy').textContent=x.strategy;$('run').textContent=x.engine_running?`RUNNING · ${x.engine_pid}`:'ENGINE STOPPED';$('run').className='status '+(x.engine_running?'ok':'bad');$('engine').textContent=x.engine_running?'RUNNING':'STOPPED';$('lastPrice').textContent=nice(s.last_price);$('pos').textContent=fmt(s.base_qty,8);$('entry').textContent=nice(s.avg_entry);$('rpnl').textContent=fmt(s.realized_pnl,4);$('upnl').textContent=fmt(s.unrealized_pnl_mark,4);$('cash').textContent=fmt(s.quote_balance,2);$('signal').textContent=s.last_signal||'-';$('updated').textContent=(s.last_update_utc||'-').replace('T',' ').slice(0,19);$('equity').textContent=s.marked_equity==null?'-':fmt(s.marked_equity,2);const rr=x.research?.latest_strategy_report||{},rs=rr.strategy||{},rb=rr.benchmark_buy_hold||{};$('rret').textContent=rr.generated_utc?fmt(rs.return_pct,3)+'%':'run research';$('bret').textContent=rr.generated_utc?fmt(rb.return_pct,3)+'%':'-';$('exret').textContent=rr.generated_utc?fmt(rr.excess_return_pct,3)+'%':'-';$('rdd').textContent=rr.generated_utc?fmt(rs.max_drawdown_pct,3)+'%':'-';$('events').textContent=(x.recent_events||[]).slice(-16).join('\n')||'No events yet.';const rows=(x.recent_trades||[]).slice().reverse().map(t=>`<div class="trade"><b class="${t.side==='BUY'?'buy':'sell'}">${t.side}</b><div><div>${fmt(t.price,4)} · ${fmt(t.base_qty,8)}</div><div style="color:var(--muted)">${(t.time_utc||'').replace('T',' ').slice(0,19)}</div></div></div>`).join('');$('trades').innerHTML=rows||'<span style="color:var(--muted)">No trades yet.</span>';renderDiagnostics({...x,research:(researchData?.research||x.research)})}catch(e){$('run').textContent='STATUS ERROR';$('run').className='status bad'}}
$('tabs').onclick=e=>{const b=e.target.closest('button[data-view]');if(!b)return;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===b.dataset.view));if(researchData)renderResearch(researchData);if(statusData)renderDiagnostics({...statusData,research:(researchData?.research||statusData.research)});if(capabilityData)renderSystem(capabilityData);setTimeout(()=>{renderTradeCharts();if(researchData)renderResearch(researchData)},30)};$('timeframes').onclick=e=>{const b=e.target.closest('button[data-tf]');if(!b)return;interval=b.dataset.tf;document.querySelectorAll('#timeframes button').forEach(x=>x.classList.toggle('active',x===b));refreshChart()};window.addEventListener('resize',()=>{if(!lwcReady()){drawPrice();drawRsi()}if(researchData)renderResearch(researchData)});if(!lwcReady())bindHover();refreshStatus();refreshResearch();refreshCapabilities();refreshChart();setInterval(refreshStatus,3000);setInterval(refreshResearch,15000);setInterval(refreshChart,15000);
</script></body></html>'''


def run_dashboard(settings: Settings, mode: str = "paper", host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Core V1.2.2 dashboard is loopback-only. Remote binding is blocked until authenticated remote access is implemented.")
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, obj, code=200):
            payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/status":
                self._send_json(build_status(settings, mode))
                return
            if path == "/api/research":
                self._send_json({"research": build_research_bundle(settings)})
                return
            if path == "/api/capabilities":
                self._send_json(AdapterRegistry(settings).capabilities())
                return
            if path == "/api/chart":
                q = parse_qs(parsed.query)
                interval = q.get("interval", [settings.market["interval"]])[0]
                try:
                    limit = int(q.get("limit", [240])[0])
                    self._send_json(build_chart_payload(settings, mode, interval, limit))
                except Exception as exc:
                    self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if path in ("/", "/index.html"):
                payload = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_error(404)

        def log_message(self, format, *args):
            return

    url = f"http://{host}:{port}"
    print(f"Trading Dashboard: {url}  mode={mode}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped")
    finally:
        server.server_close()
