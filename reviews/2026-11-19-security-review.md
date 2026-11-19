# Security Review — bitcoin-node-watchdog

**Date:** 2026-11-19
**Scope:** Application code (`src/`, `aws/`, `scripts/`, `deploy/`), dependency manifests, CI workflows
**Baseline:** `main` @ `4758c3d`, 72/72 tests passing
**Advisory sources:** `pip-audit` (PyPI advisory DB and OSV), run against the local dev venv and a fresh resolve of the runtime dependencies

This review is not a guarantee that the codebase is free of vulnerabilities. It records what was checked, what was fixed, and what is left for a decision.

---

## 1. Confirmed issues (fixed on `security/dependency-and-ci-hardening`)

| # | Issue | Evidence | Fix |
|---|-------|----------|-----|
| 1.1 | Unauthenticated receiver crash: a non-ASCII `X-Heartbeat-Signature-256` header makes `hmac.compare_digest(str, str)` raise `TypeError`, so the caller gets a 502 instead of 401 | `aws/lambdas/heartbeat_receiver/lambda_function.py` `_verify_signature`; reproduced with new tests | Compare as bytes; 3 regression tests |
| 1.2 | Secrets interpolated with `${{ secrets.* }}` directly into a `run:` script in the deploy job (template expansion happens before the shell parses the script) | `.github/workflows/deploy-aws.yml` Deploy step | Secrets passed via `env:` and quoted `"$VAR"` |
| 1.3 | Third-party actions referenced by mutable tags, including in the job holding AWS OIDC deploy credentials | all workflows | Pinned to full commit SHAs (same versions the tags resolved to on 2026-11-19) |
| 1.4 | `gitguardian.yml` and `sonarcloud.yml` had no `permissions:` block, so they ran with the repo's default `GITHUB_TOKEN` scope | workflow files | `contents: read` (+ `pull-requests: read` for Sonar) |
| 1.5 | certifi < 2026.10.18 trusts compromised emSign intermediates. This affects TLS from the Pi to the Lambda URL, and an install could still resolve to it (local venv had 2026.2.25) | GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320 | `certifi>=2026.10.19` runtime floor |
| 1.6 | Production deploy installed `aws-cdk-lib>=2.170.0` with no upper bound, which is inconsistent with `pyproject.toml` (`~=2.248`) | `aws/requirements.txt` | Aligned to `~=2.248` / `~=10.6` |
| 1.7 | A local `cdk synth`/`deploy` writes the heartbeat secret in plaintext to `aws/cdk.out/`, which was not git-ignored | `.gitignore` | Ignore `cdk.out/` |

## 2. Scanner findings assessed as not exploitable here (still upgraded where cheap)

| Package (was) | Advisory | Why not exploitable | Action |
|---------------|----------|---------------------|--------|
| urllib3 2.6.3 | GHSA-qccp-gfcp-xxvc, GHSA-mf9v-mfxr-j63j, GHSA-vxq7-64xx-v4gw, GHSA-gh4c-6fx4-qh6g, GHSA-8988-9cw3-xx77 | Sender uses `requests` (own redirect handling), no proxy, no streaming, fixed AWS endpoint | `urllib3>=2.8,<3` floor (defense in depth) |
| aws-cdk-lib 2.248.0 | GHSA-464c-974j-9xm6 | Only affects CodeBuild `S3LoggingOptions.encrypted`; the stack has no CodeBuild | Venv now 2.277.0 (CI always installs latest 2.x) |
| idna 3.11 | GHSA-65pc-fj4g-8rjx | DoS on attacker-supplied hostnames; the only hostname is a static config value | Venv upgraded; no floor |
| pytest 9.0.2 | GHSA-6w46-j5rx-g56g | Local `/tmp` race on multi-user hosts; dev only | `pytest>=9.0.3,<10` |
| virtualenv 21.2.0, filelock 3.25.2, setuptools 82.0.1 | many (see pip-audit) | Dev-only tooling pulled in by `pre-commit` / the venv; not shipped to the Pi or Lambda | Local venv upgraded; no manifest change |

After the fixes, `pip-audit` reports no known vulnerabilities for the dev venv or for a fresh resolve of the runtime dependencies (`requests 2.34.2`, `urllib3 2.8.0`, `certifi 2026.10.23`, `idna 3.20`, `python-dotenv 1.2.4`).

## 3. Needs human review (not changed)

| # | Risk | Tradeoff |
|---|------|----------|
| 3.1 | **OIDC trust policy scope.** `deploy-aws.yml` also runs on `workflow_dispatch`, which can be triggered from any branch. If the IAM role's trust policy only checks the repo (not `ref:refs/heads/main` or a GitHub environment), any branch can deploy to prod | The trust policy lives in AWS, not in this repo, so it needs checking there. **Partly fixed:** the deploy job now has `if: github.ref == 'refs/heads/main'`. Still to do in AWS: restrict the trust policy's `sub` to `main` |
| 3.2 | **Deploy role is over-privileged.** README documents `IAMFullAccess`, `AWSLambda_FullAccess`, etc. on the GitHub deploy role | Least privilege is to let the role only `sts:AssumeRole` the CDK bootstrap roles (`cdk-*-deploy-role`, `cdk-*-file-publishing-role`). This changes the AWS setup, so it is not a repo edit |
| 3.3 | **Unpinned CDK CLI.** `npm install -g aws-cdk` installs whatever is latest, inside a job with prod credentials | Pinning (`aws-cdk@<exact>`) removes the supply-chain drift but needs bumping whenever `aws-cdk-lib` needs a newer cloud-assembly schema |
| 3.4 | **No lockfile.** Runtime and deploy dependencies are ranges and are resolved at install time on the Pi and in CI | A hashed lock (`uv lock` / `pip-compile --generate-hashes`) gives reproducible installs but adds an update workflow. Until then, re-install on the Pi to pick up the new floors |
| 3.5 | **Heartbeat secret in Lambda env and CloudFormation template** (already a known item, 2026-07-11 review 2.9) | Move to SSM SecureString / Secrets Manager; needs out-of-band secret creation |
| 3.6 | **Monitoring DoS.** The Function URL is public and its URL is committed in `config.toml`. Sustained flooding can saturate the 5 reserved executions and throttle real heartbeats, which would cause a false "heartbeat missing" alarm after 6h | Accepting this is reasonable for a home node. Alternatives (IAM-auth Function URL with a Pi IAM user, or API Gateway + throttling/WAF) add credentials or cost |
| 3.7 | Within the 90 s freshness window a captured request can be replayed | Impact is one extra `HeartbeatReceived` datapoint; capture requires breaking TLS |
| 3.8 | `pre-commit` pins ruff `v0.11.2` while the dev extra requires `ruff>=0.15.9` | Not a security issue; the hook and CI lint can disagree |

## 4. Areas checked with no findings

- No `eval`/`exec`, `pickle`, `yaml.load`, `subprocess`/`shell=True`, SQL, file-path handling of untrusted input, or LLM/agent code paths
- Sender: TLS verification on (requests default), 10 s timeout, secret never logged; `traceback.print_exc` only prints env var names on `KeyError`
- Receiver: auth before parse, constant-time compare, freshness check, `NodeId` pinned server-side, namespace-scoped `PutMetricData`
- Checker: hostname/port come from deploy-time config only (no SSRF input); reads bounded to 4096 bytes and a 10 s wall-clock deadline
- KMS key grant has an `aws:SourceAccount` confused-deputy guard
