import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
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
from constructs import Construct


class BitcoinMonitorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "PiHeartbeats",
            table_name="PiHeartbeats",
            partition_key=dynamodb.Attribute(
                name="source",
                type=dynamodb.AttributeType.STRING,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        receiver = lambda_.Function(
            self,
            "HeartbeatReceiver",
            function_name="piHeartbeatReceiver",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/heartbeat_receiver"),
            environment={"TABLE_NAME": table.table_name},
        )
        table.grant_write_data(receiver)

        receiver_url = receiver.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        watchdog = lambda_.Function(
            self,
            "HeartbeatWatchdog",
            function_name="piHeartbeatWatchdog",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambdas/heartbeat_watchdog"),
            timeout=Duration.seconds(30),
            environment={
                "TABLE_NAME": table.table_name,
                "ALERT_TO": "jan.rothen@gmail.com",
                "ALERT_FROM": "home.lasvegas.fullnode@gmail.com",
                "THRESHOLD_MINUTES": "15",
            },
        )
        table.grant_read_data(watchdog)
        watchdog.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail"],
                resources=["*"],
            )
        )

        events.Rule(
            self,
            "WatchdogSchedule",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            targets=[targets.LambdaFunction(watchdog)],
        )

        CfnOutput(
            self,
            "HeartbeatReceiverUrl",
            value=receiver_url.url,
            description="Paste this URL into config.toml as heartbeat_endpoint",
        )
