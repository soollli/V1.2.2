from __future__ import annotations
from dataclasses import dataclass, asdict, fields
from pathlib import Path
import json
import os
import tempfile


@dataclass
class PortfolioState:
    quote_balance: float = 10000.0
    base_qty: float = 0.0
    # Execution-price average, used for simple stop/take-profit logic.
    avg_entry: float = 0.0
    # Fee-inclusive quote cost basis used for accounting/PnL.
    cost_basis_quote: float = 0.0
    realized_pnl: float = 0.0
    last_bar_time: str = ""
    last_price: float = 0.0
    last_signal: str = ""
    last_reason: str = ""
    last_update_utc: str = ""
    reconciliation_required: bool = False
    reconciliation_note: str = ""
    last_account_sync_utc: str = ""

    def to_dict(self):
        return asdict(self)

    def save(self, path: Path):
        """Atomically persist state so a crash cannot leave half-written JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path, initial_quote: float = 10000.0):
        if not path.exists():
            return cls(quote_balance=initial_quote)
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in allowed}
        clean.setdefault("quote_balance", initial_quote)
        # Migration from pre-V1.2.1 state. This cannot reconstruct historical
        # fees exactly, but preserves the existing position conservatively.
        if "cost_basis_quote" not in clean:
            clean["cost_basis_quote"] = float(clean.get("avg_entry", 0.0)) * float(clean.get("base_qty", 0.0))
        return cls(**clean)
