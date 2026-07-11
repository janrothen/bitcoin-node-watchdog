import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

import boto3
from botocore.config import Config

cloudwatch = boto3.client(
    "cloudwatch", config=Config(connect_timeout=5, read_timeout=10)
)

_NAMESPACE = "BitcoinNode"
_MAX_AGE = timedelta(seconds=90)
_SECRET = os.environ["HEARTBEAT_SECRET"]
_SIGNATURE_HEADER = "X-Heartbeat-Signature-256"

type Response = dict[str, int | str]


class _ValidationError(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


def _raw_body(event: dict) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body)
        except (ValueError, TypeError):
            raise _ValidationError(
                {"statusCode": 400, "body": "invalid body"}
            ) from None
    return body.encode()


def _parse_body(raw_body: bytes) -> dict:
    invalid = _ValidationError({"statusCode": 400, "body": "invalid json"})
    try:
        body = json.loads(raw_body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise invalid from None
    if not isinstance(body, dict):
        raise invalid
    return body


def _verify_signature(event: dict, raw_body: bytes) -> None:
    # The HMAC covers the raw body bytes as received, so every field (source,
    # sent_at) is authenticated and verification happens before any parsing —
    # unauthenticated callers get a uniform 401 and can probe nothing.
    headers = event.get("headers") or {}
    token = headers.get(_SIGNATURE_HEADER.lower()) or headers.get(_SIGNATURE_HEADER)
    expected = hmac.new(_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(token, expected):
        raise _ValidationError({"statusCode": 401, "body": "unauthorized"})


def _parse_sent_at(sent_at_raw: object) -> datetime:
    invalid = _ValidationError({"statusCode": 400, "body": "invalid sent_at"})
    if not isinstance(sent_at_raw, str):
        raise invalid
    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
    except ValueError:
        raise invalid from None
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return sent_at


def _check_freshness(sent_at: datetime) -> None:
    if abs(datetime.now(UTC) - sent_at) > _MAX_AGE:
        raise _ValidationError({"statusCode": 400, "body": "sent_at out of range"})


def _emit_metric(metric_name: str, value: float, node_id: str) -> None:
    cloudwatch.put_metric_data(
        Namespace=_NAMESPACE,
        MetricData=[
            {
                "MetricName": metric_name,
                "Dimensions": [{"Name": "NodeId", "Value": node_id}],
                "Value": value,
                "Unit": "Count",
            }
        ],
    )


def _record_heartbeat(source: str) -> None:
    _emit_metric("HeartbeatReceived", 1.0, source)


def _extract_source(body: dict) -> str:
    source = body.get("source")
    if not isinstance(source, str) or not source:
        return "unknown"
    return source[:256]


def lambda_handler(event: dict, _context: object) -> Response:
    try:
        raw_body = _raw_body(event)
        # Verify auth before any parsing — prevents unauthenticated callers
        # from probing body structure or field names via different error codes.
        _verify_signature(event, raw_body)
        body = _parse_body(raw_body)
        sent_at = _parse_sent_at(body.get("sent_at"))
        _check_freshness(sent_at)
    except _ValidationError as e:
        return e.response

    _record_heartbeat(_extract_source(body))
    return {"statusCode": 200, "body": "ok"}
