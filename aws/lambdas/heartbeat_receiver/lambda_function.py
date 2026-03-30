import json
import os
from datetime import UTC, datetime, timedelta

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
cloudwatch = boto3.client("cloudwatch")

_SECRET = os.environ["HEARTBEAT_SECRET"]
_MAX_AGE = timedelta(seconds=90)


def lambda_handler(event, context):
    # 1. Token check
    headers = event.get("headers") or {}
    token = headers.get("x-heartbeat-token") or headers.get("X-Heartbeat-Token")
    if token != _SECRET:
        return {"statusCode": 401, "body": "unauthorized"}

    # 2. Body parsing
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "invalid json"}

    # 3. Timestamp check
    sent_at_raw = body.get("sent_at")
    if not sent_at_raw:
        return {"statusCode": 400, "body": "missing sent_at"}
    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
    except ValueError:
        return {"statusCode": 400, "body": "invalid sent_at"}
    if abs(datetime.now(UTC) - sent_at) > _MAX_AGE:
        return {"statusCode": 400, "body": "sent_at out of range"}

    # 4. Happy path
    source = body.get("source", "unknown")
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
    return {"statusCode": 200, "body": "ok"}
