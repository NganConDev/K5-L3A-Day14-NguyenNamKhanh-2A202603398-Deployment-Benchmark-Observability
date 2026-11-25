"""Collect real Locust, Prometheus, Jaeger and browser evidence for CP8.

Run after starting the production observability stack; keeps services running
until evidence is captured. Does not change alert thresholds or hold times.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "06-lab-complete/benchmark-observability/production"
REPORTS = ROOT / "reports"
COMPOSE = ["docker", "compose", "-p", "k5-day14-observability", "-f", str(STACK / "docker-compose.yml")]


def api(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def save(name, value):
    (REPORTS / name).write_text(json.dumps(value, indent=2, ensure_ascii=False))


def command(args, name, env=None, background=False):
    log = (REPORTS / f"{name}.log").open("w")
    print(name, flush=True)
    proc = subprocess.Popen(args, cwd=STACK, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    if background:
        return proc
    code = proc.wait()
    if code:
        raise RuntimeError(f"{name}: exit {code}; see reports/{name}.log")


def locust(name, duration="2m"):
    return command(COMPOSE + ["run", "--rm", "--no-deps", "-T", "locust", "-f", "/mnt/locust/locustfile.py",
        "--host", "http://nginx", "--headless", "-u", "100", "-r", "10", "-t", duration,
        "--csv", f"/mnt/results/{name}"], name, background=True)


def wait_agents(count):
    """Confirm healthy replicas before measuring, including Docker DNS refresh."""
    for _ in range(60):
        output = subprocess.check_output(COMPOSE + ["ps", "--format", "json", "agent"], text=True)
        try:
            parsed = json.loads(output)
            containers = parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            containers = [json.loads(line) for line in output.splitlines() if line.strip()]
        if len(containers) == count and all(c.get("Health") == "healthy" for c in containers):
            time.sleep(12)  # Nginx re-resolves Docker DNS every ten seconds.
            save(f"scale_{count}-containers.json", containers)
            return
        time.sleep(2)
    raise RuntimeError(f"Expected {count} healthy agents before load test")


def wait_job(proc, name):
    while proc.poll() is None:
        print(name, "still running", flush=True)
        time.sleep(10)
    # Locust returns 1 if the injected/mock upstream produced any failures.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"{name} failed: {proc.returncode}")
    files = list((STACK / "benchmark-results").glob(name + "*.csv"))
    if not files:
        raise RuntimeError(f"{name} produced no CSV")
    for source in files:
        shutil.copy2(source, ROOT / "benchmark-results" / source.name)


def screenshot(page, url, filename):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000 if "3000" in url else 6000)
    # Dismiss consent dialogs if the installed dashboard version has one.
    for label in ("Accept all", "Accept", "Got it"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count() and button.first.is_visible():
            button.first.click()
    page.screenshot(path=str(ROOT / "screenshots" / filename), full_page=True)


def trace_evidence(page):
    # Jaeger v2.23 serves the v3 OTLP API as newline-delimited JSON.
    now = datetime.now(timezone.utc)
    params = urllib.parse.urlencode({
        "query.service_name": "observable-agent", "query.num_traces": 100,
        "query.start_time_min": datetime.fromtimestamp(time.time()-3600, timezone.utc).isoformat(),
        "query.start_time_max": now.isoformat(),
    })
    with urllib.request.urlopen("http://localhost:16686/api/v3/traces?"+params, timeout=30) as response:
        payload = response.read().decode()
    by_trace = {}
    for line in payload.splitlines():
        for resource in json.loads(line).get("result", {}).get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for raw in scope.get("spans", []):
                    span = {**raw, "operationName":raw["name"], "duration":
                            (int(raw["endTimeUnixNano"])-int(raw["startTimeUnixNano"]))/1000}
                    by_trace.setdefault(raw["traceId"],[]).append(span)
    traces = [{"traceID":trace_id,"spans":spans} for trace_id,spans in by_trace.items()]
    def duration(trace):
        return max(s["duration"] for s in trace["spans"])
    errors = [t for t in traces if any(event.get("name") == "exception"
        for span in t["spans"] for event in span.get("events", []))]
    if not errors:
        raise RuntimeError("No trace with an exception event found")
    chosen = {"slow": max(traces, key=duration), "error": max(errors, key=duration)}
    logs = subprocess.check_output(COMPOSE + ["logs", "--no-color", "agent"], text=True)
    summary = {}
    for kind, trace in chosen.items():
        trace_id = trace["traceID"]
        save(f"jaeger-{kind}-trace.json", trace)
        matched = []
        for line in logs.splitlines():
            start = line.find('{')
            if start >= 0:
                try:
                    entry = json.loads(line[start:])
                except ValueError:
                    continue
                if entry.get("trace_id") == trace_id:
                    matched.append(entry)
        if not matched:
            raise RuntimeError("Trace has no matching JSON log")
        save(f"jaeger-{kind}-logs.json", matched)
        spans = trace["spans"]
        llm = max((s for s in spans if s["operationName"].startswith("chat ")), key=lambda s:s["duration"])
        summary[kind] = {"trace_id": trace_id, "duration_ms": duration(trace)/1000,
                         "llm_span": llm["operationName"], "llm_duration_ms": llm["duration"]/1000,
                         "log": matched[0]}
        screenshot(page, f"http://localhost:16686/trace/{trace_id}", f"jaeger-{kind}-trace.png")
        # Open the LLM span detail so its timing/tags/exception are visible.
        span_label = page.get_by_text(llm["operationName"], exact=True)
        if span_label.count():
            span_label.first.click()
            page.wait_for_timeout(1000)
            if kind == "error":
                details = page.get_by_text("Details", exact=True)
                if details.count():
                    details.first.click()
                    page.wait_for_timeout(500)
                # Jaeger's GenAI view hides exception logs until Details is opened.
                for label in ("Logs", "Events"):
                    section = page.get_by_text(label, exact=True)
                    if section.count():
                        section.first.click()
                        page.wait_for_timeout(500)
            page.screenshot(path=str(ROOT / "screenshots" / f"jaeger-{kind}-trace.png"), full_page=True)
    save("trace-summary.json", summary)


def main():
    for port, path in [(8080,"/health"),(9090,"/-/ready"),(3000,"/api/health"),(16686,"/")]:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=2)
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError(f"Service {port} unavailable")

    command(["docker", "run", "--rm", "-v", f"{STACK / 'prometheus'}:/p", "--entrypoint", "promtool",
             "prom/prometheus:v3.16.0", "test", "rules", "/p/alert_rules_test.yml"], "alert-rule-tests")

    command(COMPOSE + ["up", "-d", "--scale", "agent=1"], "observability-scale1")
    wait_agents(1)
    wait_job(locust("scale_1"), "scale_1")
    command(COMPOSE + ["up", "-d", "--scale", "agent=3"], "observability-scale3")
    wait_agents(3)
    wait_job(locust("scale_3"), "scale_3")
    queries = {
        "rps": 'sum(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
        "rps_by_instance": 'sum by(instance)(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
        "p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job="agent",route="/ask"}[1m])))',
        "average_seconds": 'sum(rate(http_request_duration_seconds_sum{job="agent",route="/ask"}[1m]))/sum(rate(http_request_duration_seconds_count{job="agent",route="/ask"}[1m]))',
    }
    save("prometheus-baseline.json", {key:api("http://localhost:9090/api/v1/query?query="+urllib.parse.quote(query)) for key,query in queries.items()})
    try:
        urllib.request.urlopen("http://localhost:8080/metrics")
        raise RuntimeError("Metrics unexpectedly public")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        save("metrics-ingress.json", {"path":"/metrics", "status":exc.code})

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=True,
                                    args=["--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width":1600, "height":1600}, device_scale_factor=1)
        screenshot(page, "http://localhost:3000/d/day14-agent-overview?from=now-10m&to=now", "grafana-dashboard.png")

        # Experiments A and B share one controlled chaos interval, with default
        # model/version and original alert rules. Measure each alert separately.
        started = time.time()
        timeline = {"started_at":datetime.now(timezone.utc).isoformat(),
                    "settings":{"MOCK_ERROR_RATE":0.2,"MOCK_SLOW_RATE":0.3}, "first_firing_seconds":{}, "polls":[]}
        env = {**os.environ, "MOCK_ERROR_RATE":"0.2", "MOCK_SLOW_RATE":"0.3"}
        command(COMPOSE + ["up", "-d", "--scale", "agent=3", "--force-recreate", "agent"], "chaos-start", env=env)
        load = locust("chaos", "5m")
        try:
            deadline = time.time() + 285
            while time.time() < deadline:
                alerts = api("http://localhost:9090/api/v1/alerts")["data"]["alerts"]
                elapsed = round(time.time()-started, 2)
                snapshot = [{"name":a["labels"]["alertname"], "state":a["state"], "value":a["value"]} for a in alerts]
                timeline["polls"].append({"seconds":elapsed,"alerts":snapshot})
                for a in alerts:
                    if a["state"] == "firing":
                        timeline["first_firing_seconds"].setdefault(a["labels"]["alertname"],elapsed)
                save("alert-timeline.json", timeline)
                print("Alerts at", elapsed, snapshot, flush=True)
                firing = {a["labels"]["alertname"] for a in alerts if a["state"]=="firing"}
                if {"AgentHighErrorRate","AgentHighLatencyP95"} <= firing:
                    save("prometheus-alerts-firing.json", alerts)
                    screenshot(page,"http://localhost:9090/alerts","prometheus-alert-firing.png")
                    trace_evidence(page)
                    break
                time.sleep(5)
            else:
                raise RuntimeError("Both required alerts did not fire")
        finally:
            wait_job(load,"chaos")
            browser.close()
    print("Observability evidence complete", flush=True)


if __name__ == "__main__":
    main()
