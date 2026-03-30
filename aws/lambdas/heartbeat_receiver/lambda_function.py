import json
import os
from datetime import UTC, datetime

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
cloudwatch = boto3.client("cloudwatch")


def lambda_handler(event, context):
    body = json.loads(event.get("body") or "{}")
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
