from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

import yaml

from src.config import Settings
from src.agent import SkillRegistry, ActionGateway, ActionRequest, create_human_approval
from src.promotion import evaluate_promotion


def make_settings(tmp_path: Path, *, autonomy="propose", approval=True) -> Settings:
    raw = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))
    raw = deepcopy(raw)
    raw["agent"]["autonomy_level"] = autonomy
    raw["agent"]["trade_approval_required"] = approval
    return Settings(raw=raw, root=tmp_path)


def write_run(root: Path, run_id: str, kind: str, report: dict):
    d = root / "research" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "kind": kind,
        "data_sha256": "data",
        "report_sha256": "report",
        "reproducibility": {
            "immutable_run_directory": True,
            "environment_captured": True,
            "config_captured": True,
            "data_fingerprint_captured": True,
        },
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "report.json").write_text(json.dumps(report), encoding="utf-8")


def passing_ticket(settings: Settings):
    write_run(settings.root, "strategy_1", "strategy", {
        "strategy": {"max_drawdown_pct": -8.0, "orders": 12, "fill_mode": "next_open"},
        "excess_return_pct": 2.5,
    })
    write_run(settings.root, "wf_1", "walkforward", {
        "folds": [
            {"oos_return_pct": 1.0},
            {"oos_return_pct": 0.5},
            {"oos_return_pct": 1.2},
        ],
        "parameter_variation_ratio": 0.67,
    })
    return evaluate_promotion(settings.root, settings.raw, ["strategy_1", "wf_1"])


def test_skill_registry_is_deterministic_and_can_disable():
    r = SkillRegistry({"disabled_skills": ["execution.testnet"]})
    assert r.get("research.factor") is not None
    assert r.get("execution.testnet") is None
    assert r.get("execution.live").live_money is True


def test_default_propose_policy_blocks_paper_and_writes_receipt(tmp_path):
    s = make_settings(tmp_path, autonomy="propose", approval=True)
    g = ActionGateway(s)
    d = g.evaluate(ActionRequest(skill="execution.paper", mode="paper"))
    assert not d.authorized
    assert any("autonomy" in x for x in d.reasons)
    assert d.receipt_id
    assert Path(d.receipt_path).exists()


def test_promotion_gate_passes_only_with_strategy_and_walkforward(tmp_path):
    s = make_settings(tmp_path)
    ticket = passing_ticket(s)
    assert ticket["passed"] is True
    assert ticket["status"] == "PASSED"
    assert ticket["expires_utc"]
    rejected = evaluate_promotion(s.root, s.raw, ["strategy_1"])
    assert rejected["passed"] is False
    assert any("missing walkforward" in x for x in rejected["reasons"])


def test_agent_paper_execution_requires_promotion_and_out_of_band_approval(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=True)
    ticket = passing_ticket(s)
    g = ActionGateway(s)
    payload = {"side": "BUY", "quote_amount": 25}
    no_approval = g.evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"], payload=payload,
    ))
    assert not no_approval.authorized
    assert "out-of-band human approval receipt required by policy" in no_approval.reasons
    approval = create_human_approval(
        s.root, skill="execution.paper", mode="paper", payload=payload,
        promotion_ticket=ticket["ticket_id"], ttl_minutes=10,
    )
    approved = g.evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        approval_id=approval["approval_id"], payload=payload,
    ))
    assert approved.authorized
    assert approved.status == "AUTHORIZED"
    # Approval is one-time and cannot be replayed by the agent.
    replay = g.evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        approval_id=approval["approval_id"], payload=payload,
    ))
    assert not replay.authorized
    assert "human approval receipt already consumed" in replay.reasons

def test_gateway_rejects_order_over_agent_quote_limit(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=False)
    ticket = passing_ticket(s)
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        payload={"quote_amount": 500},
    ))
    assert not d.authorized
    assert any("exceeds agent limit" in x for x in d.reasons)


