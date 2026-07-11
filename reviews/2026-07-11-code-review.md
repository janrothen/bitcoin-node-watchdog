# Code Review — bitcoin-node-watchdog

**Date:** 2026-07-11
**Scope:** Full project (`src/`, `aws/`, `scripts/`, `deploy/`, `tests/`, CI workflows)
**Baseline:** `main` @ `79387b1`, 48/48 tests passing, `ruff check` clean

---

## 1. Critical issues

### 1.1 Non-object JSON body crashes the receiver on the unauthenticated path

- **File:line:** `aws/lambdas/heartbeat_receiver/lambda_function.py:27-31`, crash at line 95
- **Severity:** major
- **Issue:** `_parse_body` accepts any valid JSON, but `lambda_handler` immediately calls `body.get("sent_at")`. A body of `[]`, `"x"`, `42`, or `null` parses fine and then raises `AttributeError` — an unhandled exception, so the Function URL returns 502 instead of 400.
- **Why it matters:** This is the Pi → AWS trust boundary; the Function URL has `auth_type=NONE`, so any unauthenticated internet caller can trigger handler crashes with a 2-byte payload. Each crash logs a stack trace and pollutes the Lambda `Errors` metric, which drowns out real failures.
- **Suggested fix:** In `_parse_body`, after `json.loads`, raise the existing 400 `_ValidationError` when the result is not a `dict`:
  ```python
  parsed = json.loads(event.get("body") or "{}")
  if not isinstance(parsed, dict):
      raise _ValidationError({"statusCode": 400, "body": "invalid json"})
  return parsed
  ```
  Add a test (`body=json.dumps([])`) to `tests/test_heartbeat_receiver.py`.

### 1.2 `_wait_for_verack` has no overall deadline — the in-code bound claim is inaccurate

- **File:line:** `aws/lambdas/reachability_checker/lambda_function.py:79-96`
- **Severity:** major
- **Issue:** The comment says the loop is "bounded by the 10s socket timeout even if the remote sends continuous garbage," but `settimeout(10)` is a *per-recv* timeout, not a wall-clock deadline. A peer that dribbles 1 byte every ~9 seconds keeps every `recv` alive; the 4096-byte cap then permits up to ~4096 iterations, so the real bound is the Lambda's 30s timeout, not the socket timeout.
- **Why it matters:** This is the AWS → Bitcoin-network trust boundary — the peer is attacker-controlled (DNS points at a home IP; whoever holds that IP answers). A slow-dribbling peer pins the Lambda until its hard timeout, so `_put_metric` never runs: EventBridge retries twice, the event lands in the DLQ, and the hour's datapoint is missing. Outcome is fail-safe (missing data breaches), but you get timeout kills + DLQ noise instead of a clean `NodeReachable=0`, and the code's stated safety property doesn't hold.
- **Suggested fix:** Track a deadline and shrink the remaining recv timeout each iteration:
  ```python
  deadline = time.monotonic() + 10
  while len(buf) < 4096:
      remaining = deadline - time.monotonic()
      if remaining <= 0:
          return False
      sock.settimeout(remaining)
      chunk = sock.recv(256)
      ...
  ```
  Then the 30s Lambda timeout stays comfortable headroom rather than the actual bound.

---

## 2. Suggestions

### 2.1 HMAC signs only `sent_at`, leaving `source` outside the authenticated envelope

- **File:line:** `src/heartbeat_sender/sender.py:31`, `aws/lambdas/heartbeat_receiver/lambda_function.py:43-45`
- **Severity:** minor
- **Issue:** The signature covers only the timestamp, so `source` — which becomes the CloudWatch `NodeId` dimension the alarm is keyed on — is not authenticated. Anyone holding a still-fresh signed request (≤90s) can replay it with an arbitrary `source`, minting arbitrary metric dimensions.
- **Why it matters:** This matches the documented design decision (`HMAC-SHA256(secret, sent_at)`), and HTTPS makes capture impractical, so it's not urgent — but signing the whole canonical body (e.g. `HMAC(secret, f"{source}.{sent_at}")` or the raw JSON body bytes) would close the gap at zero operational cost and also makes replays fully inert.
- **Suggested fix:** Sign the raw request body bytes on the sender and verify against `event["body"]` on the receiver; keep `hmac.compare_digest`.

### 2.2 Receiver trusts body `source` for the alarm-critical NodeId dimension

