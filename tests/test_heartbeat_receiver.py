import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

_LAMBDA = (
    Path(__file__).parent.parent / "aws/lambdas/heartbeat_receiver/lambda_function.py"
)
spec = importlib.util.spec_from_file_location("heartbeat_receiver", _LAMBDA)
lf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lf)


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_known_source(mock_table, mock_cw):
    event = {"body": json.dumps({"source": "lasvegas"})}
    result = lf.lambda_handler(event, None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "lasvegas"
    assert "timestamp" in item
    assert result == {"statusCode": 200, "body": "ok"}


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_missing_body_defaults_to_unknown(mock_table, mock_cw):
    lf.lambda_handler({}, None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "unknown"


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_empty_json_body_defaults_to_unknown(mock_table, mock_cw):
    lf.lambda_handler({"body": "{}"}, None)
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["source"] == "unknown"


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_malformed_json_returns_400(mock_table, mock_cw):
    result = lf.lambda_handler({"body": "not-json"}, None)
    assert result == {"statusCode": 400, "body": "invalid json"}
    mock_table.put_item.assert_not_called()


@patch.object(lf, "cloudwatch")
@patch.object(lf, "table")
def test_cloudwatch_metric_uses_source_as_node_id(mock_table, mock_cw):
    event = {"body": json.dumps({"source": "lasvegas"})}
    lf.lambda_handler(event, None)
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Dimensions"][0] == {"Name": "NodeId", "Value": "lasvegas"}
    assert metric["Value"] == 1
