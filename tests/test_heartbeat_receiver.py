import hashlib
import hmac
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

_LAMBDA = (
    Path(__file__).parent.parent / "aws/lambdas/heartbeat_receiver/lambda_function.py"
)
spec = importlib.util.spec_from_file_location("heartbeat_receiver", _LAMBDA)
lf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lf)


def _make_headers(sent_at: str, secret: str = "test-secret") -> dict[str, str]:
    token = hmac.new(secret.encode(), sent_at.encode(), hashlib.sha256).hexdigest()
    return {"x-heartbeat-signature-256": token}


def _event(
    source: str = "lasvegas",
    sent_at: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    sent_at_str = sent_at or datetime.now(UTC).isoformat()
    body = {"source": source, "sent_at": sent_at_str}
    return {
        "headers": headers if headers is not None else _make_headers(sent_at_str),
        "body": json.dumps(body),
    }


# ── Happy path ────────────────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_known_source(mock_table, mock_cw):
    result = lf.lambda_handler(_event(), None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "lasvegas"
    assert "timestamp" in item
    assert result == {"statusCode": 200, "body": "ok"}


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_missing_source_defaults_to_unknown(mock_table, mock_cw):
    sent_at = datetime.now(UTC).isoformat()
    event = {
        "headers": _make_headers(sent_at),
        "body": json.dumps({"sent_at": sent_at}),
    }
    lf.lambda_handler(event, None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "unknown"


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_empty_json_body_defaults_to_unknown(mock_table, mock_cw):
    sent_at = datetime.now(UTC).isoformat()
    event = {
        "headers": _make_headers(sent_at),
        "body": json.dumps({"sent_at": sent_at}),
    }
    lf.lambda_handler(event, None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "unknown"


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_malformed_json_returns_400(mock_table, mock_cw):
    event = {"headers": {}, "body": "not-json"}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 400, "body": "invalid json"}
    mock_table.put_item.assert_not_called()


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_cloudwatch_metric_uses_source_as_node_id(mock_table, mock_cw):
    lf.lambda_handler(_event(), None)
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Dimensions"][0] == {"Name": "NodeId", "Value": "lasvegas"}
    assert metric["Value"] == 1


# ── Authentication ────────────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_missing_token_returns_401(mock_table, mock_cw):
    result = lf.lambda_handler(_event(headers={}), None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_table.put_item.assert_not_called()


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_wrong_token_returns_401(mock_table, mock_cw):
    result = lf.lambda_handler(_event(headers={"x-heartbeat-token": "wrong"}), None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_table.put_item.assert_not_called()


# ── Timestamp validation ──────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_missing_sent_at_returns_400(mock_table, mock_cw):
    event = {"headers": {}, "body": json.dumps({"source": "lasvegas"})}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 400, "body": "missing sent_at"}
    mock_table.put_item.assert_not_called()


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_stale_sent_at_returns_400(mock_table, mock_cw):
    stale = (datetime.now(UTC) - timedelta(seconds=91)).isoformat()
    result = lf.lambda_handler(_event(sent_at=stale), None)
    assert result == {"statusCode": 400, "body": "sent_at out of range"}
    mock_table.put_item.assert_not_called()


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_valid_authenticated_request_returns_200(mock_table, mock_cw):
    result = lf.lambda_handler(_event(), None)
    assert result == {"statusCode": 200, "body": "ok"}
    mock_table.put_item.assert_called_once()