- **File:line:** `aws/lambdas/heartbeat_receiver/lambda_function.py:83-87` vs `aws/stacks/bitcoin_monitor_stack.py:161`
- **Severity:** minor
- **Issue:** The alarm watches `NodeId=<CDK context node_id>`, but the metric dimension comes from the Pi's `.env` `NODE_ID`. If the two ever diverge (typo, renamed node), heartbeats are recorded under the wrong dimension while the smoke test still prints PASS (it checks only for a 200), and the alarm goes to ALARM despite a healthy Pi.
- **Why it matters:** Two sources of truth for the same identifier is the classic "everything looks green while the alarm fires" misconfiguration. It fails loud (good) but confusingly.
- **Suggested fix:** Pass `NODE_ID` to the receiver Lambda's environment (the stack already has it) and either reject mismatched `source` with a 400 or ignore the body value entirely and always emit under the configured NodeId.

### 2.3 `PutMetricData` policy should be namespace-scoped

- **File:line:** `aws/stacks/bitcoin_monitor_stack.py:102-107` and `136-141`
- **Severity:** minor
- **Issue:** `cloudwatch:PutMetricData` genuinely requires `resources=["*"]` (it has no resource-level ARNs), but the statement can still be constrained with a condition.
- **Why it matters:** A compromised Lambda (the receiver is internet-facing) could otherwise write metrics into any namespace, including ones other alarms/billing dashboards read.
- **Suggested fix:**
  ```python
  iam.PolicyStatement(
      actions=["cloudwatch:PutMetricData"],
      resources=["*"],
      conditions={"StringEquals": {"cloudwatch:namespace": "BitcoinNode"}},
  )
  ```

### 2.4 KMS key policy for CloudWatch lacks a confused-deputy guard

- **File:line:** `aws/stacks/bitcoin_monitor_stack.py:67-73`
- **Severity:** minor
- **Issue:** The key grants `kms:GenerateDataKey*`/`kms:Decrypt` to the `cloudwatch.amazonaws.com` service principal with no `aws:SourceAccount` condition.
- **Why it matters:** Service principals without source conditions are the standard cross-account confused-deputy pattern; scoping to your account is a one-liner.
- **Suggested fix:** Add `conditions={"StringEquals": {"aws:SourceAccount": self.account}}` to the policy statement.

### 2.5 `smoke_test.py` has no request timeout

- **File:line:** `scripts/smoke_test.py:31-44`
- **Severity:** minor
- **Issue:** Both `requests.post` calls omit `timeout`, so the script can hang forever; the production sender correctly uses 10s.
- **Why it matters:** It's the post-deploy verification tool — the one script you run when something might already be wrong is the one that can hang.
- **Suggested fix:** `timeout=10` on both calls (flake8-bugbear doesn't catch this; ruff's `S113` under the `S` ruleset would).

### 2.6 Unauthenticated Function URL has no concurrency/throttle guard

- **File:line:** `aws/stacks/bitcoin_monitor_stack.py:109-111`
- **Severity:** minor
- **Issue:** `auth_type=NONE` plus the endpoint URL committed in `config.toml` means anyone can invoke the Lambda at will; auth happens only inside the handler, after you've paid for the invocation.
- **Why it matters:** One curl loop can run receiver concurrency to the account limit and generate invocation cost; there's nothing to shed load before the handler runs.
- **Suggested fix:** Set `reserved_concurrent_executions` on the receiver (e.g. 2–5 — one Pi posting hourly needs almost nothing) so abuse is capped and can't starve other functions in the account.

### 2.7 `test_wrong_token_returns_401` doesn't test a wrong token

- **File:line:** `tests/test_heartbeat_receiver.py:81-85`
- **Severity:** minor
- **Issue:** The test sends header `x-heartbeat-token` (wrong header *name*), so it exercises the missing-header path — duplicating `test_missing_token_returns_401`. A wrong *value* under the correct header `x-heartbeat-signature-256` is never tested.
- **Why it matters:** The `hmac.compare_digest` rejection branch — the core auth check on the trust boundary — currently has no direct coverage; a regression that accepted any non-empty token would pass the suite.
- **Suggested fix:** `_event(headers={"x-heartbeat-signature-256": "0" * 64})` and assert 401. Also consider a test for a >90s *future* `sent_at` to cover the `abs()` clock-skew branch (`_check_freshness`), which is currently only tested in the past direction.

### 2.8 Docs claim DynamoDB, code has none

- **File:line:** `CLAUDE.md:28`, `README.md:30`
- **Severity:** minor
- **Issue:** Both docs say the heartbeat receiver writes to DynamoDB ("POST from Pi → DynamoDB + CloudWatch metric"); no DynamoDB table, IAM grant, or client exists anywhere in the codebase.
- **Why it matters:** The review checklist asks whether changes match `CLAUDE.md`'s stated design — right now the stated design itself is stale, which will mislead future reviews and any agent using `CLAUDE.md` as ground truth.
- **Suggested fix:** Delete the DynamoDB mentions (or implement the table if durable heartbeat history is actually wanted — the metric-only approach seems sufficient for alarming).

### 2.9 Nits

