# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyen Nam Khanh  
**Ngày chạy:** 25 November 2026 (GMT+7)  
**Environment:** macOS-13.7.5-x86_64-i386-64bit; 8 logical host CPUs; Python 3.12.16. Docker Desktop was allocated 6 CPUs and 4,112,519,168 bytes of RAM; source: `reports/docker-environment.json`.

## 1. SLO

| SLI | SLO | Reason |
|---|---|---|
| `/ask` p95 latency | ≤ 500 ms | Default local load-test gate; capture slow-user experience |
| `/ask` error rate | ≤ 2% | Default local gate; counts every non-200 result |
| Golden-dataset accuracy | 100%, zero regressions | Final lab quality requirement (23 examples) |

The CI exercise enforces ≥85%; final local acceptance is stronger at 100%. Production alerts retain the supplied separate thresholds: error rate >5% for 1m and p95 >1s for 2m. Those alerts are not equivalent to the local SLO gate.

## 2. Performance — agent v2

Each local run sends 300 requests. Baseline configuration: `MOCK_ERROR_RATE=0.01`, `MOCK_SLOW_RATE=0.03`. The mock is random and unseeded. These runs shared the host with Docker image builds/downloads; results describe this machine/session and cannot isolate application capacity from host contention. Latency percentiles use successful responses, while error rate uses all responses.

### 2.1 Concurrency

| Concurrency | RPS | p50 ms | p95 ms | p99 ms | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 4.04 | 193.0 | 234.8 | 1705.5 | 0.33% | PASS |
| 10 | 29.0 | 205.9 | 1686.5 | 1762.1 | 0.00% | FAIL |
| 50 | 32.74 | 548.0 | 4688.2 | 6539.8 | 1.33% | FAIL |
| 100 | 25.83 | 2440.0 | 7786.3 | 9167.8 | 0.67% | FAIL |

Source: `reports/load_v2_c{1,10,50,100}.json`. Throughput did not scale linearly: it rose to concurrency 50 then declined at 100, while p95 rose sharply. Queueing, event-loop/client work and host contention contribute; these measurements do not identify one bottleneck conclusively. Failed SLO gates were retained as evidence.

### 2.2 Tail latency (concurrency 20)

| MOCK_SLOW_RATE | Average ms | p95 ms | p99 ms |
|---|---:|---:|---:|
| 0 | 205.6 | 252.4 | 269.6 |
| 0.03 | 228.1 | 307.9 | 490.2 |
| 0.1 | 399.8 | 1728.4 | 2024.6 |

Source: `reports/load_v2_slow_*.json`. At a 10% slow rate, more than 5% of requests fall in the slow population, moving p95 sharply. Average dilutes that population; high percentiles reveal it. With only 300 unseeded requests, the realized slow fraction varies, so percentile changes need not be monotonic across every run. Use p95/p99 and error rate alongside the mean.

## 3. Quality

Evaluations disable random upstream errors/slow injection to isolate answer quality. The original 23-question dataset and eval script were unchanged. Gate threshold is 100% for all three recorded evaluations; the final run also compares with the original v2 baseline.

| Metric | v1 | v2 original | v2 fixed |
|---|---:|---:|---:|
| Accuracy | 1/23 (4.35%) | 21/23 (91.30%) | 23/23 (100.00%) |
| Avg tokens / question | 56.8 | 108.7 | 113.3 |
| Total cost (USD) | 0.0004 | 0.000756 | 0.000787 |
| Cost / correct answer (USD) | 0.00039975 | 3.599e-05 | 3.423e-05 |
| Quality gate (100%) | FAIL | FAIL | PASS |

| Original failure | Missing keywords | Knowledge-base fix |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Add a JWT/API-key comparison with expiry and signature verification |
| scaling-03 | cpu, memory, custom metrics | Add Kubernetes HPA scaling signals |

The two new entries appear in both develop and production knowledge bases. The final gate reports 23/23 and zero regressions. v2 uses more input context and output tokens than v1, increasing per-call cost; cost per correct answer measures useful work instead of rewarding cheap incorrect responses. Costs here are simulated mock-model token charges, not actual cloud invoices. Eval report costs are rounded aggregates.

The pull-request job `.github/workflows/eval.yml` runs eval with `--min-accuracy 0.85`. Exit 1 fails the job; branch protection must make that job required to block merging. A job alone does not enable branch protection.

## 4. Observability

### 4.1 Evidence and dashboard interpretation

- [Grafana dashboard](screenshots/grafana-dashboard.png)
- [Slow trace](screenshots/jaeger-slow-trace.png)
- [Error trace](screenshots/jaeger-error-trace.png)
- [Prometheus alerts](screenshots/prometheus-alert-firing.png)

Prometheus snapshot after the scale-3 run: p95 563.8 ms; average 257.5 ms. Histogram p95 is estimated from buckets; Locust computes percentiles from its own request samples. They need not match exactly.

Request rates by target from the same snapshot: `172.22.0.4:8000`: 18.22 requests/s; `172.22.0.8:8000`: 19.64 requests/s; `172.22.0.9:8000`: 18.16 requests/s. The target rates indicate how Nginx shares traffic; a short run with random delays will not be perfectly equal.

