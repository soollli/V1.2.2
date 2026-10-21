from __future__ import annotations
from dataclasses import dataclass
from typing import Any


AUTONOMY_LEVELS = {
    "observe": 0,
    "research": 1,
    "propose": 2,
    "paper": 3,
    "testnet": 4,
    "guarded_live": 5,
    "bounded_live": 6,
}


@dataclass(frozen=True)
class AutonomyPolicy:
    level: str = "propose"
    trade_approval_required: bool = True
    live_money_enabled: bool = False
    max_agent_quote_order: float = 50.0
    max_agent_position_quote: float = 250.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "AutonomyPolicy":
        cfg = cfg or {}
        level = str(cfg.get("autonomy_level", "propose")).lower()
        if level not in AUTONOMY_LEVELS:
            raise ValueError(f"unknown autonomy_level: {level}")
        return cls(
            level=level,
            trade_approval_required=bool(cfg.get("trade_approval_required", True)),
            live_money_enabled=bool(cfg.get("live_money_enabled", False)),
            max_agent_quote_order=float(cfg.get("max_agent_quote_order", 50.0)),
            max_agent_position_quote=float(cfg.get("max_agent_position_quote", 250.0)),
        )

    @property
    def rank(self) -> int:
        return AUTONOMY_LEVELS[self.level]

    def allows_level(self, minimum: str) -> bool:
        return self.rank >= AUTONOMY_LEVELS[minimum]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "rank": self.rank,
            "trade_approval_required": self.trade_approval_required,
            "live_money_enabled": self.live_money_enabled,
            "max_agent_quote_order": self.max_agent_quote_order,
            "max_agent_position_quote": self.max_agent_position_quote,
        }
