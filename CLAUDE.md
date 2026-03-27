# bitcoin-node-watchdog

Monitors a Bitcoin full node on Raspberry Pi. Checks external reachability via bitnodes.io and alerts via AWS when the node goes offline.

## Target environment
- Hardware: Raspberry Pi 4, 8 GB RAM
- OS: Debian GNU/Linux 13 (trixie), aarch64
- Python: 3.13.5

## Structure
```
src/bitcoin_reachability/   # installable package
  __main__.py               # entry point: python -m bitcoin_reachability
  utils/
aws/                        # CDK infrastructure (deployed via GitHub Actions)
  app.py
  stacks/bitcoin_monitor_stack.py
  lambdas/
    heartbeat_receiver/
    heartbeat_watchdog/
.github/workflows/
  deploy-aws.yml            # push to main → cdk deploy (eu-central-1)
tests/
config.toml                 # runtime config (bitnodes endpoint, heartbeat URL)
pyproject.toml              # packaging and dependencies
```

## Dev/test
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
