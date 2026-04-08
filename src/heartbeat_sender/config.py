import tomllib
from pathlib import Path

from dotenv import load_dotenv


def _load() -> dict:
    # Resolve paths from CWD so the package works when installed into a venv.
    # The cron job always runs from the project root via `cd $HOME`.
    root = Path.cwd()
    load_dotenv(root / ".env")
    with open(root / "config.toml", "rb") as f:
        return tomllib.load(f)


_config: dict | None = None


def config() -> dict:
    global _config
    if _config is None:
        _config = _load()
    return _config
