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

_MAX_AGE = timedelta(seconds=90)
_SECRET = os.environ["HEARTBEAT_SECRET"]
_SIGNATURE_HEADER = "X-Heartbeat-Signature-256"

type Response = dict[str, int | str]


def _parse_body(event: dict) -> tuple[dict, None] | tuple[None, Response]:
    """Returns (body_dict, error_response) — one of which is None."""
    try:
        return json.loads(event.get("body") or "{}"), None
    except json.JSONDecodeError:
        return None, {"statusCode": 400, "body": "invalid json"}


def _verify_signature(event: dict, sent_at_raw: str | None) -> Response | None:
    """Returns error_response or None if the signature is valid.

    Missing sent_at is treated as an auth failure so unauthenticated callers
    cannot probe field names via different error codes.
    """
    if not sent_at_raw:
        return {"statusCode": 401, "body": "unauthorized"}
    headers = event.get("headers") or {}
    token = headers.get(_SIGNATURE_HEADER.lower()) or headers.get(_SIGNATURE_HEADER)
    expected = hmac.new(
        _SECRET.encode(), sent_at_raw.encode(), hashlib.sha256
    ).hexdigest()
    if not token or not hmac.compare_digest(token, expected):
        return {"statusCode": 401, "body": "unauthorized"}
    return None


def _parse_sent_at(sent_at_raw: str) -> tuple[datetime, None] | tuple[None, Response]:
    """Returns (sent_at_datetime, error_response)."""
    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        return sent_at, None
    except ValueError:
        return None, {"statusCode": 400, "body": "invalid sent_at"}


def _check_freshness(sent_at: datetime) -> Response | None:
    """Returns error_response or None if the timestamp is fresh."""
    if abs(datetime.now(UTC) - sent_at) > _MAX_AGE:
        return {"statusCode": 400, "body": "sent_at out of range"}
    return None


def _record_heartbeat(source: str) -> None:
    cloudwatch.put_metric_data(
        Namespace="BitcoinNode",
        MetricData=[
            {
                "MetricName": "HeartbeatReceived",
                "Dimensions": [{"Name": "NodeId", "Value": source}],
                "Value": 1,
                "Unit": "Count",
            }
        ],
    )


def lambda_handler(event: dict, context: object) -> Response:
    body, err = _parse_body(event)
    if err:
        return err

    # Verify auth before any further validation — prevents unauthenticated callers
    # from probing field names via different error codes.
    sent_at_raw = body.get("sent_at")
    err = _verify_signature(event, sent_at_raw)
    if err:
        return err

    sent_at, err = _parse_sent_at(sent_at_raw)
    if err:
        return err

    err = _check_freshness(sent_at)
    if err:
        return err

    source = str(body.get("source") or "unknown")[:256]
    _record_heartbeat(source)
    return {"statusCode": 200, "body": "ok"}
