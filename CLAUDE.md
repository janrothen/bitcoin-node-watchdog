# bitcoin-node-watchdog

Monitors a Bitcoin full node on Raspberry Pi. The Pi sends an hourly heartbeat to AWS. A Lambda on AWS independently checks internet reachability every hour via a Bitcoin P2P handshake (DuckDNS → IP → port 8333 version/verack). CloudWatch Alarms trigger SNS email alerts after 6h of missing data — one email on failure, one on recovery.

## Target environment
- Hardware: Raspberry Pi 4, 8 GB RAM
- OS: Debian GNU/Linux 13 (trixie), aarch64
- Python: 3.13.5
- AWS region: eu-north-1 (Stockholm)

## Structure
```
src/heartbeat_sender/       # installable package
  __main__.py               # entry point: python -m heartbeat_sender
                            # sends heartbeat unconditionally every hour
  config.py                 # loads config.toml and .env
scripts/
  smoke_test.py             # manual post-deploy verification (401 + 200 check)
  test_alarm.sh             # manually trigger ALARM state for pipeline testing
  test_recovery.sh          # manually trigger OK state for pipeline testing
aws/                        # CDK infrastructure (deployed via GitHub Actions)
  app.py
  cdk.json
  requirements.txt
  stacks/bitcoin_monitor_stack.py
  lambdas/
    heartbeat_receiver/
      lambda_function.py    # POST from Pi → CloudWatch metric
    reachability_checker/
      lambda_function.py    # EventBridge hourly → Bitcoin P2P check → CloudWatch metric
deploy/
  cron/
    bitcoin-node-watchdog   # cron job for Pi (runs heartbeat_sender hourly)
    README.md               # installation steps for the cron job
  logrotate.d/
    bitcoin-node-watchdog   # logrotate drop-in for /var/log/bitcoin-node-watchdog-cron.log
    README.md               # installation steps for logrotate
.github/workflows/
  deploy-aws.yml            # push to main → cdk deploy (eu-north-1)
  sonarcloud.yml            # SonarCloud analysis on push/PR
tests/
  conftest.py
  test_heartbeat_receiver.py
  test_heartbeat_sender.py
  test_reachability_checker.py
  test_bitcoin_monitor_stack.py
reviews/                    # code review findings and fix status
config.toml                 # runtime config (heartbeat URL only)
pyproject.toml              # packaging and dependencies
.env.example                # template for .env (HEARTBEAT_SECRET, NODE_ID)
sonar-project.properties    # SonarCloud project configuration
.pre-commit-config.yaml     # pre-commit hooks (ruff lint/format)
```

## Key design decisions
- Pi sends heartbeat unconditionally — reachability check is done independently by Lambda
- Reachability check performs a real Bitcoin P2P handshake (version/verack), no third-party APIs
- DuckDNS hostname `you-monkey.duckdns.org` resolves to current public IP via standard DNS
- CloudWatch Alarms handle state: one email on ALARM, one on OK — no repeated alerts
- Alarm threshold: 6 consecutive hourly periods (6 hours) of missing/failed data
- SES replaced by SNS; SNS subscription must be confirmed after first deploy
- Heartbeat auth: sender computes `HMAC-SHA256(secret, raw request body)` and sends the hex digest as `X-Heartbeat-Signature-256` — secret never in plaintext; every body field (source, sent_at) is authenticated; receiver verifies before parsing and rejects requests older than 90 seconds
- Receiver pins the CloudWatch `NodeId` dimension to its `NODE_ID` env var (same CDK context value the alarms watch) and rejects a mismatched body `source` with 400 — a misconfigured Pi fails loudly in its own cron log
- Receiver Function URL is unauthenticated at the AWS layer (HMAC checked in-handler), so reserved concurrency is capped at 5 to bound abuse
- Checker failures land in an SQS DLQ after EventBridge retries; a third alarm (`BitcoinNode-CheckerDLQ`) emails when that happens

## Dev/test
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
