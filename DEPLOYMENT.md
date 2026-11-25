# Railway deployment — Part 6

Status: deployed and verified on Railway's trial plan, 25 November 2026 (GMT+7).

**Public URL:** https://agent-production-8e366087.up.railway.app

**Project:** `k5-day14-deployment`  
**Agent deployment:** `6984b02a-07bc-4767-9b4c-b426290b6964` (Railway status `SUCCESS`)  
**Project dashboard:** https://railway.com/project/2737300d-7007-4297-b787-73aa1f317dea

All four CP6 checks passed: health 200, readiness 200, missing key 401, correct key 200.
Actual output: [deployment-http.txt](reports/deployment-http.txt).
The authenticated response body and headers are in [deployment-authenticated-curl.txt](reports/deployment-authenticated-curl.txt).

The private key is kept in the ignored `06-lab-complete/.env.production` (mode 600) and in Railway variables.
Redis runs as a separate service and the agent references `${{Redis.REDIS_URL}}`.
The following steps document how this deployment was created and can be reproduced.

## 1. Select the correct source

Deploy `06-lab-complete/`, using its `Dockerfile` and `railway.toml`.
For a GitHub-connected service, set its root directory to `/06-lab-complete`.
For a CLI upload, run `railway up . --path-as-root --service agent` from `06-lab-complete/` so only Part 6 is uploaded.
Do not deploy the example app in `03-cloud-deployment/` or the root Dockerfile.

## 2. Create the project and Redis

Sign in to Railway, create a project and add a Redis database plus the agent service.
In the agent's variables, reference the Redis service's `REDIS_URL`; use Railway's variable-reference picker.
Keep Redis private within the project. The agent needs Redis for readiness, limits and budget state.

## 3. Set the agent variables

| Variable | Value |
|---|---|
| `AGENT_API_KEY` | Generate a private random key; enter only in Railway variables |
| `REDIS_URL` | Reference to the Redis service's connection URL |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1` |
| `MONTHLY_BUDGET_USD` | `10` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | `8000` set for this deployment; CMD also accepts a platform-injected value |

Generate a key locally with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Do not put the key, Redis credentials, or Railway token into the repository or screenshots.
The cost guard accounts for simulated LLM tokens, not Railway infrastructure charges.

## 4. Deploy and verify

Link the CLI to your project/service, upload, then generate a domain:

```bash
cd 06-lab-complete
railway login
railway link
railway up . --path-as-root --service agent
railway domain --service agent --port 8000
```

From the repository root, export `BASE` to the actual HTTPS domain and enter the private key into your shell environment. Then:

```bash
# The saved private key can be loaded locally without printing it:
set -a
. 06-lab-complete/.env.production
set +a
export BASE=https://agent-production-8e366087.up.railway.app
.venv/bin/python scripts/check_deployment.py
```

Expected results: `/health` 200, `/ready` 200, unauthenticated `POST /ask` 401, authenticated `POST /ask` 200.
The helper prints status codes without printing your key. Save its output to `reports/deployment-http.txt`.

## 5. Deployment evidence

The public URL above was verified. Service screenshots and platform deployment metadata accompany the HTTP checks:

- `screenshots/dashboard.png`: deployment dashboard with successful build/deploy.
- `screenshots/running.png`: actual public health response.
- `screenshots/test.png`: authenticated Swagger request and server response, with credentials hidden. All four status checks are recorded in `reports/deployment-http.txt`.

The helper uses curl when available because this host intermittently reset Python TLS connections to Railway. Retries apply to transport errors; unexpected HTTP status codes still fail the check.

Run the public-URL grading option from Part 6 as an additional check:

```bash
python check_production_ready.py --public-url "$BASE"
```

## Current repository state

The public repository was verified accessible without authentication. The deployment was uploaded from the local Part 6 directory using the CLI. This session's source, reports and screenshots still need a reviewed commit/push before LMS submission; the cloud upload does not push Git changes.

## Local validation

The complete unmodified grader result is in [reports/production-readiness.txt](reports/production-readiness.txt).
It verifies local code, runtime and Docker behavior; its deployment criterion validates platform configuration.
The local PASS is accompanied by the live public HTTP checks, platform status metadata and seven screenshots in this submission. The Swagger capture attaches the private credential at the browser network layer, so it is absent from the rendered curl example.
