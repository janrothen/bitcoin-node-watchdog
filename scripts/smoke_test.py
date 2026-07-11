#!/usr/bin/env python3
"""Smoke-test the live heartbeat receiver endpoint."""

import hashlib
import hmac
import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import requests

_SIGNATURE_HEADER = "X-Heartbeat-Signature-256"
_REQUEST_TIMEOUT_SECONDS = 10
_ROOT = Path(__file__).parent.parent


def _create_signature(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _endpoint() -> str:
    with open(_ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)["heartbeat"]["receiver"]["endpoint"]


def main():
    endpoint = _endpoint()
    secret = os.environ["HEARTBEAT_SECRET"]
    # Must match the deployed stack's node_id — the receiver rejects other sources.
    node_id = os.environ["NODE_ID"]

    # 1. Unauthenticated → expect 401
    r = requests.post(
        endpoint,
        json={"source": node_id, "sent_at": datetime.now(UTC).isoformat()},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    status = "PASS" if r.status_code == 401 else f"FAIL (got {r.status_code})"
    print(f"[{status}] No auth → {r.status_code}")

    # 2. Valid HMAC signature → expect 200
    sent_at = datetime.now(UTC).isoformat()
    payload = json.dumps({"source": node_id, "sent_at": sent_at})
    r = requests.post(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            _SIGNATURE_HEADER: _create_signature(secret, payload),
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    status = "PASS" if r.status_code == 200 else f"FAIL (got {r.status_code})"
    print(f"[{status}] Valid signature → {r.status_code}")


if __name__ == "__main__":
    main()
