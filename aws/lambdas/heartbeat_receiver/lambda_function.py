import json
import os
from datetime import UTC, datetime

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def lambda_handler(event, context):
    body = json.loads(event.get("body") or "{}")
    source = body.get("source", "unknown")
    table.put_item(
        Item={
            "source": source,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    return {"statusCode": 200, "body": "ok"}
