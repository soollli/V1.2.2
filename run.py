#!/usr/bin/env python3
import argparse
import json
import os
import sys

from src.config import load_settings
from src.engine import TradingEngine
from src.backtest import run_backtest
from src.dashboard import run_dashboard
from src.monitor import print_status_json, build_status, build_research_bundle
from src.doctor import run_doctor
from src.research import save_report, append_experiment_journal
from src.research_runs import archive_research_run
from src.factors import fetch_close_matrix
from src.portfolio_research import capm_report, portfolio_report, analyze_portfolio_research
from src.theory_backtests import theories_report
from src.core.registry import AdapterRegistry
from src.agent import SkillRegistry, ActionGateway, ActionRequest, create_human_approval, circuit_status, set_circuit
from src.promotion import evaluate_promotion
from src.agent.tool_policy import is_operator_only


def _registry(settings):
    return AdapterRegistry(settings)


def _load_bars(settings, bars: int):
    md = _registry(settings).data(use_testnet=False)
    df = md.history(settings.market["symbol"], settings.market["interval"], int(bars), closed_only=True, use_cache=True, strict=True)
    return df


def main():
    p = argparse.ArgumentParser(description="AI Quant Terminal Core V1: modular data/research/execution terminal")
    p.add_argument("command", choices=[
        "paper", "testnet", "backtest", "research", "scan", "walkforward", "factors", "capm", "portfolio", "theories",
        "journal", "dashboard", "terminal", "status", "snapshot", "doctor", "capabilities",
        "openbb-check", "openbb-equity", "openbb-macro", "openbb-filings",
        "qlib-check", "qlib-ml", "skills", "agent-policy", "promotion-check", "human-approve", "gateway-check", "circuit-status", "circuit-halt", "circuit-reset"
    ])
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--bars", type=int, default=1000)
    p.add_argument("--mode", choices=["paper", "binance_testnet"], default="paper")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open-browser", action="store_true")
    p.add_argument("--hypothesis", default="")
    p.add_argument("--change", default="")
    p.add_argument("--acceptance", default="")
    p.add_argument("--result", default="")
    p.add_argument("--conclusion", default="")
    p.add_argument("--symbol", default="AAPL")
    p.add_argument("--provider", default="cboe")
    p.add_argument("--start-date", default="")
    p.add_argument("--end-date", default="")
    p.add_argument("--interval", default="1d")
    p.add_argument("--form-type", default="10-K")
    p.add_argument("--skill", default="market.snapshot")
    p.add_argument("--promotion-ticket", default="")
    p.add_argument("--run-id", action="append", default=[])
    p.add_argument("--quote-amount", type=float, default=0.0)
    p.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    p.add_argument("--approval-id", default="")
    p.add_argument("--approval-ttl-minutes", type=float, default=10.0)
    p.add_argument("--requested-by", default="hermes")
    p.add_argument("--reason", default="")
    args = p.parse_args()

    s = load_settings(args.config)
    if os.getenv("AI_QUANT_AGENT_CONTEXT", "").strip() == "1" and is_operator_only(s.root, args.command):
        raise SystemExit(f"DENIED_BY_TOOL_POLICY: operator-only command '{args.command}' is unavailable in agent context")
    registry = _registry(s)

    if args.command == "paper":
        TradingEngine(s, force_mode="paper").run_forever()
    elif args.command == "testnet":
        TradingEngine(s, force_mode="binance_testnet").run_forever()
    elif args.command == "backtest":
        df = _load_bars(s, args.bars)
        r = run_backtest(df, s.strategy, s.risk, s.broker["initial_quote_balance"])
        print(f"start_equity={r.start_equity:.2f}")
        print(f"end_equity={r.end_equity:.2f}")
        print(f"return_pct={r.return_pct:.3f}%")
        print(f"trades={r.trades}")
        print(f"realized_pnl={r.realized_pnl:.2f}")
        print(f"fees_paid={r.fees_paid:.4f}")
    elif args.command in {"research", "scan", "walkforward"}:
        df = _load_bars(s, args.bars)
        research_dir = s.root / s.raw.get("research", {}).get("output_dir", "research/results")
        research_dir.mkdir(parents=True, exist_ok=True)
        research = registry.research()
        if args.command == "research":
            report = research.strategy_report(df, s.strategy, s.risk, s.broker["initial_quote_balance"], s.market["interval"])
            report["engine"] = research.info.name
            run_id, run_dir = archive_research_run(s.root, kind="strategy", report=report, config=s.raw, data=df, latest_path=research_dir / "latest_strategy_report.json")
            report["run_id"] = run_id
            path = run_dir / "report.json"
        elif args.command == "scan":
            report = research.parameter_scan(df, s.strategy, s.risk, s.broker["initial_quote_balance"], s.market["interval"])
            report["engine"] = research.info.name
            run_id, run_dir = archive_research_run(s.root, kind="parameter_scan", report=report, config=s.raw, data=df, latest_path=research_dir / "latest_parameter_scan.json")
            report["run_id"] = run_id
            path = run_dir / "report.json"
        else:
            report = research.walk_forward(df, s.strategy, s.risk, s.broker["initial_quote_balance"], s.market["interval"])
            report["engine"] = research.info.name
            run_id, run_dir = archive_research_run(s.root, kind="walkforward", report=report, config=s.raw, data=df, latest_path=research_dir / "latest_walkforward.json")
            report["run_id"] = run_id
            path = run_dir / "report.json"
        report["engine"] = research.info.name
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(f"saved={path}")
    elif args.command == "factors":
        rcfg = s.raw.get("factor_research", {})
        universe = list(rcfg.get("universe", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]))
        interval = str(rcfg.get("interval", "1h"))
        md = registry.data(use_testnet=False)
        closes = fetch_close_matrix(md, universe, interval, int(args.bars))
        if closes.empty or closes.shape[1] < 5:
            raise SystemExit("factor research needs at least 5 aligned symbols")
        research = registry.research()
        report = research.factor_report(closes, rcfg)
        report["engine"] = research.info.name
        report["data_provider"] = md.info.name
        research_dir = s.root / s.raw.get("research", {}).get("output_dir", "research/results")
        run_id, run_dir = archive_research_run(s.root, kind="factor", report=report, config=s.raw, data=closes, latest_path=research_dir / "latest_factor_report.json")
        report["run_id"] = run_id
        path = run_dir / "report.json"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(f"saved={path}")
    elif args.command in {"capm", "portfolio", "theories"}:
        rcfg = s.raw.get("factor_research", {})
        pcfg = s.raw.get("portfolio_research", {})
        universe = list(pcfg.get("universe", rcfg.get("universe", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"])))
        interval = str(pcfg.get("interval", rcfg.get("interval", "1h")))
        annualization = str(s.raw.get("research", {}).get("annualization", "crypto_24x7"))
        md = registry.data(use_testnet=False)
        closes = fetch_close_matrix(md, universe, interval, int(args.bars))
        if closes.empty or closes.shape[1] < 5:
            raise SystemExit("CAPM/portfolio/theories research needs at least 5 aligned symbols; check network/universe/bars")
        research = registry.research()
        research_dir = s.root / s.raw.get("research", {}).get("output_dir", "research/results")
        if args.command == "theories":
            tcfg = s.raw.get("theory_tests", {})
            report = theories_report(closes, tcfg, interval, annualization)
            kind = "theories"
        else:
            report = capm_report(closes, pcfg, interval, annualization) if args.command == "capm" else portfolio_report(closes, pcfg, interval, annualization)
            kind = args.command
        report["engine"] = research.info.name
        report["data_provider"] = md.info.name
        run_id, run_dir = archive_research_run(s.root, kind=kind, report=report, config=s.raw, data=closes,
                                               latest_path=research_dir / f"latest_{kind}_report.json")
        report["run_id"] = run_id
        path = run_dir / "report.json"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(f"saved={path}")
    elif args.command == "journal":
        path = s.root / s.raw.get("research", {}).get("journal_file", "research/experiment_journal.jsonl")
        append_experiment_journal(path, args.hypothesis, args.change, args.acceptance, args.result, args.conclusion)
        print(f"saved={path}")
    elif args.command in {"dashboard", "terminal"}:
        run_dashboard(s, mode=args.mode, host=args.host, port=args.port, open_browser=(args.open_browser or args.command == "terminal"))
    elif args.command == "status":
        print_status_json(s, mode=args.mode)
    elif args.command == "snapshot":
        print(json.dumps({
            "status": build_status(s, mode=args.mode),
            "research": build_research_bundle(s),
            "capabilities": registry.capabilities(),
        }, ensure_ascii=False, indent=2, default=str))
    elif args.command == "doctor":
        sys.exit(run_doctor(s, mode=args.mode))
    elif args.command == "capabilities":
        print(json.dumps(registry.capabilities(), ensure_ascii=False, indent=2))
    elif args.command == "openbb-check":
        try:
            rd = registry.research_data()
            print(json.dumps({
                "adapter": rd.info.name,
                "health": rd.health(network=False),
                "coverage": rd.coverage(),
            }, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "install": "pip install -r requirements-openbb.txt",
            }, ensure_ascii=False, indent=2))
            sys.exit(2)
    elif args.command == "openbb-equity":
        rd = registry.research_data()
        df = rd.equity_history(
            args.symbol,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
            interval=args.interval,
            provider=args.provider,
        )
        print(df.tail(30).to_string(index=False))
    elif args.command == "openbb-macro":
        rd = registry.research_data()
        df = rd.fred_series(
            args.symbol,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
        )
        print(df.tail(30).to_string(index=False))
    elif args.command == "openbb-filings":
        rd = registry.research_data()
        df = rd.company_filings(
            args.symbol,
            form_type=args.form_type or None,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
        )
        print(df.head(30).to_string(index=False))
    elif args.command == "skills":
        print(json.dumps(SkillRegistry(s.raw.get("agent", {})).capabilities(), ensure_ascii=False, indent=2))
    elif args.command == "agent-policy":
        print(json.dumps(ActionGateway(s).capabilities(), ensure_ascii=False, indent=2))
    elif args.command == "promotion-check":
        if not args.run_id:
            raise SystemExit("promotion-check requires one or more --run-id values (at minimum strategy + walkforward)")
        ticket = evaluate_promotion(s.root, s.raw, list(args.run_id))
        print(json.dumps(ticket, ensure_ascii=False, indent=2, default=str))
    elif args.command == "human-approve":
        payload = {"side": args.side}
        if args.quote_amount:
            payload["quote_amount"] = float(args.quote_amount)
        if args.run_id:
            payload["run_ids"] = list(args.run_id)
        approval = create_human_approval(
            s.root, skill=args.skill, mode=args.mode, payload=payload,
            promotion_ticket=(args.promotion_ticket or None), ttl_minutes=args.approval_ttl_minutes,
        )
        print(json.dumps(approval, ensure_ascii=False, indent=2, default=str))
    elif args.command == "circuit-status":
        print(json.dumps(circuit_status(s.root), ensure_ascii=False, indent=2))
    elif args.command == "circuit-halt":
        print(json.dumps(set_circuit(s.root, halted=True, reason=args.reason or "manual_operator_halt"), ensure_ascii=False, indent=2))
    elif args.command == "circuit-reset":
        print(json.dumps(set_circuit(s.root, halted=False, reason=args.reason or "manual_operator_reset"), ensure_ascii=False, indent=2))
    elif args.command == "gateway-check":
        gateway = ActionGateway(s)
        payload = {}
        if args.quote_amount:
            payload["quote_amount"] = float(args.quote_amount)
        payload["side"] = args.side
        if args.run_id:
            payload["run_ids"] = list(args.run_id)
        decision = gateway.evaluate(ActionRequest(
            skill=args.skill, requested_by=args.requested_by, mode=args.mode, payload=payload,
            promotion_ticket=(args.promotion_ticket or None), approval_id=(args.approval_id or None),
        ))
        print(json.dumps(decision.__dict__, ensure_ascii=False, indent=2, default=str))
        if not decision.authorized:
            sys.exit(3)
    elif args.command == "qlib-check":
        ml = registry.ml_research()
        health = ml.health()
        print(json.dumps(health, ensure_ascii=False, indent=2, default=str))
        if not health.get("ok"):
            print("install=pip install -r requirements-qlib.txt")
            sys.exit(2)
    elif args.command == "qlib-ml":
        rcfg = s.raw.get("factor_research", {})
        qcfg = s.raw.get("qlib_research", {})
        universe = list(qcfg.get("universe", rcfg.get("universe", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"])))
        interval = str(qcfg.get("interval", rcfg.get("interval", "1h")))
        md = registry.data(use_testnet=False)
        closes = fetch_close_matrix(md, universe, interval, int(args.bars))
        if closes.empty or closes.shape[1] < int(qcfg.get("min_assets", 5)):
            raise SystemExit("Qlib ML research needs enough aligned assets; check network/universe/bars")
        ml = registry.ml_research()
        report = ml.ml_report(closes, qcfg)
        report["data_provider"] = md.info.name
        report["interval"] = interval
        research_dir = s.root / s.raw.get("research", {}).get("output_dir", "research/results")
        run_id, run_dir = archive_research_run(s.root, kind="qlib_ml", report=report, config=s.raw, data=closes, latest_path=research_dir / "latest_qlib_ml_report.json")
        report["run_id"] = run_id
        path = run_dir / "report.json"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(f"saved={path}")


if __name__ == "__main__":
    main()
