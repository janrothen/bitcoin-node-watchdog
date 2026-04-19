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
_REQUEST_TIMEOUT_SECONDS = 10


class HeartbeatSender:
    def __init__(
        self,
        endpoint: str,
        secret: str,
        node_id: str,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint = endpoint
        self._secret = secret
        self._node_id = node_id
        self._timeout = timeout

    @staticmethod
    def _sign(secret: str, sent_at: str) -> str:
        # HMAC-SHA256 over the sent_at timestamp so the secret is never transmitted
        # in plaintext. Binding the signature to the timestamp also makes each
        # heartbeat single-use: a replayed request will be rejected by the receiver's
        # 90-second freshness check.
        return hmac.new(secret.encode(), sent_at.encode(), hashlib.sha256).hexdigest()

    def send(self) -> bool:
        sent_at = datetime.now(UTC).isoformat()
        body = {"source": self._node_id, "sent_at": sent_at}
        headers = {_SIGNATURE_HEADER: self._sign(self._secret, sent_at)}
        try:
            r = requests.post(
                self._endpoint, json=body, headers=headers, timeout=self._timeout
            )
        except requests.exceptions.RequestException as e:
            print(f"Failed to send heartbeat: {e}")
            return False
        if r.status_code not in (200, 201):
            print(f"Failed to send heartbeat:\nCode: {r.status_code}\nResult: {r.text}")
            return False
        print("Heartbeat sent.")
        return True


def _from_env() -> HeartbeatSender:
    cfg = config()
    return HeartbeatSender(
        endpoint=cfg["heartbeat"]["receiver"]["endpoint"],
        secret=os.environ["HEARTBEAT_SECRET"],
        node_id=os.environ["NODE_ID"],
    )


def run() -> None:
    try:
        if not _from_env().send():
            sys.exit(1)
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    run()
