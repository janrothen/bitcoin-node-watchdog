#!/usr/bin/env bash
# Manually trigger the HeartbeatMissing alarm to test the SNS alert email.
aws cloudwatch set-alarm-state \
  --alarm-name "BitcoinNode-HeartbeatMissing" \
  --state-value ALARM \
  --state-reason "Manual test: simulating missing heartbeats" \
  --region eu-north-1
