import aws_cdk as cdk
from stacks.bitcoin_monitor_stack import BitcoinMonitorStack

app = cdk.App()
BitcoinMonitorStack(
    app, "BitcoinMonitorStack", env=cdk.Environment(region="eu-central-1")
)
app.synth()
