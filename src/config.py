from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import os
import yaml
from dotenv import dotenv_values


@dataclass
class Settings:
    raw: Dict[str, Any]
    root: Path

    @property
    def market(self):
        return self.raw["market"]

    @property
    def strategy(self):
        return self.raw["strategy"]

    @property
    def risk(self):
        return self.raw["risk"]

    @property
    def broker(self):
        return self.raw["broker"]

    @property
    def storage(self):
        return self.raw["storage"]


def load_settings(config_path: str = "config.yaml") -> Settings:
    # Deliberately do NOT load .env here. Research/agent processes should not
    # inherit exchange secrets merely by reading configuration.
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings(raw=raw, root=path.parent)


def env_value(name: str, root: Path | None = None) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = (root or Path.cwd()) / ".env"
    if env_path.exists():
        try:
            return str(dotenv_values(env_path).get(name) or "").strip()
        except Exception:
            return ""
    return ""


def env_testnet_credentials(root: Path | None = None):
    # Read only the two exchange keys; do not import every .env variable into
    # the process environment.
    key = env_value("BINANCE_TESTNET_API_KEY", root)
    secret = env_value("BINANCE_TESTNET_API_SECRET", root)
    return key, secret
