from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cloudwatch_actions,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as sns_subscriptions,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct

CHECK_PERIOD = Duration.hours(1)
EVAL_PERIODS = 6  # 6 × 1h = alarm after 6h of continuous failure

_LAMBDAS_DIR = Path(__file__).parent.parent / "lambdas"


def _lambda_code(name: str) -> lambda_.AssetCode:
    return lambda_.Code.from_asset(str(_LAMBDAS_DIR / name))


class BitcoinMonitorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alert_email = self._require_context("alert_email")
        heartbeat_secret = self._require_context("heartbeat_secret")

        # ── SNS topic → email ─────────────────────────────────────────────────
        # A customer-managed key is required so we can grant CloudWatch Alarms
        # the kms:GenerateDataKey* / kms:Decrypt permissions it needs to publish
        # to an encrypted topic. AWS-managed keys don't allow policy additions.
        sns_key = kms.Key(
            self,
            "SnsKey",
            description="Encryption key for Bitcoin Node Alerts SNS topic",
            enable_key_rotation=True,
        )
        sns_key.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("cloudwatch.amazonaws.com")],
                actions=["kms:GenerateDataKey*", "kms:Decrypt"],
                resources=["*"],
                # Confused-deputy guard: only CloudWatch acting on behalf of
                # this account may use the key, not on behalf of other accounts.
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )
        alert_topic = sns.Topic(
            self,
            "BitcoinAlerts",
            topic_name="BitcoinNodeAlerts",
            master_key=sns_key,
        )
        alert_topic.add_subscription(sns_subscriptions.EmailSubscription(alert_email))

        # ── Heartbeat receiver (Pi → Lambda → CloudWatch) ────────────────────

        node_id = self._require_context("node_id")
        ip_provider_hostname = self._require_context("ip_provider_hostname")

        # Note: the secret is stored as a Lambda env var (KMS-encrypted at rest
        # by AWS). For a production deployment, prefer SSM Parameter Store
        # (SecureString) or Secrets Manager to avoid exposure in the console
        # and CloudFormation templates.
        receiver = lambda_.Function(
            self,
            "HeartbeatReceiver",
            function_name="piHeartbeatReceiver",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=_lambda_code("heartbeat_receiver"),
            # The Function URL is unauthenticated (HMAC is checked inside the
            # handler), so cap concurrency: one Pi posting hourly needs almost
            # none, and abuse can't run up cost or starve the account limit.
            reserved_concurrent_executions=5,
            environment={
                "HEARTBEAT_SECRET": heartbeat_secret,
                # The metric dimension the alarm watches — pinned server-side
                # so a misconfigured Pi can't emit under a different NodeId.
                "NODE_ID": node_id,
            },
        )
        receiver.add_to_role_policy(
            iam.PolicyStatement(
                # PutMetricData has no resource-level ARNs, so "*" is required;
                # the namespace condition keeps a compromised Lambda from
                # writing into any other namespace.
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "BitcoinNode"}},
            )
        )

        receiver_url = receiver.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ── Reachability checker (EventBridge → Lambda → CloudWatch) ─────────
        checker_dlq = sqs.Queue(
            self,
            "ReachabilityCheckerDLQ",
            queue_name="piReachabilityCheckerDLQ",
            retention_period=Duration.days(14),
        )
        checker = lambda_.Function(
            self,
            "ReachabilityChecker",
            function_name="piReachabilityChecker",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=_lambda_code("reachability_checker"),
            # 10s TCP connect + 10s verack wait + DNS + overhead → 30s is safe
            timeout=Duration.seconds(30),
            dead_letter_queue=checker_dlq,
            environment={
                "IP_PROVIDER_HOSTNAME": ip_provider_hostname,
                "BITCOIN_PORT": "8333",
                "NODE_ID": node_id,
            },
        )
        checker.add_to_role_policy(
            iam.PolicyStatement(
                # PutMetricData has no resource-level ARNs, so "*" is required;
                # the namespace condition keeps a compromised Lambda from
                # writing into any other namespace.
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "BitcoinNode"}},
            )
        )

        events.Rule(
            self,
            "ReachabilitySchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(checker)],
        )

        # ── CloudWatch alarms ─────────────────────────────────────────────────
        def _make_alarm(
            alarm_id: str,
            alarm_name: str,
            description: str,
            metric_name: str,
            statistic: str,
        ) -> cloudwatch.Alarm:
            metric = cloudwatch.Metric(
                namespace="BitcoinNode",
                metric_name=metric_name,
                dimensions_map={"NodeId": node_id},
                statistic=statistic,
                period=CHECK_PERIOD,
            )
            alarm = cloudwatch.Alarm(
                self,
                alarm_id,
                alarm_name=alarm_name,
                alarm_description=description,
                metric=metric,
                evaluation_periods=EVAL_PERIODS,
                datapoints_to_alarm=EVAL_PERIODS,
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
            )
            alarm.add_alarm_action(cloudwatch_actions.SnsAction(alert_topic))
            alarm.add_ok_action(cloudwatch_actions.SnsAction(alert_topic))
            return alarm

        _make_alarm(
            alarm_id="HeartbeatAlarm",
            alarm_name="BitcoinNode-HeartbeatMissing",
            description=f"No heartbeat from Pi ({node_id}) for 6 hours",
            metric_name="HeartbeatReceived",
            statistic="Sum",
        )

        _make_alarm(
            alarm_id="ReachabilityAlarm",
            alarm_name="BitcoinNode-NotReachable",
            description=f"Bitcoin node ({node_id}) unreachable from internet for 6 hours",
            metric_name="NodeReachable",
            statistic="Maximum",
        )

        # A checker failure already alerts via missing data (breaching), but
        # without this the DLQ fills silently and entries expire after 14 days
        # unseen. One email when retries are exhausted, one when it drains.
        dlq_alarm = cloudwatch.Alarm(
            self,
            "CheckerDlqAlarm",
            alarm_name="BitcoinNode-CheckerDLQ",
            alarm_description="Reachability checker invocations exhausted retries",
            metric=checker_dlq.metric_approximate_number_of_messages_visible(
                period=CHECK_PERIOD,
            ),
            evaluation_periods=1,
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        dlq_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alert_topic))
        dlq_alarm.add_ok_action(cloudwatch_actions.SnsAction(alert_topic))

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(
            self,
            "HeartbeatReceiverUrl",
            value=receiver_url.url,
            description="Paste this URL into config.toml as heartbeat_endpoint",
        )

    def _require_context(self, key: str) -> str:
        value = self.node.try_get_context(key)
        if not value:
            raise ValueError(
                f"CDK context value '{key}' is required. "
                f"Pass it with: cdk deploy --context {key}=<value>"
            )
        return value
