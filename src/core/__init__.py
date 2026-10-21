"""Core contracts and schemas.

Keep this package initializer deliberately light. AdapterRegistry imports concrete
adapters, while concrete adapters import core contracts; eagerly importing the
registry here creates an order-dependent circular import.
"""
from .contracts import (
    AdapterInfo,
    ExecutionAdapter,
    MarketDataProvider,
    MLResearchEngine,
    ResearchDataProvider,
    ResearchEngine,
)

__all__ = [
    "AdapterInfo",
    "MarketDataProvider",
    "ExecutionAdapter",
    "ResearchEngine",
    "ResearchDataProvider",
    "MLResearchEngine",
]