- `aws/lambdas/reachability_checker/lambda_function.py:47` — `struct.pack("<Q", int.from_bytes(os.urandom(8), "little"))` is an 8-byte round-trip to itself; `nonce = os.urandom(8)` is identical.
- `aws/lambdas/reachability_checker/lambda_function.py:32` — `socket.gethostbyname` is IPv4-only and legacy; fine while DuckDNS serves A records, but `socket.getaddrinfo` would survive an IPv6 move.
- `deploy/cron/bitcoin-node-watchdog` — setting `HOME=` to the project directory works but repurposes a semantically loaded variable (anything reading `$HOME` — pip, dotfiles — is redirected). A plain project-path variable (`APP_DIR=...` + `cd $APP_DIR`) says what it means.
- `aws/stacks/bitcoin_monitor_stack.py:114-119` — the checker DLQ has no alarm/consumer, so entries age out silently after 14 days. Low priority because a checker failure already alarms via missing data (`TreatMissingData.BREACHING`), but a tiny `ApproximateNumberOfMessagesVisible > 0` alarm on the existing SNS topic would make retry exhaustion visible.
- `aws/stacks/bitcoin_monitor_stack.py:98-100` — secret as a plain Lambda env var is already flagged by the in-code comment as a known tradeoff (visible in the console and the synthesized CloudFormation template). Noting for the record that the comment's own recommendation (SSM SecureString/Secrets Manager) is the right eventual move; the GitHub OIDC deploy at least keeps it out of long-lived credentials.

---

## 3. What works well

- **Auth hardening on the receiver is genuinely thoughtful:** `hmac.compare_digest` for constant-time comparison, signature verification *before* any field parsing, and uniform 401s for missing/malformed `sent_at` so unauthenticated callers can't probe field names via differentiated error codes — with comments explaining exactly that intent.
- **Alarm wiring is consistent end-to-end** and covered by assertions: 1h metric period and Sum/Maximum statistics match what each Lambda emits, `EvaluationPeriods=6` + `DatapointsToAlarm=6` matches the documented 6h threshold, and `TreatMissingData.BREACHING` means a dead checker Lambda fails loud rather than silent. `tests/test_bitcoin_monitor_stack.py` pins all of it, so infra drift breaks CI.
- **Failure paths fail loudly on the Pi:** the sender prints to stderr and `__main__.run` exits non-zero on any failure, so the cron log + logrotate setup actually capture problems; tests assert both the exit behavior and the stderr output.
- **Test hygiene:** `conftest.py` stubs `boto3` and sets env vars *before* lambda import so no test can touch real AWS; failure paths (DNS error, connection refused, garbage stream, closed socket, stale timestamp, non-string field types) are covered, not just happy paths.
- **The P2P read loop is bounded in bytes with a written rationale** for the substring-scan tradeoff — right instinct at that trust boundary (see 1.2 for the remaining time-bound gap).
- **Deploy posture:** OIDC role assumption instead of long-lived AWS keys, encrypted SNS topic with a documented reason for the customer-managed key, DLQ on the async-invoked Lambda, and secrets kept to GitHub Secrets / `.env` (`.env.example` is a clean template).

---

## Summary

| # | File:line | Severity | Issue |
|---|-----------|----------|-------|
| 1.1 | `heartbeat_receiver/lambda_function.py:27` | major | Non-dict JSON body → unhandled `AttributeError` → 502 on unauthenticated path |
| 1.2 | `reachability_checker/lambda_function.py:79` | major | No wall-clock deadline in verack loop; comment overstates the 10s bound |
| 2.1 | `sender.py:31` / receiver `:43` | minor | HMAC covers only `sent_at`; `source` replayable/forgeable within 90s window |
| 2.2 | receiver `:83` / stack `:161` | minor | Body-supplied `source` vs CDK `node_id` — two sources of truth for the alarm dimension |
| 2.3 | stack `:102,:136` | minor | `PutMetricData *` without `cloudwatch:namespace` condition |
| 2.4 | stack `:67` | minor | KMS key policy missing `aws:SourceAccount` condition |
| 2.5 | `smoke_test.py:31` | minor | No `requests` timeout in the post-deploy verifier |
| 2.6 | stack `:109` | minor | Open Function URL with no reserved concurrency cap |
| 2.7 | `test_heartbeat_receiver.py:81` | minor | "Wrong token" test never exercises the signature-mismatch branch |
| 2.8 | `CLAUDE.md:28`, `README.md:30` | minor | Docs describe a DynamoDB write that doesn't exist |
| 2.9 | various | nit | Nonce round-trip, IPv4-only DNS, `HOME=` in cron, unmonitored DLQ, env-var secret |

No blockers. The two majors are small, contained fixes (an `isinstance` check and a deadline in the recv loop). Overall the codebase is small, deliberate, and unusually well-commented about its security tradeoffs.
