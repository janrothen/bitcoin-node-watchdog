import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from stacks.bitcoin_monitor_stack import BitcoinMonitorStack

_REQUIRED_CONTEXT = {
    "alert_email": "test@example.com",
    "heartbeat_secret": "test-secret-value",
    "node_id": "test-node",
    "ip_provider_hostname": "test.duckdns.org",
}


def _stack(**overrides) -> BitcoinMonitorStack:
    ctx = {**_REQUIRED_CONTEXT, **overrides}
    app = cdk.App(context=ctx)
    return BitcoinMonitorStack(app, "TestStack")


@pytest.fixture(scope="module")
def tmpl() -> Template:
    return Template.from_stack(_stack())


# ── Context validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "missing_key",
    ["alert_email", "heartbeat_secret", "node_id", "ip_provider_hostname"],
)
def test_missing_context_raises(missing_key):
    ctx = {k: v for k, v in _REQUIRED_CONTEXT.items() if k != missing_key}
    app = cdk.App(context=ctx)
    with pytest.raises(ValueError, match=missing_key):
        BitcoinMonitorStack(app, "TestStack")


# ── Lambda functions ──────────────────────────────────────────────────────────


def test_heartbeat_receiver_exists(tmpl):
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "piHeartbeatReceiver"},
    )


def test_heartbeat_receiver_pins_node_id(tmpl):
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "piHeartbeatReceiver",
            "Environment": {
                "Variables": Match.object_like({"NODE_ID": "test-node"}),
            },
        },
    )


def test_heartbeat_receiver_concurrency_capped(tmpl):
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "piHeartbeatReceiver",
            "ReservedConcurrentExecutions": 5,
        },
    )


def test_reachability_checker_timeout_30s(tmpl):
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "piReachabilityChecker", "Timeout": 30},
    )


# ── IAM ───────────────────────────────────────────────────────────────────────


def test_put_metric_data_scoped_to_namespace(tmpl):
    policies = tmpl.find_resources("AWS::IAM::Policy")
    statements = [
        stmt
        for policy in policies.values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
        if stmt["Action"] == "cloudwatch:PutMetricData"
    ]
    assert len(statements) == 2  # receiver + checker
    for stmt in statements:
        assert stmt["Condition"] == {
            "StringEquals": {"cloudwatch:namespace": "BitcoinNode"}
        }


# ── KMS ───────────────────────────────────────────────────────────────────────


def test_kms_cloudwatch_grant_has_source_account_condition(tmpl):
    keys = tmpl.find_resources("AWS::KMS::Key")
    assert len(keys) == 1
    statements = next(iter(keys.values()))["Properties"]["KeyPolicy"]["Statement"]
    cloudwatch_stmts = [
        stmt
        for stmt in statements
        if stmt.get("Principal") == {"Service": "cloudwatch.amazonaws.com"}
    ]
    assert len(cloudwatch_stmts) == 1
    condition = cloudwatch_stmts[0]["Condition"]["StringEquals"]
    assert "aws:SourceAccount" in condition


# ── CloudWatch alarms ─────────────────────────────────────────────────────────


def test_three_alarms_created(tmpl):
    tmpl.resource_count_is("AWS::CloudWatch::Alarm", 3)


def test_alarms_evaluate_6_consecutive_periods(tmpl):
    tmpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"EvaluationPeriods": 6, "DatapointsToAlarm": 6},
    )


def test_alarms_treat_missing_data_as_breaching(tmpl):
    tmpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"TreatMissingData": "breaching"},
    )


def test_dlq_alarm_fires_on_any_message(tmpl):
    tmpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "AlarmName": "BitcoinNode-CheckerDLQ",
            "MetricName": "ApproximateNumberOfMessagesVisible",
            "Threshold": 0,
            "ComparisonOperator": "GreaterThanThreshold",
            "TreatMissingData": "notBreaching",
        },
    )


# ── SNS ───────────────────────────────────────────────────────────────────────


def test_sns_topic_name(tmpl):
    tmpl.has_resource_properties(
        "AWS::SNS::Topic",
        {"TopicName": "BitcoinNodeAlerts"},
    )


def test_sns_topic_encrypted(tmpl):
    tmpl.has_resource_properties(
        "AWS::SNS::Topic",
        {"KmsMasterKeyId": Match.any_value()},
    )


# ── Outputs ───────────────────────────────────────────────────────────────────


def test_heartbeat_url_output_exists(tmpl):
    outputs = tmpl.find_outputs("HeartbeatReceiverUrl")
    assert outputs
