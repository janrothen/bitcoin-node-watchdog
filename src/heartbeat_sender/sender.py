import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime

import requests

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
    def _sign(secret: str, payload: str) -> str:
        # HMAC-SHA256 over the raw request body so the secret is never transmitted
        # in plaintext and every field (source and sent_at) is authenticated —
        # a captured request cannot be replayed with a modified source. The body
        # contains sent_at, so each heartbeat is still single-use: a replay is
        # rejected by the receiver's 90-second freshness check.
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def send(self) -> bool:
        sent_at = datetime.now(UTC).isoformat()
        # Serialize once and sign those exact bytes — the receiver verifies the
        # HMAC over the body as received, so payload and signature must match.
        payload = json.dumps({"source": self._node_id, "sent_at": sent_at})
        headers = {
            "Content-Type": "application/json",
            _SIGNATURE_HEADER: self._sign(self._secret, payload),
        }
        try:
            r = requests.post(
                self._endpoint, data=payload, headers=headers, timeout=self._timeout
            )
        except requests.exceptions.RequestException as e:
            print(f"Failed to send heartbeat: {e}", file=sys.stderr)
            return False
        if r.status_code not in (200, 201):
            print(
                f"Failed to send heartbeat:\nCode: {r.status_code}\nResult: {r.text}",
                file=sys.stderr,
            )
            return False
        print("Heartbeat sent.")
        return True
