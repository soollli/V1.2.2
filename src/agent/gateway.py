from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .policy import AutonomyPolicy
from .receipts import payload_hash, write_receipt
from .skills import SkillRegistry
from .approvals import validate_human_approval, consume_human_approval
from .circuit import circuit_status
from ..promotion import load_promotion_ticket, load_research_run
from ..state import PortfolioState


@dataclass
class ActionRequest:
    skill: str
    requested_by: str = "hermes"
    mode: str = "paper"
    payload: dict[str, Any] = field(default_factory=dict)
    promotion_ticket: str | None = None
    approval_id: str | None = None
    correlation_id: str | None = None


@dataclass
class ActionDecision:
    status: str
    authorized: bool
    reasons: list[str]
    skill: str
    mode: str
    receipt_id: str | None = None
    receipt_path: str | None = None


class ActionGateway:
    """Deterministic policy gate between an LLM/agent and market-mutating tools.

    The gateway authorizes requests; it does not hold broker credentials and it
    deliberately does not dispatch orders in this alpha.
    """
    def __init__(self, settings):
        self.settings = settings
        agent_cfg = settings.raw.get("agent", {})
        self.policy = AutonomyPolicy.from_config(agent_cfg)
        self.skills = SkillRegistry(agent_cfg)

    def _testnet_reconciliation_reason(self, mode: str) -> str | None:
        if mode != "binance_testnet":
            return None
        state_path = self.settings.root / str(self.settings.storage["state_file"]).format(mode=mode)
        state = PortfolioState.load(state_path, self.settings.broker["initial_quote_balance"])
        if state.reconciliation_required:
            return f"testnet reconciliation_required: {state.reconciliation_note}"
        return None

    def evaluate(self, req: ActionRequest, *, write: bool = True) -> ActionDecision:
        reasons: list[str] = []
        skill = self.skills.get(req.skill)
        if skill is None:
            reasons.append("unknown or disabled skill")
        else:
            if not self.policy.allows_level(skill.min_autonomy):
                reasons.append(f"autonomy {self.policy.level} below required {skill.min_autonomy}")
            if skill.live_money or req.mode == "live":
                reasons.append("live-money execution is not implemented/enabled")
            if req.skill == "strategy.propose":
                run_ids = req.payload.get("run_ids") or []
                if not run_ids:
                    reasons.append("strategy proposal requires immutable research run_ids")
                else:
                    for run_id in run_ids:
                        try:
                            load_research_run(self.settings.root, str(run_id))
                        except Exception as exc:
                            reasons.append(f"research evidence invalid: {type(exc).__name__}: {exc}")
            if req.skill == "execution.paper" and req.mode != "paper":
                reasons.append("execution.paper requires mode=paper")
            if req.skill == "execution.testnet" and req.mode != "binance_testnet":
                reasons.append("execution.testnet requires mode=binance_testnet")
            approval_valid = False
            if skill.mutates_market_state and self.policy.trade_approval_required:
                if not req.approval_id:
                    reasons.append("out-of-band human approval receipt required by policy")
                else:
                    approval_valid, approval_reason, _ = validate_human_approval(
                        self.settings.root, approval_id=req.approval_id, skill=req.skill, mode=req.mode,
                        payload=req.payload, promotion_ticket=req.promotion_ticket,
                    )
                    if not approval_valid:
                        reasons.append(approval_reason)
            quote_amount = req.payload.get("quote_amount")
            if quote_amount is not None and float(quote_amount) > self.policy.max_agent_quote_order:
                reasons.append(f"quote_amount {quote_amount} exceeds agent limit {self.policy.max_agent_quote_order}")
            if skill.mutates_market_state:
                cb = circuit_status(self.settings.root)
                if cb.get("halted"):
                    reasons.append(f"agent circuit breaker HALTED: {cb.get('reason')}")
            if skill.mutates_market_state and str(req.payload.get("side", "BUY")).upper() == "BUY" and quote_amount is not None:
                state_path = self.settings.root / str(self.settings.storage["state_file"]).format(mode=req.mode)
                state = PortfolioState.load(state_path, self.settings.broker["initial_quote_balance"])
                if state.base_qty > 0 and float(state.last_price or 0) <= 0:
                    reasons.append("cannot enforce agent position budget because current position has no valid mark price")
                else:
                    current_position_quote = float(state.base_qty) * float(state.last_price or 0)
                    projected = current_position_quote + float(quote_amount)
                    if projected > self.policy.max_agent_position_quote:
                        reasons.append(f"projected agent position {projected:.4f} exceeds {self.policy.max_agent_position_quote:.4f}")
            if skill.requires_promotion:
                if not req.promotion_ticket:
                    reasons.append("promotion ticket required for AI-triggered execution")
                else:
                    try:
                        ticket = load_promotion_ticket(self.settings.root, req.promotion_ticket)
                        if not ticket.get("passed") or ticket.get("status") != "PASSED":
                            reasons.append("promotion ticket is not PASSED")
                        expires = ticket.get("expires_utc")
                        if expires:
                            expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                            if datetime.now(timezone.utc) >= expiry:
                                reasons.append("promotion ticket expired")
                    except Exception as exc:
                        reasons.append(f"promotion ticket invalid: {type(exc).__name__}: {exc}")
            recon = self._testnet_reconciliation_reason(req.mode)
            if skill.mutates_market_state and recon:
                reasons.append(recon)

        authorized = not reasons
        status = "AUTHORIZED" if authorized else ("PENDING_APPROVAL" if reasons == ["out-of-band human approval receipt required by policy"] else "REJECTED")
        receipt = {
            "decision": status,
            "authorized": authorized,
            "reasons": reasons,
            "request": asdict(req),
            "payload_sha256": payload_hash(req.payload),
            "policy": self.policy.to_dict(),
            "skill": asdict(skill) if skill else None,
            "invariants": {
                "gateway_holds_broker_secret": False,
                "gateway_dispatches_orders": False,
                "live_money_enabled": False,
            },
            "evaluated_utc": datetime.now(timezone.utc).isoformat(),
        }
        receipt_id = receipt_path = None
        if write:
            receipt_id, path = write_receipt(self.settings.root, receipt)
            receipt_path = str(path)
            if authorized and skill is not None and skill.mutates_market_state and self.policy.trade_approval_required and req.approval_id:
                consume_human_approval(self.settings.root, req.approval_id, receipt_id)
        return ActionDecision(status, authorized, reasons, req.skill, req.mode, receipt_id, receipt_path)

    def capabilities(self) -> dict[str, Any]:
        return {
            "architecture": "single_agent_loop_plus_deterministic_skills",
            "agent_loop_runtime": "external_hermes_provider_agnostic",
            "policy": self.policy.to_dict(),
            "skills": self.skills.capabilities(),
            "circuit_breaker": circuit_status(self.settings.root),
            "capital_isolation": {
                "paper_state_separated": True,
                "testnet_state_separated": True,
                "broker_side_dedicated_agent_account": False,
                "note": "Robinhood-style broker-level dedicated Agentic Account is not implemented; use separate testnet credentials/account for isolation.",
            },
            "secret_isolation": {
                "project_dotenv_loaded_by_research": False,
                "testnet_keys_loaded_only_by_execution_adapter": True,
                "restricted_agent_cli": "scripts/agent_cli.py",
                "unrestricted_agent_shell_supported": False,
            },
            "gateway": {
                "implemented": True,
                "broker_secret_access": False,
                "dispatches_orders": False,
                "decision_receipts": True,
                "out_of_band_one_time_approvals": True,
                "promotion_ticket_required_for_agent_execution": True,
                "live_money_enabled": False,
            },
        }
