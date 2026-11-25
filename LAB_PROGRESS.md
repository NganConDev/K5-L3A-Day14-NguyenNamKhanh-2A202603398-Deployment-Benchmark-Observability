# Lab progress and next commands

Follow `CHECKPOINTS.md` and the K5 corrections in the root README.

| Checkpoint | Status | Evidence |
|---|---|---|
| CP0 Setup | Complete locally | Python 3.12 virtual environment, Docker running |
| CP1 Localhost/production | Complete | `reports/local-examples.txt`, `MISSION_ANSWERS.md` |
| CP2 Docker | Complete | Image sizes/build logs, Nginx HTTP output |
| CP3 Security | Complete | 401/200/429 responses; cost explanation |
| CP4 Scaling | Complete | Three instances, ten preserved messages |
| CP5 Final agent | Complete | Unmodified grader PASS 12/12, 43/43 checks |
| CP6 Railway | Deployed and verified | Public URL and four passing checks in `DEPLOYMENT.md` |
| CP7 Local benchmark/eval | Complete | Seven load JSON reports; final eval 23/23, no regressions |
| CP8 Observability | Complete | Locust CSV, Grafana/Jaeger screenshots, two alerts firing, detection times |
| Submission | Ready for student review | No push or LMS submission performed |

## Run the completed agent locally

From the repository root:

```bash
cp 06-lab-complete/.env.example 06-lab-complete/.env
```

Set a generated private `AGENT_API_KEY` in that ignored file, then:

```bash
cd 06-lab-complete
docker compose -p k5-day14-final up -d --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
../.venv/bin/python check_production_ready.py
```

The grading script creates its own temporary Redis and servers; do not edit it.
To stop the local agent stack, run `docker compose -p k5-day14-final down` from the same directory.

## Read the implementation in order

1. `app/config.py`: environment and secret configuration.
2. `app/auth.py`: API key verification and 401 behavior.
3. `app/redis_client.py`: lazy client and bounded connection timeouts.
4. `app/rate_limiter.py`: atomic Redis Lua sliding window and 429.
5. `app/cost_guard.py`: daily/monthly token accounting and 402.
6. `app/main.py`: input validation, request logs, probes and shutdown.
7. `Dockerfile`, `.dockerignore`, `docker-compose.yml`: reproducible runtime.
8. `railway.toml`: deployment behavior; next steps in `DEPLOYMENT.md`.

## Reproduce reports

From the repository root, use `.venv/bin/python scripts/run_benchmarks.py load` or `fixed`, then `scripts/write_reports.py`.
`baseline` captures the code as it currently exists; avoid overwriting the original pre-fix v2 evidence.
Start the observability stack with project `k5-day14-observability`, one agent, then run `scripts/run_observability.py`.
That script performs deliberate fault injection and leaves the stack running for inspection; stop it after capturing evidence using the same project name.

All local lab stacks were stopped after evidence collection. The public Railway deployment remains running for grading.

## Final review and submission

The repository is public (anonymous HTTP check returned 200). Work in this session is saved locally and has **not been committed, pushed, or submitted on LMS**. After reviewing the implementation, AI log and measured reports, commit and push this working tree, then submit the repository link on LMS according to `SUBMISSION.md`.

The API key stays in the ignored `06-lab-complete/.env.production`; it is absent from publishable files. See `DEPLOYMENT.md` for the private-key loading command. No grader or golden-dataset changes were made.
