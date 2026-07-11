import hashlib
import hmac
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

_LAMBDA = (
    Path(__file__).parent.parent / "aws/lambdas/heartbeat_receiver/lambda_function.py"
)
spec = importlib.util.spec_from_file_location("heartbeat_receiver", _LAMBDA)
lf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lf)


def _make_headers(payload: str, secret: str = "test-secret") -> dict[str, str]:
    token = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {"x-heartbeat-signature-256": token}


def _event(
    source: str = "lasvegas",
    sent_at: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    sent_at_str = sent_at or datetime.now(UTC).isoformat()
    payload = json.dumps({"source": source, "sent_at": sent_at_str})
    return {
        "headers": headers if headers is not None else _make_headers(payload),
        "body": payload,
    }


def _signed_event(body: dict) -> dict:
    payload = json.dumps(body)
    return {"headers": _make_headers(payload), "body": payload}


# ── Happy path ────────────────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
def test_known_source(mock_cw):
    result = lf.lambda_handler(_event(), None)
    assert result == {"statusCode": 200, "body": "ok"}


@patch.object(lf, "cloudwatch")
def test_missing_source_defaults_to_unknown(mock_cw):
    sent_at = datetime.now(UTC).isoformat()
    event = _signed_event({"sent_at": sent_at})
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 200, "body": "ok"}


@patch.object(lf, "cloudwatch")
def test_malformed_json_returns_400(mock_cw):
    # Signed so the request passes auth; the parse failure is what's under test.
    event = {"headers": _make_headers("not-json"), "body": "not-json"}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 400, "body": "invalid json"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_unsigned_malformed_json_returns_401(mock_cw):
    # Auth runs before parsing: unauthenticated callers get a uniform 401
    # and learn nothing about how the body is validated.
    event = {"headers": {}, "body": "not-json"}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
@pytest.mark.parametrize("body", ["[]", '"x"', "42", "null", "true"])
def test_non_object_json_returns_400(mock_cw, body):
    # Valid JSON that is not an object must be rejected, not crash the handler.
    event = {"headers": _make_headers(body), "body": body}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 400, "body": "invalid json"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_cloudwatch_metric_uses_source_as_node_id(mock_cw):
    lf.lambda_handler(_event(), None)
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Dimensions"][0] == {"Name": "NodeId", "Value": "lasvegas"}
    assert metric["Value"] == 1


# ── Authentication ────────────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
def test_missing_token_returns_401(mock_cw):
    result = lf.lambda_handler(_event(headers={}), None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_wrong_token_returns_401(mock_cw):
    result = lf.lambda_handler(_event(headers={"x-heartbeat-token": "wrong"}), None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_cw.put_metric_data.assert_not_called()


# ── Timestamp validation ──────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
def test_unsigned_missing_sent_at_returns_401(mock_cw):
    # Without a valid signature the caller gets 401 regardless of body shape.
    event = {"headers": {}, "body": json.dumps({"source": "lasvegas"})}
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 401, "body": "unauthorized"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_signed_missing_sent_at_returns_400(mock_cw):
    result = lf.lambda_handler(_signed_event({"source": "lasvegas"}), None)
    assert result == {"statusCode": 400, "body": "invalid sent_at"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_stale_sent_at_returns_400(mock_cw):
    stale = (datetime.now(UTC) - timedelta(seconds=91)).isoformat()
    result = lf.lambda_handler(_event(sent_at=stale), None)
    assert result == {"statusCode": 400, "body": "sent_at out of range"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_valid_authenticated_request_returns_200(mock_cw):
    result = lf.lambda_handler(_event(), None)
    assert result == {"statusCode": 200, "body": "ok"}
    mock_cw.put_metric_data.assert_called_once()


# ── Malformed field types ─────────────────────────────────────────────────────


@patch.object(lf, "cloudwatch")
def test_non_string_sent_at_returns_400(mock_cw):
    # A JSON bool/number in sent_at must not crash the handler.
    result = lf.lambda_handler(_signed_event({"source": "x", "sent_at": True}), None)
    assert result == {"statusCode": 400, "body": "invalid sent_at"}
    mock_cw.put_metric_data.assert_not_called()


@patch.object(lf, "cloudwatch")
def test_non_string_source_recorded_as_unknown(mock_cw):
    sent_at = datetime.now(UTC).isoformat()
    event = _signed_event({"source": 0, "sent_at": sent_at})
    result = lf.lambda_handler(event, None)
    assert result == {"statusCode": 200, "body": "ok"}
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Dimensions"][0] == {"Name": "NodeId", "Value": "unknown"}
