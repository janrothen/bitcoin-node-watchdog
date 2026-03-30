# bitcoin-node-watchdog

Monitors a Bitcoin full node on Raspberry Pi. The Pi sends an hourly heartbeat to AWS. A Lambda on AWS independently checks internet reachability every hour via a Bitcoin P2P handshake (DuckDNS → IP → port 8333 version/verack). CloudWatch Alarms trigger SNS email alerts after 6h of missing data — one email on failure, one on recovery.

## Target environment
- Hardware: Raspberry Pi 4, 8 GB RAM
- OS: Debian GNU/Linux 13 (trixie), aarch64
- Python: 3.13.5
- AWS region: eu-north-1 (Stockholm)

## Structure
```
src/bitcoin_reachability/   # installable package
  __main__.py               # entry point: python -m bitcoin_reachability
                            # sends heartbeat unconditionally every hour
  utils/
aws/                        # CDK infrastructure (deployed via GitHub Actions)
  app.py
  stacks/bitcoin_monitor_stack.py
  lambdas/
    heartbeat_receiver/     # POST from Pi → DynamoDB + CloudWatch metric
    reachability_checker/   # EventBridge hourly → Bitcoin P2P check → CloudWatch metric
.github/workflows/
  deploy-aws.yml            # push to main → cdk deploy (eu-north-1)
tests/
config.toml                 # runtime config (heartbeat URL only)
pyproject.toml              # packaging and dependencies
```

## Key design decisions
- Pi sends heartbeat unconditionally — reachability check is done independently by Lambda
- Reachability check performs a real Bitcoin P2P handshake (version/verack), no third-party APIs
- DuckDNS hostname `you-monkey.duckdns.org` resolves to current public IP via standard DNS
- CloudWatch Alarms handle state: one email on ALARM, one on OK — no repeated alerts
- Alarm threshold: 6 consecutive hourly periods (6 hours) of missing/failed data
- SES replaced by SNS; SNS subscription must be confirmed after first deploy

## Dev/test
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
