import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
cloudwatch = boto3.client("cloudwatch")

_SECRET = os.environ["HEARTBEAT_SECRET"]
_MAX_AGE = timedelta(seconds=90)


def _parse_body(event):
    """Returns (body_dict, error_response) — one of which is None."""
    try:
        return json.loads(event.get("body") or "{}"), None
    except json.JSONDecodeError:
        return None, {"statusCode": 400, "body": "invalid json"}


def _parse_sent_at(body):
    """Returns (sent_at_raw, sent_at_datetime, error_response)."""
    sent_at_raw = body.get("sent_at")
    if not sent_at_raw:
        return None, None, {"statusCode": 400, "body": "missing sent_at"}
    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        return sent_at_raw, sent_at, None
    except ValueError:
        return None, None, {"statusCode": 400, "body": "invalid sent_at"}


def _verify_signature(event, sent_at_raw):
    """Returns error_response or None if the signature is valid."""
    headers = event.get("headers") or {}
    token = headers.get("x-heartbeat-signature-256") or headers.get(
        "X-Heartbeat-Signature-256"
    )
    expected = hmac.new(
        _SECRET.encode(), sent_at_raw.encode(), hashlib.sha256
    ).hexdigest()
    if not token or not hmac.compare_digest(token, expected):
        return {"statusCode": 401, "body": "unauthorized"}
    return None


def _check_freshness(sent_at):
    """Returns error_response or None if the timestamp is fresh."""
    if abs(datetime.now(UTC) - sent_at) > _MAX_AGE:
        return {"statusCode": 400, "body": "sent_at out of range"}
    return None


def _record_heartbeat(source):
    table.put_item(
        Item={
            "source": source,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
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


def lambda_handler(event, context):
    body, err = _parse_body(event)
    if err:
        return err

    sent_at_raw, sent_at, err = _parse_sent_at(body)
    if err:
        return err

    err = _verify_signature(event, sent_at_raw)
    if err:
        return err

    err = _check_freshness(sent_at)
    if err:
        return err

    _record_heartbeat(body.get("source", "unknown"))
    return {"statusCode": 200, "body": "ok"}
