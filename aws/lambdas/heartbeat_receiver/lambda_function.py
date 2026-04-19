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


def _parse_body(event: dict) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        raise _ValidationError({"statusCode": 400, "body": "invalid json"}) from None


def _verify_signature(event: dict, sent_at_raw: object) -> None:
    # A missing or non-string sent_at is treated as an auth failure so
    # unauthenticated callers cannot probe field names or types via different
    # error codes.
    unauthorized = _ValidationError({"statusCode": 401, "body": "unauthorized"})
    if not isinstance(sent_at_raw, str) or not sent_at_raw:
        raise unauthorized
    headers = event.get("headers") or {}
    token = headers.get(_SIGNATURE_HEADER.lower()) or headers.get(_SIGNATURE_HEADER)
    expected = hmac.new(
        _SECRET.encode(), sent_at_raw.encode(), hashlib.sha256
    ).hexdigest()
    if not token or not hmac.compare_digest(token, expected):
        raise unauthorized


def _parse_sent_at(sent_at_raw: str) -> datetime:
    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
    except ValueError:
        raise _ValidationError({"statusCode": 400, "body": "invalid sent_at"}) from None
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
        body = _parse_body(event)
        # Verify auth before any further validation — prevents unauthenticated
        # callers from probing field names via different error codes.
        sent_at_raw = body.get("sent_at")
        _verify_signature(event, sent_at_raw)
        sent_at = _parse_sent_at(sent_at_raw)
        _check_freshness(sent_at)
    except _ValidationError as e:
        return e.response

    _record_heartbeat(_extract_source(body))
    return {"statusCode": 200, "body": "ok"}
