import tomllib
from pathlib import Path

_CONFIG = None


def config():
    global _CONFIG
    if _CONFIG is None:
        path = Path(__file__).parents[3] / "config.toml"
        with open(path, "rb") as f:
            _CONFIG = tomllib.load(f)
    return _CONFIG
