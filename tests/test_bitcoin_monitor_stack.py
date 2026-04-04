import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
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


def test_reachability_checker_timeout_30s(tmpl):
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "piReachabilityChecker", "Timeout": 30},
    )


# ── CloudWatch alarms ─────────────────────────────────────────────────────────


def test_two_alarms_created(tmpl):
    tmpl.resource_count_is("AWS::CloudWatch::Alarm", 2)


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


# ── SNS ───────────────────────────────────────────────────────────────────────


def test_sns_topic_name(tmpl):
    tmpl.has_resource_properties(
        "AWS::SNS::Topic",
        {"TopicName": "BitcoinNodeAlerts"},
    )


# ── Outputs ───────────────────────────────────────────────────────────────────


def test_heartbeat_url_output_exists(tmpl):
    outputs = tmpl.find_outputs("HeartbeatReceiverUrl")
    assert outputs
