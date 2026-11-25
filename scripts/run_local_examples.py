"""Run Parts 1/4/5 on free local ports and save sanitized HTTP evidence."""
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def server(folder, **overrides):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
            "--port", str(port), "--no-access-log",
        ], cwd=ROOT / folder, env={**os.environ, **overrides}, stdout=log, stderr=log)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                if proc.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read().decode())
                try:
                    urllib.request.urlopen(url + "/openapi.json", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Agent did not start")
            yield url
        finally:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def request(url, path, body=None, headers=None):
    req = urllib.request.Request(url + path, headers={
        "Content-Type": "application/json", **(headers or {}),
    }, data=json.dumps(body).encode() if body is not None else None)
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    return response.status, dict(response.headers), json.loads(response.read())


def evidence(label, result):
    status, headers, body = result
    print(f"\n{label}\nHTTP/1.1 {status}")
    for key, value in headers.items():
        if key.lower() in {"content-type", "retry-after", "x-ratelimit-remaining"}:
            print(f"{key}: {value}")
    print(json.dumps(body, ensure_ascii=False))


def main():
    with server("01-localhost-vs-production/develop") as url:
        evidence("Part 1 develop: POST /ask?question=Hello",
                 request(url, "/ask?question=Hello", {}))
        evidence("Part 1 develop: POST /ask with JSON (expected 422)",
                 request(url, "/ask", {"question": "Hello"}))
    with server("01-localhost-vs-production/production") as url:
        evidence("Part 1 production: GET /health", request(url, "/health"))
        evidence("Part 1 production: GET /ready", request(url, "/ready"))
        evidence("Part 1 production: POST /ask", request(url, "/ask", {"question": "Docker"}))
    key = secrets.token_urlsafe(32)
    with server("04-api-gateway/develop", AGENT_API_KEY=key) as url:
        evidence("Part 4 API key: missing key", request(url, "/ask", {"question": "hello"}))
        evidence("Part 4 API key: correct key (redacted)", request(
            url, "/ask", {"question": "hello"}, {"X-API-Key": key}))
    with server("04-api-gateway/production", JWT_SECRET=secrets.token_urlsafe(32)) as url:
        evidence("Part 4 JWT: missing token", request(url, "/ask", {"question": "hello"}))
        status, _, login = request(url, "/auth/token", {"username": "student", "password": "demo123"})
        assert status == 200
        print("\nPOST /auth/token: HTTP 200; access_token=[REDACTED]")
        headers = {"Authorization": "Bearer " + login["access_token"]}
        codes = []
        for i in range(12):
            result = request(url, "/ask", {"question": "What is Docker?"}, headers)
            codes.append(result[0])
            if i in (0, 10):
                evidence(f"Part 4 JWT request {i+1}: token redacted", result)
        print("Rate-limit loop status codes:", codes)
        assert codes == [200] * 10 + [429] * 2
    with server("05-scaling-reliability/develop") as url:
        evidence("Part 5 develop: GET /health", request(url, "/health"))
        evidence("Part 5 develop: GET /ready", request(url, "/ready"))
    print("\nAll local example checks passed.")


if __name__ == "__main__":
    main()
