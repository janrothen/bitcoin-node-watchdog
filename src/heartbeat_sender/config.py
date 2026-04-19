import tomllib
from functools import cache
from pathlib import Path


@cache
def config() -> dict:
    # Resolve from CWD so the package works when installed into a venv.
    # The cron job always runs from the project root via `cd $HOME`.
    with open(Path.cwd() / "config.toml", "rb") as f:
        return tomllib.load(f)
