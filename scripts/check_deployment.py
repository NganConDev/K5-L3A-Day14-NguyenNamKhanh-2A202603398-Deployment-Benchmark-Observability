"""Verify the four CP6 HTTP contracts without printing credentials."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

base = os.environ.get('BASE', '').rstrip('/')
key = os.environ.get('AGENT_API_KEY', '')
if not base.startswith('https://') or not key:
    sys.exit('Set BASE=https://your-service and AGENT_API_KEY in your environment.')
checks = [('GET', '/health', None, False, 200), ('GET', '/ready', None, False, 200),
          ('POST', '/ask', {'question': 'Hello'}, False, 401),
          ('POST', '/ask', {'question': 'Hello'}, True, 200)]
failed = False


def curl_status(method, path, headers, body):
    # Some networks reset Python's TLS connections to Railway's edge. curl uses
    # the system TLS transport, and also keeps the private key off command lines.
    config = [f'url = {json.dumps(base + path)}', f'request = {json.dumps(method)}']
    config.extend('header = ' + json.dumps(f'{name}: {value}') for name, value in headers.items())
    if body is not None:
        config.append('data = ' + json.dumps(json.dumps(body)))
    result = subprocess.run([
        'curl', '--config', '-', '--silent', '--show-error', '--max-time', '30',
        '--retry', '3', '--retry-all-errors', '--retry-delay', '1',
        '--output', os.devnull, '--write-out', '%{http_code}',
    ], input='\n'.join(config) + '\n', text=True, capture_output=True)
    if result.returncode:
        print(method, path, f'curl transport error {result.returncode}')
        return None
    return int(result.stdout[-3:])


for method, path, body, authenticated, expected in checks:
    headers = {'Content-Type': 'application/json'}
    if authenticated:
        headers['X-API-Key'] = key
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body else None)
    status = curl_status(method, path, headers, body) if shutil.which('curl') else None
    for attempt in range(3) if not shutil.which('curl') else ():
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                status = response.status
            break
        except urllib.error.HTTPError as exc:
            status = exc.code
            break
        except OSError as exc:
            if attempt == 2:
                print(method, path, type(exc).__name__, str(exc))
            else:
                time.sleep(1)
    if status is None:
        failed = True
        continue
    print(method, path, '(authenticated)' if authenticated else '', status,
          'PASS' if status == expected else f'FAIL: expected {expected}')
    failed |= status != expected
sys.exit(int(failed))
