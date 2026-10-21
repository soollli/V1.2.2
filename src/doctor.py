from __future__ import annotations
import json
import os
import sys
import tempfile

from .config import Settings, env_testnet_credentials
from .core.registry import AdapterRegistry
from .monitor import mode_path


def run_doctor(settings: Settings, mode: str = "paper") -> int:
    checks = []

    def add(name: str, ok: bool, detail: str, *, required: bool = True):
        checks.append({"check": name, "ok": bool(ok), "required": bool(required), "detail": detail})

    # Project runtime is intentionally pinned to Python 3.12 because Qlib 0.9.7
    # publishes CPython 3.12 wheels while the user's other local stacks may use 3.13.
    py = sys.version_info
    add("python_runtime", (py.major, py.minor) == (3, 12), f"running={py.major}.{py.minor}.{py.micro}; supported_project_runtime=3.12")

    try:
        symbol = settings.market["symbol"]
        interval = settings.market["interval"]
        add("config", bool(symbol and interval), f"symbol={symbol} interval={interval}")
    except Exception as e:
        add("config", False, str(e))

    try:
        md = AdapterRegistry(settings).data(use_testnet=(mode == "binance_testnet"))
        px = md.price(settings.market["symbol"])
        add("market_api", px > 0, f"price={px}")
    except Exception as e:
        add("market_api", False, f"{type(e).__name__}: {e}")

    try:
        target = mode_path(settings, "state_file", mode).parent
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target, prefix=".writecheck_", delete=True):
            pass
        add("storage_writable", True, str(target))
    except Exception as e:
        add("storage_writable", False, str(e))

    try:
        # Clean-process imports catch package initializer cycles that pytest's
        # module order can otherwise hide.
        from .adapters.research.qlib import QlibResearchAdapter  # noqa: F401
        from .adapters.data.binance import BinanceDataAdapter  # noqa: F401
        add("adapter_imports", True, "clean explicit imports succeeded")
    except Exception as e:
        add("adapter_imports", False, f"{type(e).__name__}: {e}")

    if mode == "binance_testnet":
        if os.getenv("AI_QUANT_AGENT_CONTEXT", "").strip() == "1":
            add("testnet_credentials", True, "credential presence check skipped in agent context; operator-only", required=False)
        else:
            key, secret = env_testnet_credentials(settings.root)
            add("testnet_credentials", bool(key and secret), "present" if key and secret else "missing API key/secret")

    ok = all(x["ok"] for x in checks if x["required"])
    print(json.dumps({"ok": ok, "mode": mode, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 2
