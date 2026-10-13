#!/usr/bin/env python3
"""Quick test for Node backend on port 1422."""
import json, urllib.request, urllib.error

PORT = 1422
TOKEN = "s02-test"

def fetch(path, token=TOKEN):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, headers={"X-Seraphim-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# Health
code, d = fetch("/health")
print(f"Health: status={code} service={d.get('service')} version={d.get('version')} digest={d.get('config',{}).get('digest')}")

# Traversal
code, d = fetch("/config/check?path=../health.yaml")
print(f"Traversal: status={code} blocked={d.get('blocked')} reason={d.get('reason')}")

# Auth
code, d = fetch("/health", token="")
print(f"Auth: status={code} code={d.get('code')}")