Input prompts include system instructions, retrieved context and the user question. The relative input/output rate depends on the sampled questions and answer lengths; retrieval does not guarantee input exceeds output. The dashboard and token counters provide the measured comparison. The Nginx ingress returns 404 for `/metrics` while Prometheus scrapes agent instances directly over the internal network; see `reports/metrics-ingress.json`.

Metric examples: `http_requests_total` (Counter), `agent_in_flight_requests` (Gauge), `http_request_duration_seconds` (Histogram). Added `agent_question_length_chars` with bounded character buckets. Route labels use matched route templates or `unmatched`; raw bot-generated paths would create unbounded time series and exhaust memory. Request IDs belong in logs/traces, not metric labels.

### 4.2 Fault injection and alerts

Injected `MOCK_ERROR_RATE=0.2` (experiment A) and `MOCK_SLOW_RATE=0.3` (experiment B) together, preserving all alert thresholds and hold times. Detection time includes container recreation and Prometheus observation, measured from the start of the change.

| Change | Alert | Time to first firing (s) | Panel |
|---|---|---:|---|
| A: error rate 20% | AgentHighErrorRate | 93.94 | Errors |
| B: slow rate 30% | AgentHighLatencyP95 | 149.24 | Latency p95 |

Raw polling timeline: [alert-timeline.json](reports/alert-timeline.json). Experiments C (large model), D (paused instance) and E (v1) were not run as separate chaos experiments; no detection times are claimed for them.

Changing to v1 can lower answer accuracy without increasing HTTP failures or latency. Detect that with golden-dataset canaries, scheduled production evals, labeled quality samples and an accuracy/regression alert. Infrastructure golden signals alone do not measure correctness.

### 4.3 Trace debugging

Slow trace `273d8787e59841998e60419ed58693fa`: 1722.399 ms total; `chat mock-llm-small` takes 1694.198 ms (98.4%). The LLM span dominates the request, consistent with the injected upstream delay.

Error trace `416911366929532c7092b005eebe08f0` contains a recorded `exception` event. Raw spans and matching JSON logs are saved in `reports/jaeger-*-trace.json` and `reports/jaeger-*-logs.json`.

Matching slow-trace log:

```json
{"ts": "2026-11-25T14:30:59.356901+00:00", "level": "INFO", "service": "observable-agent", "instance": "d9f6b962a132", "event": "llm_call", "trace_id": "273d8787e59841998e60419ed58693fa", "span_id": "1291ec2e5cbfea28", "request_id": "89c07495aff1", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1691.2}
```

## 5. Scaling — Locust headless

Each recorded scaling run uses 100 users, spawn rate 10/s, 2 minutes, supplied user think time and the same model/fault defaults. The aggregate includes `/ask` and `/health`; detailed per-route rows remain in CSV.

| Instances | RPS | p50 ms | p95 ms | p99 ms | Failures |
|---|---:|---:|---:|---:|---:|
| 1 | 56.15214324405074 | 230 | 1700 | 2400 | 47 |
| 3 | 63.2872022616577 | 200 | 760 | 1700 | 82 |

Sources: `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`. The warmed one-instance repeat produced 56.15 RPS versus 63.29 RPS for three instances; p95 fell from 1700 ms to 760 ms. This is about 12.7% more throughput in these runs, far below 3×. Both configurations still had mock upstream failures. The single-instance run was repeated after startup warm-up to exclude initial proxy 502s; superseded output is retained under `reports/superseded-scaling/`. Container-count snapshots confirm the final runs used one and three instances. `docker compose run --no-deps` preserves those counts. More replicas increase available CPU/process capacity, but cannot eliminate upstream mock delay or overcome the load generator's user/think-time ceiling. Inspect the actual CSV before attributing a p95 change to scaling; the short unseeded tests are not controlled capacity estimates.

## 6. Lessons and next changes

1. Preserve measured failures: mean latency can look acceptable while a tail percentile or SLO fails.
2. Use eval alongside metrics: fast successful HTTP responses can still contain incorrect answers.
3. Correlate trace IDs and JSON logs to locate upstream delay and errors without exposing secrets.

For a real service, add queue-depth/concurrency limits, provider token reconciliation, reservation-based budget enforcement, dependency readiness alerts, and scheduled accuracy canaries. Wire alert routing and make the CI gate required. Public deployment evidence is tracked separately in `DEPLOYMENT.md`.

## Reproduction

Run from the repository root with the project virtual environment:

```bash
.venv/bin/python scripts/run_local_examples.py
.venv/bin/python scripts/run_benchmarks.py load
.venv/bin/python scripts/run_benchmarks.py fixed
.venv/bin/python scripts/write_reports.py
```

The original baseline v2 report was captured before the knowledge-base edit; rerunning `baseline` on the fixed code would overwrite that historical evidence and is unnecessary. After starting the observability Compose stack with one agent, `scripts/run_observability.py` collects scaling/chaos/browser evidence. It needs Docker access, Playwright, and the installed Chrome executable used in this environment.
