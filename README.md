# bitcoin-node-watchdog

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
