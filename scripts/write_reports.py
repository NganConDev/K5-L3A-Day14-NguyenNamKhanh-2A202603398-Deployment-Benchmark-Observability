"""Render benchmark tables directly from the submitted evidence files."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'


def read(name):
    return json.loads((REPORTS / name).read_text())


def main():
    env = read('environment.json')
    rows = []
    for c in (1, 10, 50, 100):
        r = read(f'load_v2_c{c}.json'); l = r['latency_ms']
        rows.append(f"| {c} | {r['rps']} | {l['p50']} | {l['p95']} | {l['p99']} | {r['error_rate']:.2%} | {'PASS' if r['slo']['passed'] else 'FAIL'} |")
    tail = []
    for rate in ('0', '0.03', '0.1'):
        l = read(f'load_v2_slow_{rate}.json')['latency_ms']
        tail.append(f"| {rate} | {l['avg']} | {l['p95']} | {l['p99']} |")
    evaluations = [read(f'eval_{v}.json') for v in ('v1','v2','v2_fixed')]
    def erow(label, values):
        return '| '+label+' | '+' | '.join(map(str,values))+' |'
    quality = [erow('Accuracy', [f"{e['passed']}/{e['total']} ({e['accuracy']:.2%})" for e in evaluations]),
               erow('Avg tokens / question',[e['avg_tokens'] for e in evaluations]),
               erow('Total cost (USD)',[e['total_cost_usd'] for e in evaluations]),
               erow('Cost / correct answer (USD)',[e['cost_per_correct_usd'] for e in evaluations]),
               erow('Quality gate (100%)',['PASS' if e['quality_gate']['passed'] else 'FAIL' for e in evaluations])]
    scaling=[]
    for count in (1,3):
        path=ROOT / f'benchmark-results/scale_{count}_stats.csv'
        if path.exists():
            with path.open() as stream:
                stats=next(row for row in csv.DictReader(stream) if row['Name']=='Aggregated')
            scaling.append(erow(str(count),[stats['Requests/s'],stats['50%'],stats['95%'],stats['99%'],stats['Failure Count']]))
    chaos='Pending: observability stack evidence collection is still in progress.'
    timeline=REPORTS / 'alert-timeline.json'
    if timeline.exists():
        data=read(timeline.name)
        chaos='Injected `MOCK_ERROR_RATE=0.2` (experiment A) and `MOCK_SLOW_RATE=0.3` (experiment B) together, preserving all alert thresholds and hold times. Detection time includes container recreation and Prometheus observation, measured from the start of the change.\n\n'
        chaos+='| Change | Alert | Time to first firing (s) | Panel |\n|---|---|---:|---|\n'
        for label,alert,panel in [('A: error rate 20%','AgentHighErrorRate','Errors'),('B: slow rate 30%','AgentHighLatencyP95','Latency p95')]:
            chaos+=f"| {label} | {alert} | {data['first_firing_seconds'].get(alert,'Not observed')} | {panel} |\n"
        chaos+='\nRaw polling timeline: [alert-timeline.json](reports/alert-timeline.json). Experiments C (large model), D (paused instance) and E (v1) were not run as separate chaos experiments; no detection times are claimed for them.'
    tracing='Pending: trace and matching JSON log collection.'
    summary=REPORTS / 'trace-summary.json'
    if summary.exists():
        data=read(summary.name); slow=data['slow']; err=data['error']
        tracing=f"Slow trace `{slow['trace_id']}`: {slow['duration_ms']:.3f} ms total; `{slow['llm_span']}` takes {slow['llm_duration_ms']:.3f} ms ({slow['llm_duration_ms']/slow['duration_ms']:.1%}). The LLM span dominates the request, consistent with the injected upstream delay.\n\nError trace `{err['trace_id']}` contains a recorded `exception` event. Raw spans and matching JSON logs are saved in `reports/jaeger-*-trace.json` and `reports/jaeger-*-logs.json`.\n\nMatching slow-trace log:\n\n```json\n"+json.dumps(slow['log'],ensure_ascii=False)+'\n```'
    panels='Pending live Prometheus baseline query.'
    baseline=REPORTS / 'prometheus-baseline.json'
    if baseline.exists():
        data=read(baseline.name)
        def val(key):
            result=data[key]['data']['result']
            return float(result[0]['value'][1]) if result else None
        panels=f"Prometheus snapshot after the scale-3 run: p95 {val('p95_seconds')*1000:.1f} ms; average {val('average_seconds')*1000:.1f} ms. Histogram p95 is estimated from buckets; Locust computes percentiles from its own request samples. They need not match exactly.\n\nRequest rates by target from the same snapshot: "+'; '.join(f"`{r['metric']['instance']}`: {float(r['value'][1]):.2f} requests/s" for r in data['rps_by_instance']['data']['result'])+'. The target rates indicate how Nginx shares traffic; a short run with random delays will not be perfectly equal.'
    text=f'''# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyen Nam Khanh  
**Ngày chạy:** 25 November 2026 (GMT+7)  
**Environment:** {env['host']}; {env['logical_cpus']} logical host CPUs; Python {env['python']}. Docker Desktop was allocated 6 CPUs and 4,112,519,168 bytes of RAM; source: `reports/docker-environment.json`.

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
{chr(10).join(rows)}

Source: `reports/load_v2_c{{1,10,50,100}}.json`. Throughput did not scale linearly: it rose to concurrency 50 then declined at 100, while p95 rose sharply. Queueing, event-loop/client work and host contention contribute; these measurements do not identify one bottleneck conclusively. Failed SLO gates were retained as evidence.

### 2.2 Tail latency (concurrency 20)

| MOCK_SLOW_RATE | Average ms | p95 ms | p99 ms |
|---|---:|---:|---:|
{chr(10).join(tail)}

Source: `reports/load_v2_slow_*.json`. At a 10% slow rate, more than 5% of requests fall in the slow population, moving p95 sharply. Average dilutes that population; high percentiles reveal it. With only 300 unseeded requests, the realized slow fraction varies, so percentile changes need not be monotonic across every run. Use p95/p99 and error rate alongside the mean.

## 3. Quality

Evaluations disable random upstream errors/slow injection to isolate answer quality. The original 23-question dataset and eval script were unchanged. Gate threshold is 100% for all three recorded evaluations; the final run also compares with the original v2 baseline.

| Metric | v1 | v2 original | v2 fixed |
|---|---:|---:|---:|
{chr(10).join(quality)}

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

{panels}

Input prompts include system instructions, retrieved context and the user question. The relative input/output rate depends on the sampled questions and answer lengths; retrieval does not guarantee input exceeds output. The dashboard and token counters provide the measured comparison. The Nginx ingress returns 404 for `/metrics` while Prometheus scrapes agent instances directly over the internal network; see `reports/metrics-ingress.json`.

Metric examples: `http_requests_total` (Counter), `agent_in_flight_requests` (Gauge), `http_request_duration_seconds` (Histogram). Added `agent_question_length_chars` with bounded character buckets. Route labels use matched route templates or `unmatched`; raw bot-generated paths would create unbounded time series and exhaust memory. Request IDs belong in logs/traces, not metric labels.

### 4.2 Fault injection and alerts

{chaos}

Changing to v1 can lower answer accuracy without increasing HTTP failures or latency. Detect that with golden-dataset canaries, scheduled production evals, labeled quality samples and an accuracy/regression alert. Infrastructure golden signals alone do not measure correctness.

### 4.3 Trace debugging

{tracing}

## 5. Scaling — Locust headless

Each recorded scaling run uses 100 users, spawn rate 10/s, 2 minutes, supplied user think time and the same model/fault defaults. The aggregate includes `/ask` and `/health`; detailed per-route rows remain in CSV.

| Instances | RPS | p50 ms | p95 ms | p99 ms | Failures |
|---|---:|---:|---:|---:|---:|
{chr(10).join(scaling) if scaling else '| Pending | — | — | — | — | — |'}

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
'''
    (ROOT / 'BENCHMARK_REPORT.md').write_text(text)


if __name__ == '__main__':
    main()
