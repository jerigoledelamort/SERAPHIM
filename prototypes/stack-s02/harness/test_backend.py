#!/usr/bin/env python3
"""
SERAPHIM S02 — Test harness for backend validation.
Tests all required checks: health, auth, file root, subprocess, loopback-only.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SERVER_URL = "http://127.0.0.1:{port}"
PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0
RESULTS = []
_args = None  # set in main()


def skip(name, detail=""):
    global SKIP_COUNT
    SKIP_COUNT += 1
    RESULTS.append({"name": name, "status": "SKIP", "detail": detail})
    print(f"  [SKIP] {name} {detail}")


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
    RESULTS.append({"name": name, "status": status, "detail": detail})
    print(f"  [{status}] {name} {detail}")


def fetch(path, port, token="s02-test", method="GET", body=None):
    url = SERVER_URL.format(port=port) + path
    headers = {"X-Seraphim-Token": token}
    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_health():
    code, data = fetch("/health", _args.port)
    check("health endpoint returns 200", code == 200, f"status={code}")
    check("health has service name", data.get("service") == "seraphim-core",
          f"service={data.get('service')}")
    check("health has config version", "version" in data.get("config", {}),
          f"config={json.dumps(data.get('config'))[:80]}")
    check("health has binding info", "127.0.0.1" in data.get("binding", ""),
          f"binding={data.get('binding')}")
    check("health has config digest", len(data.get("config", {}).get("digest", "")) == 16,
          f"digest={data.get('config', {}).get('digest')}")


def test_auth():
    code, data = fetch("/health", _args.port, token="")
    check("no token returns 401", code == 401, f"status={code}")
    check("401 has structured error code", data.get("code") == "AUTH_REQUIRED",
          f"code={data.get('code')}")


def test_config_read():
    code, data = fetch("/config/check?path=config/health.yaml", _args.port)
    check("config/read returns 200", code == 200, f"status={code}")
    check("config file exists", data.get("exists") is True, f"exists={data.get('exists')}")
    check("config has content", "content" in data, f"has_content={('content' in data)}")
    check("config content is YAML", "seraphim:" in data.get("content", ""),
          f"first_chars={data.get('content', '')[:20]}")


def test_path_traversal():
    code, data = fetch("/config/check?path=../health.yaml", _args.port)
    check("traversal ../ blocked", code == 403, f"status={code}")
    check("traversal reason documented", data.get("reason") == "path_traversal_outside_root",
          f"reason={data.get('reason')}")
    check("traversal has file_root_blocked code", data.get("code") == "FILE_ROOT_BLOCKED",
          f"code={data.get('code')}")


def test_absolute_path():
    code, data = fetch("/config/check?path=C:/Windows/win.ini", _args.port)
    check("absolute path outside root blocked", code == 403, f"status={code}")


def test_subprocess_spawn():
    code, data = fetch("/proc/spawn", _args.port, method="POST",
                         body=json.dumps({"cmd": "cmd", "args": ["/c", "echo", "hello"], "timeout_ms": 5000}))
    check("proc/spawn returns 200", code == 200, f"status={code}")
    check("proc/spawn has pid", isinstance(data.get("pid"), int) and data["pid"] > 0,
          f"pid={data.get('pid')}")
    check("proc/spawn has job_id", data.get("job_id", "").startswith("SERAPHIM-S02-Job-"),
          f"job={data.get('job_id')[:30]}")


def test_no_network_exposure():
    """Verify server only listens on 127.0.0.1, not on LAN IP."""
    code, data = fetch("/health", _args.port)
    if code != 200:
        check("network exposure check (health first)", False, "health failed")
        return

    # Find LAN IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "192.168.1.1"

    # Try connecting to LAN IP — should fail
    try:
        sock = socket.create_connection((lan_ip, _args.port), timeout=1)
        sock.close()
        check("LAN IP not accessible", False, f"connected to {lan_ip}:{_args.port}")
    except (ConnectionRefusedError, socket.timeout, OSError):
        check("LAN IP not accessible (bound 127.0.0.1 only)", True, f"lan={lan_ip}:{_args.port}")


def test_file_root_symlink():
    """Test that symlinks outside root are rejected."""
    root = Path(_args.root)
    # Create a symlink inside testroot pointing outside
    link = root / "link_to_root"
    target = root.parent.resolve()
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target, target_is_directory=True)
    except OSError as e:
        skip("symlink confinement (needs Create Symbolic Link privilege)", f"{e}")
        # Clean up
        try:
            if link.is_symlink():
                link.unlink()
        except Exception:
            pass
        return

    try:
        code, data = fetch("/config/check?path=link_to_root/../health.yaml", _args.port)
        check("symlink traversal blocked", code == 403, f"status={code} reason={data.get('reason')}")
    finally:
        try:
            link.unlink()
        except Exception:
            pass


def test_rtt():
    code, data = fetch("/health", _args.port)
    if code == 200:
        t0 = time.time()
        fetch("/health", _args.port)
        rtt = (time.time() - t0) * 1000
        check(f"RTT < 50ms", rtt < 50, f"rtt={rtt:.1f}ms")
    else:
        check("RTT measurement", False, "health failed")


def test_structured_errors():
    """Verify all error responses follow the CONTRACTS §7 envelope format."""
    # 404
    code, data = fetch("/nonexistent", _args.port)
    check("404 has error envelope", code == 404 and "code" in data and "message_key" in data,
          f"code={code}")
    # 401
    code, data = fetch("/health", _args.port, token="wrong")
    check("401 has error envelope", code == 401 and "code" in data and "message_key" in data,
          f"code={code}")
    # 403
    code, data = fetch("/config/check?path=../x", _args.port)
    check("403 has error envelope", code == 403 and "code" in data and "message_key" in data,
          f"code={code}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global PASS_COUNT, FAIL_COUNT, _args

    parser = argparse.ArgumentParser(description="S02 backend test harness")
    parser.add_argument("--port", required=True, help="Backend port")
    parser.add_argument("--root", required=True, help="Test root path")
    parser.add_argument("--json-out", default=None, help="Write results JSON to file")
    _args = parser.parse_args()

    print(f"SERAPHIM S02 Backend Test Harness")
    print(f"  Port: {_args.port}")
    print(f"  Root: {_args.root}")
    print()

    print("1. Health endpoint:")
    test_health()
    print()

    print("2. Auth:")
    test_auth()
    print()

    print("3. Config read from test root:")
    test_config_read()
    print()

    print("4. Path traversal:")
    test_path_traversal()
    test_absolute_path()
    test_file_root_symlink()
    print()

    print("5. Subprocess management:")
    test_subprocess_spawn()
    print()

    print("6. Network exposure:")
    test_no_network_exposure()
    print()

    print("7. Performance:")
    test_rtt()
    print()

    print("8. Error envelope format:")
    test_structured_errors()
    print()

    print(f"=== RESULTS: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL / {SKIP_COUNT} SKIP ===")

    if _args.json_out:
        results = {
            "pass": PASS_COUNT,
            "fail": FAIL_COUNT,
            "skip": SKIP_COUNT,
            "total": PASS_COUNT + FAIL_COUNT + SKIP_COUNT,
            "items": RESULTS,
        }
        with open(_args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results written to {_args.json_out}")

    sys.exit(1 if FAIL_COUNT > 0 else 0)


if __name__ == "__main__":
    main()
