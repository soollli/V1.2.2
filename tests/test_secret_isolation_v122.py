from __future__ import annotations
from pathlib import Path
import json
import os
import subprocess
import sys

from src.config import env_testnet_credentials, load_settings


def test_load_settings_does_not_import_dotenv_secrets(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project:\n  name: x\nmarket: {}\nstrategy: {}\nrisk: {}\nbroker: {}\nstorage: {}\n", encoding="utf-8")
    (tmp_path / ".env").write_text("BINANCE_TESTNET_API_KEY=abc\nBINANCE_TESTNET_API_SECRET=secret\n", encoding="utf-8")
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    load_settings(str(cfg))
    assert os.getenv("BINANCE_TESTNET_API_KEY") is None
    assert os.getenv("BINANCE_TESTNET_API_SECRET") is None


def test_testnet_credentials_read_only_requested_keys(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "BINANCE_TESTNET_API_KEY=abc\nBINANCE_TESTNET_API_SECRET=secret\nSHOULD_NOT_LOAD=hidden\n",
        encoding="utf-8",
    )
    for k in ["BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET", "SHOULD_NOT_LOAD"]:
        monkeypatch.delenv(k, raising=False)
    assert env_testnet_credentials(tmp_path) == ("abc", "secret")
    assert os.getenv("SHOULD_NOT_LOAD") is None


def test_agent_cli_denies_operator_only_command():
    root = Path(__file__).parents[1]
    p = subprocess.run([sys.executable, str(root / "scripts" / "agent_cli.py"), "testnet"], cwd=root, capture_output=True, text=True)
    assert p.returncode == 13
    assert "DENIED_BY_TOOL_POLICY" in p.stderr


def test_agent_cli_allows_capabilities():
    root = Path(__file__).parents[1]
    p = subprocess.run([sys.executable, str(root / "scripts" / "agent_cli.py"), "capabilities"], cwd=root, capture_output=True, text=True)
    assert p.returncode == 0
    obj = json.loads(p.stdout)
    assert obj["agent_safety"]["gateway"]["broker_secret_access"] is False

def test_agent_context_blocks_direct_operator_command():
    root = Path(__file__).parents[1]
    env = dict(os.environ)
    env["AI_QUANT_AGENT_CONTEXT"] = "1"
    p = subprocess.run([sys.executable, str(root / "run.py"), "human-approve"], cwd=root, env=env, capture_output=True, text=True)
    assert p.returncode != 0
    assert "DENIED_BY_TOOL_POLICY" in (p.stderr + p.stdout)


def test_testnet_execution_adapter_reads_project_env_without_global_loading(tmp_path, monkeypatch):
    import yaml
    from src.config import Settings
    from src.adapters.execution.native import NativeExecutionAdapter
    root = Path(__file__).parents[1]
    raw = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    (tmp_path / ".env").write_text("BINANCE_TESTNET_API_KEY=abc\nBINANCE_TESTNET_API_SECRET=secret\n", encoding="utf-8")
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    adapter = NativeExecutionAdapter(Settings(raw=raw, root=tmp_path), "binance_testnet")
    assert adapter.broker.api_key == "abc"
    assert os.getenv("BINANCE_TESTNET_API_KEY") is None
