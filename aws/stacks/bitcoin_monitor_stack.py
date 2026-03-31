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
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as sns_subscriptions,
)
from constructs import Construct

CHECK_PERIOD = Duration.hours(1)
EVAL_PERIODS = 6  # 6 × 1h = alarm after 6h of continuous failure


class BitcoinMonitorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alert_email = self.node.try_get_context("alert_email")
        if not alert_email:
            raise ValueError(
                "CDK context value 'alert_email' is required. "
                "Pass it with: cdk deploy --context alert_email=<email>"
            )

        heartbeat_secret = self.node.try_get_context("heartbeat_secret")
        if not heartbeat_secret:
            raise ValueError(
                "CDK context value 'heartbeat_secret' is required. "
                "Pass it with: cdk deploy --context heartbeat_secret=<secret>"
            )

        # ── SNS topic → email ─────────────────────────────────────────────────
        alert_topic = sns.Topic(
            self,
            "BitcoinAlerts",
            topic_name="BitcoinNodeAlerts",
        )
        alert_topic.add_subscription(sns_subscriptions.EmailSubscription(alert_email))

        # ── Heartbeat receiver (Pi → Lambda → CloudWatch) ────────────────────

        node_id = self.node.try_get_context("node_id")
        if not node_id:
            raise ValueError(
                "CDK context value 'node_id' is required. "
                "Pass it with: cdk deploy --context node_id=<id>"
            )

        receiver = lambda_.Function(
            self,
            "HeartbeatReceiver",
            function_name="piHeartbeatReceiver",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/heartbeat_receiver"),
            environment={
                "HEARTBEAT_SECRET": heartbeat_secret,
            },
        )
        receiver.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            )
        )

        receiver_url = receiver.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ── Reachability checker (EventBridge → Lambda → CloudWatch) ─────────
        checker = lambda_.Function(
            self,
            "ReachabilityChecker",
            function_name="piReachabilityChecker",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/reachability_checker"),
            timeout=Duration.seconds(25),
            environment={
                "DUCKDNS_HOSTNAME": "you-monkey.duckdns.org",
                "BITCOIN_PORT": "8333",
                "node_id": node_id,
            },
        )
        checker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
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

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(
            self,
            "HeartbeatReceiverUrl",
            value=receiver_url.url,
            description="Paste this URL into config.toml as heartbeat_endpoint",
        )
