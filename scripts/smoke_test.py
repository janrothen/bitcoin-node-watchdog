#!/usr/bin/env python3
"""Smoke-test the live heartbeat receiver endpoint."""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from heartbeat_sender.__main__ import _SIGNATURE_HEADER, create_signature
from heartbeat_sender.config import config


def main():
    cfg = config()
    endpoint = cfg["heartbeat"]["receiver"]["endpoint"]
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
    signature = create_signature(secret, sent_at)
    r = requests.post(
        endpoint,
        json={"source": "smoke", "sent_at": sent_at},
        headers={_SIGNATURE_HEADER: signature},
    )
    status = "PASS" if r.status_code == 200 else f"FAIL (got {r.status_code})"
    print(f"[{status}] Valid signature → {r.status_code}")


if __name__ == "__main__":
    main()
