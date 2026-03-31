import tomllib
from pathlib import Path

from dotenv import load_dotenv

# src/heartbeat_sender/config.py → project root is three levels up
_PROJECT_ROOT = Path(__file__).parent.parent.parent

load_dotenv(_PROJECT_ROOT / ".env")


def _load() -> dict:
    with open(_PROJECT_ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


_config: dict | None = None


def config() -> dict:
    global _config
    if _config is None:
        _config = _load()
    return _config


def project_root() -> Path:
    return _PROJECT_ROOT
