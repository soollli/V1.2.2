from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Skill:
    name: str
    layer: str
    permission: str
    min_autonomy: str
    mutates_market_state: bool
    live_money: bool
    description: str
    requires_promotion: bool = False


_BUILTINS = (
    Skill("market.snapshot", "data", "read", "observe", False, False,
          "Read canonical market/status snapshots."),
    Skill("portfolio.status", "portfolio", "read", "observe", False, False,
          "Read local paper/testnet portfolio state and reconciliation status."),
    Skill("research.strategy", "research", "research", "research", False, False,
          "Run deterministic native strategy research/backtest."),
    Skill("research.factor", "research", "research", "research", False, False,
          "Run cross-sectional factor research."),
    Skill("research.qlib", "research", "research", "research", False, False,
          "Run optional Qlib ML candidate research."),
    Skill("research.capm", "research", "research", "research", False, False,
          "Run single-factor CAPM/SML diagnostics on the cross-sectional universe."),
    Skill("research.portfolio", "research", "research", "research", False, False,
          "Run walk-forward portfolio candidates (equal-weight / min-var / MVO-shrinkage / risk-parity) with next-open cost accounting."),
    Skill("research.theories", "research", "research", "research", False, False,
          "Run the four-theory backtest battery: CAPM tercile sort, weak-form EMH (Ljung-Box/variance-ratio/GARCH), Black-Scholes assumption tests, cointegration-pair statistical arbitrage with cost hurdle."),
    Skill("research.walkforward", "research", "research", "research", False, False,
          "Run native walk-forward validation."),
    Skill("strategy.propose", "agent", "propose", "propose", False, False,
          "Create a strategy/portfolio proposal grounded in immutable research run IDs."),
    Skill("execution.paper", "execution", "execute", "paper", True, False,
          "Request bounded paper execution through the deterministic engine.", True),
    Skill("execution.testnet", "execution", "execute", "testnet", True, False,
          "Request Binance Spot Testnet execution through the deterministic engine.", True),
    Skill("execution.live", "execution", "execute", "guarded_live", True, True,
          "Reserved live-money execution skill. Not implemented/enabled in this project.", True),
)


class SkillRegistry:
    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        disabled = {str(x) for x in config.get("disabled_skills", [])}
        self._skills = {s.name: s for s in _BUILTINS if s.name not in disabled}
        self._disabled = disabled

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def capabilities(self) -> dict[str, Any]:
        return {
            "skills": [asdict(s) | {"registered": True, "runtime_enabled": (not s.live_money)} for s in self.all()],
            "disabled_skills": sorted(self._disabled),
            "design": "single_agent_loop_rich_deterministic_tools",
        }