def test_live_execution_is_always_rejected(tmp_path):
    s = make_settings(tmp_path, autonomy="bounded_live", approval=False)
    d = ActionGateway(s).evaluate(ActionRequest(skill="execution.live", mode="live"))
    assert not d.authorized
    assert any("live-money" in x for x in d.reasons)


def test_expired_promotion_ticket_is_rejected(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=False)
    ticket = passing_ticket(s)
    p = s.root / "research" / "promotions" / f"{ticket['ticket_id']}.json"
    obj = json.loads(p.read_text())
    obj["expires_utc"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    p.write_text(json.dumps(obj), encoding="utf-8")
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
    ))
    assert not d.authorized
    assert "promotion ticket expired" in d.reasons

def test_strategy_proposal_requires_research_run_ids(tmp_path):
    s = make_settings(tmp_path, autonomy="propose", approval=True)
    g = ActionGateway(s)
    bad = g.evaluate(ActionRequest(skill="strategy.propose", mode="paper", payload={}))
    assert not bad.authorized
    assert "strategy proposal requires immutable research run_ids" in bad.reasons
    write_run(s.root, "r1", "strategy", {"strategy": {"fill_mode": "next_open"}})
    good = g.evaluate(ActionRequest(skill="strategy.propose", mode="paper", payload={"run_ids": ["r1"]}))
    assert good.authorized


def test_agent_position_budget_is_enforced(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=False)
    ticket = passing_ticket(s)
    # Seed a marked paper position worth 240 quote; another 20 should fail the 250 cap.
    state_path = s.root / str(s.storage["state_file"]).format(mode="paper")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "quote_balance": 1000.0, "base_qty": 2.0, "avg_entry": 100.0,
        "cost_basis_quote": 200.0, "realized_pnl": 0.0, "last_bar_time": "",
        "last_price": 120.0, "last_signal": "HOLD", "last_reason": "",
        "last_update_utc": "", "reconciliation_required": False,
        "reconciliation_note": "", "last_account_sync_utc": ""
    }), encoding="utf-8")
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        payload={"side": "BUY", "quote_amount": 20},
    ))
    assert not d.authorized
    assert any("projected agent position" in x for x in d.reasons)

def test_circuit_breaker_blocks_agent_execution(tmp_path):
    from src.agent import set_circuit
    s = make_settings(tmp_path, autonomy="paper", approval=False)
    ticket = passing_ticket(s)
    set_circuit(s.root, halted=True, reason="operator_test")
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        payload={"side": "BUY", "quote_amount": 10},
    ))
    assert not d.authorized
    assert any("circuit breaker HALTED" in x for x in d.reasons)


def test_human_approval_is_payload_bound(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=True)
    ticket = passing_ticket(s)
    approved_payload = {"side": "BUY", "quote_amount": 10}
    approval = create_human_approval(
        s.root, skill="execution.paper", mode="paper", payload=approved_payload,
        promotion_ticket=ticket["ticket_id"], ttl_minutes=10,
    )
    altered = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket=ticket["ticket_id"],
        approval_id=approval["approval_id"], payload={"side": "BUY", "quote_amount": 11},
    ))
    assert not altered.authorized
    assert "human approval does not match action payload" in altered.reasons


def test_external_identifiers_reject_path_traversal(tmp_path):
    s = make_settings(tmp_path, autonomy="paper", approval=False)
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="execution.paper", mode="paper", promotion_ticket="../../etc/passwd",
        payload={"side": "BUY", "quote_amount": 10},
    ))
    assert not d.authorized
    assert any("unsafe promotion ticket id" in x for x in d.reasons)


def test_strategy_proposal_rejects_nonexistent_evidence(tmp_path):
    s = make_settings(tmp_path, autonomy="propose", approval=True)
    d = ActionGateway(s).evaluate(ActionRequest(
        skill="strategy.propose", mode="paper", payload={"run_ids": ["does_not_exist"]}
    ))
    assert not d.authorized
    assert any("research evidence invalid" in x for x in d.reasons)
