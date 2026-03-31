#!/usr/bin/env python3
"""Smoke-test the live heartbeat receiver endpoint."""

import hashlib
import hmac
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import requests

_SIGNATURE_HEADER = "X-Heartbeat-Signature-256"
_ROOT = Path(__file__).parent.parent


def _create_signature(secret: str, sent_at: str) -> str:
    return hmac.new(secret.encode(), sent_at.encode(), hashlib.sha256).hexdigest()


def _endpoint() -> str:
    with open(_ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)["heartbeat"]["receiver"]["endpoint"]


def main():
    endpoint = _endpoint()
    secret = os.environ["HEARTBEAT_SECRET"]

    # 1. Unauthenticated → expect 401
    r = requests.post(
        endpoint,
        json={"source": "smoke", "sent_at": datetime.now(UTC).isoformat()},
    )
    status = "PASS" if r.status_code == 401 else f"FAIL (got {r.status_code})"
    print(f"[{status}] No auth → {r.status_code}")

    # 2. Valid HMAC signature → expect 200
    sent_at = datetime.now(UTC).isoformat()
    r = requests.post(
        endpoint,
        json={"source": "smoke", "sent_at": sent_at},
        headers={_SIGNATURE_HEADER: _create_signature(secret, sent_at)},
    )
    status = "PASS" if r.status_code == 200 else f"FAIL (got {r.status_code})"
    print(f"[{status}] Valid signature → {r.status_code}")


if __name__ == "__main__":
    main()
