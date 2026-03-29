# bitcoin-node-watchdog

![Python](https://img.shields.io/badge/python-3.13-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-red)
![AWS CDK](https://img.shields.io/badge/infra-AWS%20CDK-orange)
[![Deploy AWS](https://github.com/janrothen/bitcoin-node-watchdog/actions/workflows/deploy-aws.yml/badge.svg)](https://github.com/janrothen/bitcoin-node-watchdog/actions/workflows/deploy-aws.yml)
![License](https://img.shields.io/badge/license-MIT-green)

Monitors a Bitcoin full node on Raspberry Pi. Checks external reachability via [bitnodes.io](https://bitnodes.io) and posts a heartbeat to AWS. A watchdog Lambda alerts via email when heartbeats stop — catching Pi crashes, network outages, and node failures.

## Pi setup

**Install the package:**
```bash
cd ~/bitcoin-node-watchdog
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Configure** `config.toml` — set `heartbeat_endpoint` to the URL from the CloudFormation stack output (see AWS setup below):
```toml
[bitcoin.reachability]
service_endpoint   = "https://bitnodes.io/api/v1/nodes/me-8333/"
heartbeat_endpoint = "https://<id>.lambda-url.eu-central-1.on.aws/"
```

**Run manually:**
```bash
python -m bitcoin_reachability
```

**Run on a schedule** — add to crontab (`crontab -e`):
```
*/5 * * * * /home/pi/bitcoin-node-watchdog/.venv/bin/python -m bitcoin_reachability
```

## AWS setup (one-time)

**1. Bootstrap CDK** (once per account/region):
```bash
cd aws
pip install -r requirements.txt
npm install -g aws-cdk
cdk bootstrap aws://ACCOUNT_ID/eu-central-1
```

**2. Configure GitHub OIDC** so GitHub Actions can assume an AWS role without stored credentials:
- AWS Console → IAM → Identity Providers → Add provider
  - Type: OpenID Connect
  - URL: `https://token.actions.githubusercontent.com`
  - Audience: `sts.amazonaws.com`
- Create IAM Role `GitHubActionsDeployRole` with this trust policy:
  ```json
  {
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:janrothen/bitcoin-node-watchdog:ref:refs/heads/main"
      }
    }
  }
  ```
- Attach permissions for CloudFormation, Lambda, DynamoDB, SES, IAM, and EventBridge

**3. Verify SES sender** in eu-central-1:
- AWS Console → SES → Verified identities → Verify `home.lasvegas.fullnode@gmail.com`

**4. Add GitHub secret:**
- Repo Settings → Secrets and variables → Actions → New secret
- Name: `AWS_ACCOUNT_ID`, value: your 12-digit AWS account ID

**5. Deploy:**

Push any change to `aws/**` on `main` — GitHub Actions will run `cdk deploy` automatically.

Or deploy manually:
```bash
cd aws
cdk deploy
```

**6. Update `config.toml`** with the `HeartbeatReceiverUrl` from the CloudFormation stack outputs.

## Dev/test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| No heartbeat received, node appears reachable | `heartbeat_endpoint` in `config.toml` is wrong or empty | Update with `HeartbeatReceiverUrl` from CloudFormation outputs |
| Alert email never arrives | SES sender address not verified | Verify the sender in AWS SES → Verified identities |
| `cdk deploy` fails with auth error | GitHub OIDC role or `AWS_ACCOUNT_ID` secret misconfigured | Re-check IAM trust policy and secret value |
| `python -m bitcoin_reachability` exits with HTTP error | bitnodes.io `service_endpoint` unreachable or node not yet synced | Confirm the node is fully synced and port 8333 is open |
| Cron job not running | Wrong Python path in crontab | Use absolute path: `/home/pi/bitcoin-node-watchdog/.venv/bin/python` |
| Watchdog fires but node is actually fine | Heartbeat Lambda timeout too short | Increase `SILENCE_THRESHOLD_MINUTES` in the CDK stack and redeploy |

## License

MIT © Jan Rothen — see [LICENSE](LICENSE) for details.
