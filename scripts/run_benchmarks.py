"""Reproduce Part 7 local evidence without changing the eval or dataset."""
import argparse
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEVELOP = ROOT / "06-lab-complete/benchmark-observability/develop"
REPORTS = ROOT / "reports"


@contextlib.contextmanager
def agent(version="v2", **overrides):
    env = {**os.environ, "AGENT_VERSION": version, "PORT": "8002", **overrides}
    with (REPORTS / f"agent_{version}.log").open("a") as log:
        proc = subprocess.Popen([sys.executable, "app.py"], cwd=DEVELOP,
                                env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("Agent failed; inspect reports/agent_*.log")
                try:
                    urllib.request.urlopen("http://localhost:8002/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Agent startup timed out")
            yield
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def run(script, name, *args):
    cmd = [sys.executable, script, "--url", "http://localhost:8002", *args,
           "--out", str(REPORTS / f"{name}.json")]
    print("Running", name, flush=True)
    with (REPORTS / f"{name}.txt").open("w") as out:
        result = subprocess.run(cmd, cwd=DEVELOP, stdout=out, stderr=subprocess.STDOUT)
    # Exit 1 means SLO/quality gate failed, and is evidence to keep.
    if result.returncode not in (0, 1) or not (REPORTS / f"{name}.json").exists():
        raise RuntimeError(f"{name} failed to produce evidence")
    print(name, "exit", result.returncode, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "fixed", "load"])
    phase = parser.parse_args().phase
    REPORTS.mkdir(exist_ok=True)
    if phase == "baseline":
        for version in ("v1", "v2"):
            with agent(version, MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0"):
                run("eval/run_eval.py", f"eval_{version}", "--min-accuracy", "1.0")
    elif phase == "fixed":
        with agent(MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0"):
            run("eval/run_eval.py", "eval_v2_fixed", "--min-accuracy", "1.0",
                "--baseline", str(REPORTS / "eval_v2.json"))
    else:
        with agent(MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE="0.03"):
            for concurrency in (1, 10, 50, 100):
                run("load_test.py", f"load_v2_c{concurrency}", "--requests", "300",
                    "--concurrency", str(concurrency))
            (REPORTS / "metrics-local.prom").write_bytes(
                urllib.request.urlopen("http://localhost:8002/metrics").read())
        for slow in ("0", "0.03", "0.1"):
            with agent(MOCK_SLOW_RATE=slow, MOCK_ERROR_RATE="0.01"):
                run("load_test.py", f"load_v2_slow_{slow}", "--requests", "300", "--concurrency", "20")


if __name__ == "__main__":
    main()
