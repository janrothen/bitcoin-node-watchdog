#!/usr/bin/env bash
# Reset the HeartbeatMissing alarm to OK to test the SNS recovery email.
aws cloudwatch set-alarm-state \
  --alarm-name "BitcoinNode-HeartbeatMissing" \
  --state-value OK \
  --state-reason "Manual test: simulating recovery" \
  --region eu-north-1
