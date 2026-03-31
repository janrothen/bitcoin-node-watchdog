#!/usr/bin/env python3

# Sends a heartbeat to AWS every hour so the watchdog knows the Pi is alive.
# Reachability of the Bitcoin node is checked independently by a Lambda on AWS.

import hashlib
import hmac
import os
import sys
import traceback
from datetime import UTC, datetime

import requests

from .config import config

_SIGNATURE_HEADER = "X-Heartbeat-Signature-256"


def check():
    post_heartbeat()


def create_signature(secret: str, sent_at: str) -> str:
    # HMAC-SHA256 over the sent_at timestamp so the secret is never transmitted
    # in plaintext. Binding the signature to the timestamp also makes each
    # heartbeat single-use: a replayed request will be rejected by the receiver's
    # 90-second freshness check.
    return hmac.new(secret.encode(), sent_at.encode(), hashlib.sha256).hexdigest()


def post_heartbeat():
    cfg = config()
    endpoint = cfg["heartbeat"]["receiver"]["endpoint"]
    secret = os.environ["HEARTBEAT_SECRET"]
    sent_at = datetime.now(UTC).isoformat()
    body = {
        "source": os.environ["NODE_ID"],
        "sent_at": sent_at,
    }
    signature = create_signature(secret, sent_at)
    headers = {_SIGNATURE_HEADER: signature}
    try:
        r = requests.post(endpoint, json=body, headers=headers)
        if r.status_code not in (200, 201):
            print(f"Failed to send heartbeat:\nCode: {r.status_code}\nResult: {r.text}")
            return
        print("Heartbeat sent.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send heartbeat: {e}")


def run():
    try:
        check()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    run()
