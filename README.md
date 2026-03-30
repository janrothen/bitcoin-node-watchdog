# bitcoin-node-watchdog

![Python](https://img.shields.io/badge/python-3.13-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-red)
![AWS CDK](https://img.shields.io/badge/infra-AWS%20CDK-orange)
[![Deploy AWS](https://github.com/janrothen/bitcoin-node-watchdog/actions/workflows/deploy-aws.yml/badge.svg)](https://github.com/janrothen/bitcoin-node-watchdog/actions/workflows/deploy-aws.yml)
![License](https://img.shields.io/badge/license-MIT-green)

Monitors a Bitcoin full node running on a Raspberry Pi. A Python package on the Pi sends an hourly heartbeat to AWS. A Lambda on AWS independently checks whether the node is reachable from the internet every hour by performing a real Bitcoin P2P handshake (resolving the current IP via DuckDNS, then exchanging `version`/`verack` messages on port 8333). CloudWatch Alarms watch both signals and send a single email via SNS when either has been missing for 6 hours — and another when it recovers.

## Requirements

**Hardware**
- Raspberry Pi 4, 8 GB RAM
- Bitcoin full node reachable on port 8333 from the internet
- Dynamic DNS via [DuckDNS](https://www.duckdns.org) keeping your public IP up to date

**Software**
- OS: Debian GNU/Linux 13 (trixie), aarch64
- Python 3.13
- AWS account with CDK bootstrap completed in `eu-north-1`

**External dependencies**
- [DuckDNS](https://www.duckdns.org) — provides a stable hostname for your dynamic IP
- AWS Lambda, DynamoDB, CloudWatch, SNS, EventBridge (all managed by the CDK stack)

## Architecture

```mermaid
sequenceDiagram
    participant Pi as Raspberry Pi
    participant Recv as piHeartbeatReceiver (Lambda)
    participant DB as DynamoDB
    participant CW as CloudWatch
    participant Check as piReachabilityChecker (Lambda)
    participant Duck as DuckDNS (DNS)
    participant Node as Bitcoin Node :8333
    participant SNS as SNS → Email

    loop Every hour (cron)
        Pi->>Recv: POST /heartbeat {source: lasvegas}
        Recv->>DB: put_item {source, timestamp}
        Recv->>CW: PutMetricData HeartbeatReceived=1
    end

    loop Every hour (EventBridge)
        Check->>Duck: DNS lookup you-monkey.duckdns.org
        Duck-->>Check: current IP
        Check->>Node: TCP connect + Bitcoin version message
        Node-->>Check: verack
        Check->>CW: PutMetricData NodeReachable=1 (or 0)
    end

    CW->>SNS: ALARM after 6h of missing/failed data
    CW->>SNS: OK when signal recovers
```

## Configuration

The Pi reads `config.toml` at runtime. There are no secrets in this file — it only contains URLs.

```toml
[bitcoin.reachability]
heartbeat_endpoint = "https://<id>.lambda-url.eu-north-1.on.aws/"
```

`heartbeat_endpoint` comes from the `HeartbeatReceiverUrl` CloudFormation stack output after deploying. All other settings (DuckDNS hostname, Bitcoin port, alarm thresholds, alert email) live in the CDK stack (`aws/stacks/bitcoin_monitor_stack.py`).

## Install & run

```bash
cd ~/bitcoin-node-watchdog
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run once manually:
```bash
python -m bitcoin_reachability
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The Pi package has no dependency on AWS at runtime beyond the heartbeat HTTP POST — you can test it locally by pointing `heartbeat_endpoint` at any HTTP listener (e.g. `python -m http.server`).

The Lambda functions use only Python standard library + `boto3` (built into the Lambda runtime), so they can be unit-tested without deployment.

## Deployment

### Pi — cron job

Add to crontab (`crontab -e`) to send a heartbeat every hour:
```
0 * * * * /home/pi/bitcoin-node-watchdog/.venv/bin/python -m bitcoin_reachability
```

### AWS — one-time setup

**1. Bootstrap CDK** (once per account/region):
```bash
cd aws
pip install -r requirements.txt
npm install -g aws-cdk
cdk bootstrap aws://YOUR_ACCOUNT_ID/eu-north-1
```

**2. Configure GitHub OIDC** so GitHub Actions can deploy without stored credentials:
- AWS Console → IAM → Identity Providers → Add provider
  - Type: OpenID Connect
  - URL: `https://token.actions.githubusercontent.com`
  - Audience: `sts.amazonaws.com`
- Create IAM Role `GitHubActionsDeployRole` with trust policy:
  ```json
  {
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:janrothen/bitcoin-node-watchdog:ref:refs/heads/main"
      }
    }
  }
  ```
- Attach permissions: `AWSCloudFormationFullAccess`, `AWSLambda_FullAccess`, `AmazonDynamoDBFullAccess`, `AmazonSNSFullAccess`, `CloudWatchFullAccess`, `AmazonEventBridgeFullAccess`, `IAMFullAccess`

**3. Add GitHub secret:**
- Repo Settings → Secrets and variables → Actions → New secret
- Name: `AWS_ACCOUNT_ID`, value: your 12-digit AWS account ID

**4. Deploy:**

Push any change under `aws/` to `main` — GitHub Actions runs `cdk deploy` automatically.

Or deploy manually:
```bash
cd aws
cdk deploy
```

**5. Confirm SNS email subscription:**

After the first deploy, AWS sends a confirmation email to `jan.rothen@gmail.com`. Click the confirmation link — no alerts will be delivered until this is done.

**6. Update `config.toml`** on the Pi with the `HeartbeatReceiverUrl` from the CloudFormation stack outputs.

### AWS resources created

All resources live in the `BitcoinMonitorStack` CloudFormation stack (visible in AWS Console → CloudFormation → eu-north-1):

| Resource | Purpose |
|---|---|
| `piHeartbeatReceiver` Lambda | Receives POST from Pi, writes to DynamoDB, emits CloudWatch metric |
| `piReachabilityChecker` Lambda | Hourly Bitcoin P2P handshake check via DuckDNS, emits CloudWatch metric |
| `PiHeartbeats` DynamoDB table | Raw heartbeat storage (retained on stack deletion) |
| `BitcoinNodeAlerts` SNS topic | Delivers alarm and recovery emails |
| `BitcoinNode-HeartbeatMissing` CloudWatch alarm | Fires after 6h of missing heartbeats |
| `BitcoinNode-NotReachable` CloudWatch alarm | Fires after 6h of failed reachability checks |
| EventBridge rule | Triggers reachability checker every hour |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No alert email ever arrives | SNS subscription not confirmed — check inbox for the confirmation link |
| Alert fires but node is actually fine | bitnodes handshake timing out due to slow node startup; wait for full sync |
| `cdk deploy` fails with auth error | OIDC role misconfigured or `AWS_ACCOUNT_ID` secret wrong — re-check IAM trust policy |
| `python -m bitcoin_reachability` exits silently | `heartbeat_endpoint` in `config.toml` not set — update with CloudFormation output URL |
| Cron job not running | Wrong Python path — use absolute path: `/home/pi/bitcoin-node-watchdog/.venv/bin/python` |
| CloudWatch alarms stuck in INSUFFICIENT_DATA | No data yet — wait up to 1h for the first Lambda invocations |
| Alarm fires every hour instead of once | OK action not set on alarm — redeploy the CDK stack |
| DuckDNS lookup returns stale IP | DDNS update cron (`ddns-update-monkey`) not running on Pi — check that cron job |

## Security

- `config.toml` contains no secrets — it is safe to commit
- The heartbeat Lambda URL has no authentication; rate limiting is handled by AWS
- Never commit AWS credentials — the deployment uses OIDC (no stored keys)
- The `AWS_ACCOUNT_ID` GitHub secret is a 12-digit number, not a credential, but keep it private

## Contributing

Found a bug or have an idea? Open an issue or send a PR. Run `pytest` before submitting and keep changes focused.

## License

MIT © Jan Rothen — see [LICENSE](LICENSE) for details.
