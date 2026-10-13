"""
SERAPHIM S02 — Python backend prototype (stdlib only, no external deps).

Endpoints:
  GET  /health        — health response, reads test config from --root
  GET  /config/check?path=... — file root confinement test
  POST /proc/spawn    — spawn child in Job Object with limits
  POST /proc/kill     — tree-kill by pid
  POST /shutdown      — graceful shutdown

Auth: X-Seraphim-Token header (value from --token or default "s02-test").
Binding: 127.0.0.1 only (loopback).
Port: written to --port-file so UI can discover it.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from procman import spawn_in_job, kill_tree

# ---------------------------------------------------------------------------
# Minimal YAML subset parser (2-level, key: value, quoted values)
# Only used for the prototype test config — NOT a production parser.
# ---------------------------------------------------------------------------
def parse_minimal_yaml(text):
    """Parse a tiny subset of YAML: top-level keys, nested by indentation."""
    result = {}
    current_key = None
    current_dict = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        if ':' not in stripped:
            continue
        key, _, val = stripped.partition(':')
        key = key.strip().strip('"').strip("'")
        val = val.strip().strip('"').strip("'")
        if indent == 0:
            current_key = key
            current_dict = val if val else {}
            result[key] = current_dict
        else:
            if isinstance(current_dict, dict):
                current_dict[key] = val
    return result


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------
def validate_token(handler):
    token = handler.headers.get('X-Seraphim-Token', '')
    if token != handler.server.auth_token:
        return False
    return True


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class SeraphimHandler(BaseHTTPRequestHandler):
    """Handles requests to the backend. No secrets in logs."""

    def log_message(self, fmt, *args):
        # Suppress verbose logging to avoid leaking anything sensitive
        pass

    def _send_json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    # GET /health
    def do_GET(self):
        if not validate_token(self):
            self._send_json(401, {
                "code": "AUTH_REQUIRED",
                "message_key": "errors.auth_required",
                "component": "core.http",
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return

        if self.path == '/health':
            self._handle_health()
        elif self.path.startswith('/config/check'):
            self._handle_config_check()
        else:
            self._send_json(404, {
                "code": "ENDPOINT_NOT_FOUND",
                "message_key": "errors.endpoint_not_found",
                "component": "core.http",
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })

    # POST
    def do_POST(self):
        if not validate_token(self):
            self._send_json(401, {
                "code": "AUTH_REQUIRED",
                "message_key": "errors.auth_required",
                "component": "core.http",
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return

        if self.path == '/proc/spawn':
            self._handle_proc_spawn()
        elif self.path == '/proc/kill':
            self._handle_proc_kill()
        elif self.path == '/shutdown':
            self._handle_shutdown()
        else:
            self._send_json(404, {
                "code": "ENDPOINT_NOT_FOUND",
                "message_key": "errors.endpoint_not_found",
                "component": "core.http",
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })

    # -----------------------------------------------------------------------
    # Handlers
    # -----------------------------------------------------------------------
    def _handle_health(self):
        start = time.time()
        config = self.server.config
        if config is None:
            self._send_json(500, {
                "code": "CONFIG_READ_ERROR",
                "message_key": "errors.config_read_error",
                "component": "core.config",
                "retryable": True,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return

        uptime = round(time.time() - self.server.start_time, 3)
        self._send_json(200, {
            "status": "ok",
            "service": config.get('health', {}).get('service', 'seraphim-core'),
            "version": config.get('seraphim', {}).get('version', '0.0.0'),
            "environment": config.get('seraphim', {}).get('environment', 'unknown'),
            "config": {
                "version": config.get('seraphim', {}).get('version', '0.0.0'),
                "environment": config.get('seraphim', {}).get('environment', 'unknown'),
                "digest": self.server.config_digest,
                "path": str(self.server.config_path)
            },
            "binding": f"127.0.0.1:{self.server.server_port}",
            "uptime_seconds": uptime,
            "timestamp": time.time()
        })

    def _handle_config_check(self):
        from urllib.parse import urlparse, unquote
        parsed = urlparse(self.path)
        unsafe_path = unquote(parsed.query.split('path=', 1)[1] if 'path=' in parsed.query else '')

        # Resolve within root, reject traversal
        target = self.server.root / unsafe_path
        resolved = target.resolve()

        blocked = False
        reason = None

        if not resolved.is_relative_to(self.server.root.resolve()):
            blocked = True
            reason = "path_traversal_outside_root"
        elif target.is_symlink():
            # Check if symlink target is outside root
            try:
                link_target = target.resolve()
                if not link_target.is_relative_to(self.server.root.resolve()):
                    blocked = True
                    reason = "symlink_outside_root"
            except Exception:
                blocked = True
                reason = "symlink_target_unresolvable"

        if blocked:
            self._send_json(403, {
                "code": "FILE_ROOT_BLOCKED",
                "message_key": "errors.file_root_blocked",
                "component": "core.filesystem",
                "blocked": True,
                "reason": reason,
                "requested_path": str(target),
                "resolved_path": str(resolved),
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return

        if not target.exists():
            self._send_json(404, {
                "code": "FILE_NOT_FOUND",
                "message_key": "errors.file_not_found",
                "component": "core.filesystem",
                "requested_path": str(target),
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return

        if target.is_file():
            data = target.read_bytes()
            self._send_json(200, {
                "exists": True,
                "path": str(target),
                "size": len(data),
                "content_type": "text/yaml",
                "content": data.decode('utf-8', errors='replace')
            })
        else:
            self._send_json(200, {
                "exists": True,
                "path": str(target),
                "is_directory": True
            })

    def _handle_proc_spawn(self):
        body = self._read_body()
        cmd = body.get('cmd', 'echo')
        args = body.get('args', [])
        timeout_ms = body.get('timeout_ms', 5000)

        try:
            proc = spawn_in_job(cmd, args, timeout_ms)
            self._send_json(200, {
                "code": "PROCESS_STARTED",
                "message_key": "proc.started",
                "pid": proc.pid,
                "status": "running",
                "job_id": proc.job_id
            })
        except Exception as e:
            self._send_json(500, {
                "code": "PROC_SPAWN_FAILED",
                "message_key": "errors.proc_spawn_failed",
                "component": "core.process",
                "error": str(e),
                "retryable": True,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })

    def _handle_proc_kill(self):
        body = self._read_body()
        pid = body.get('pid')
        if not pid:
            self._send_json(400, {
                "code": "MISSING_PID",
                "message_key": "errors.missing_pid",
                "component": "core.process",
                "retryable": False,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })
            return
        try:
            success = kill_tree(pid)
            self._send_json(200, {
                "code": "PROCESS_KILLED",
                "pid": pid,
                "killed": success
            })
        except Exception as e:
            self._send_json(500, {
                "code": "PROC_KILL_FAILED",
                "error": str(e),
                "retryable": True,
                "user_action_required": False,
                "details_ref": str(uuid.uuid4())
            })

    def _handle_shutdown(self):
        self._send_json(200, {"code": "SHUTDOWN_INITIATED"})
        # Schedule shutdown in a thread-safe way
        import threading
        threading.Thread(target=self.server.shutdown).start()


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------
def create_server(root, port_file, token, config_path):
    server = HTTPServer(('127.0.0.1', 0), SeraphimHandler)
    server.root = Path(root).resolve()
    server.auth_token = token
    server.start_time = time.time()

    # Read config — resolve relative to root (not CWD)
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = config_path.resolve()
    server.config_path = config_path
    try:
        text = config_path.read_text('utf-8')
        server.config = parse_minimal_yaml(text)
        server.config_digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    except Exception as e:
        server.config = None
        server.config_digest = f"ERROR: {e}"

    # Write port to file for UI discovery
    pfile = Path(port_file)
    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(str(server.server_port), 'utf-8')

    return server


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='SERAPHIM S02 backend prototype')
    parser.add_argument('--root', default='.', help='File root for config/test')
    parser.add_argument('--config', default='config/health.yaml', help='Config file path')
    parser.add_argument('--port-file', default='.s02-port', help='File to write port to')
    parser.add_argument('--token', default='s02-test', help='Auth token')
    args = parser.parse_args()

    server = create_server(args.root, args.port_file, args.token, args.config)
    port = server.server_port
    print(f'SERAPHIM backend listening on 127.0.0.1:{port}', flush=True)
    print(f'Config root: {server.root}', flush=True)
    print(f'Token: {args.token}', flush=True)
    print(f'Config: {server.config_path} (digest: {server.config_digest})', flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...', flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
