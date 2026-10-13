#!/usr/bin/env node
/**
 * SERAPHIM S02 — Node.js backend prototype (stdlib only, no npm deps).
 *
 * Same endpoints as Python backend for direct comparison:
 *   GET  /health        — health, reads test config from --root
 *   GET  /config/check?path=... — file root confinement test
 *   POST /proc/spawn    — spawn child with limits
 *   POST /proc/kill     — tree-kill by pid
 *   POST /shutdown      — graceful shutdown
 *
 * Auth: X-Seraphim-Token header
 * Binding: 127.0.0.1 only
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { URL } = require("url");

// ---------------------------------------------------------------------------
// Minimal config
// ---------------------------------------------------------------------------
const DEFAULT_PORT = 1422;
const DEFAULT_TOKEN = "s02-test";
const DEFAULT_ROOT = ".";

// Parse CLI args manually (no external deps)
function parseArgs() {
  const args = process.argv.slice(2);
  const cfg = { port: DEFAULT_PORT, token: DEFAULT_TOKEN, root: DEFAULT_ROOT };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--port": cfg.port = parseInt(args[++i], 10); break;
      case "--root": cfg.root = args[++i]; break;
      case "--token": cfg.token = args[++i]; break;
      case "--config": cfg.configPath = args[++i]; break;
      case "--port-file": cfg.portFile = args[++i]; break;
    }
  }
  return cfg;
}

const cfg = parseArgs();
const root = path.resolve(cfg.root);
const configPath = cfg.configPath ? path.resolve(root, cfg.configPath) : path.resolve(root, "config/health.yaml");
let configData = null;
let configDigest = "";
let startTime = Date.now();

// ---------------------------------------------------------------------------
// Simple YAML subset parser
// ---------------------------------------------------------------------------
function parseMinimalYaml(text) {
  const result = {};
  let currentKey = null;
  let currentDict = null;
  for (const line of text.split("\n")) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith("#")) continue;
    const idx = stripped.indexOf(":");
    if (idx === -1) continue;
    const key = stripped.slice(0, idx).trim().replace(/^["']|["']$/g, "");
    const val = stripped.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
    if (line[0] !== " " && line[0] !== "\t") {
      currentKey = key;
      currentDict = val || {};
      result[key] = currentDict;
    } else if (currentDict && typeof currentDict === "object") {
      currentDict[key] = val;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
function validateToken(req) {
  return req.headers["x-seraphim-token"] === cfg.token;
}

// ---------------------------------------------------------------------------
// Response helpers
// ---------------------------------------------------------------------------
function sendJSON(res, code, body) {
  const data = JSON.stringify(body);
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(data),
  });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try { resolve(body ? JSON.parse(body) : {}); }
      catch (e) { reject(e); }
    });
    req.on("error", reject);
  });
}

// ---------------------------------------------------------------------------
// File root confinement
// ---------------------------------------------------------------------------
function resolveWithinRoot(unsafePath) {
  const resolved = path.resolve(root, unsafePath);
  if (!resolved.startsWith(root + path.sep) && resolved !== root) {
    return { blocked: true, reason: "path_traversal_outside_root", resolved };
  }
  // Check symlinks
  let current = path.dirname(resolved);
  while (current !== root && current.startsWith(root + path.sep)) {
    try {
      const link = fs.lstatSync(current);
      if (link.isSymbolicLink()) {
        const target = fs.readlinkSync(current);
        const absTarget = path.resolve(path.dirname(current), target);
        if (!absTarget.startsWith(root + path.sep)) {
          return { blocked: true, reason: "symlink_outside_root", resolved };
        }
      }
    } catch { /* ignore */ }
    current = path.dirname(current);
  }
  return { blocked: false, resolved };
}

// ---------------------------------------------------------------------------
// Subprocess with limits (Node approach)
// WARNING: Node stdlib has no Job Object API. This is weaker than Python's
// procman.py (ctypes-based Windows Job Object with KILL_ON_JOB_CLOSE).
// For production, use a native addon or spawn the sandbox in Python/Go.
// Parent death → children survive (no automatic cleanup).
// ---------------------------------------------------------------------------
function spawnChild(cmd, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      detached: false,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });

    const timer = setTimeout(() => {
      try { proc.kill("SIGTERM"); } catch {}
      reject(new Error("timeout"));
    }, timeoutMs);

    proc.on("exit", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout: proc.stdout?.read?.() || "", stderr: proc.stderr?.read?.() || "" });
    });

    proc.on("error", (err) => reject(err));
  });
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${cfg.port}`);
  const method = req.method;

  // Auth check
  if (!validateToken(req)) {
    return sendJSON(res, 401, {
      code: "AUTH_REQUIRED",
      message_key: "errors.auth_required",
      component: "core.http",
      retryable: false,
      user_action_required: false,
      details_ref: require("crypto").randomUUID(),
    });
  }

  // Routing
  if (method === "GET" && url.pathname === "/health") {
    const uptime = ((Date.now() - startTime) / 1000).toFixed(3);
    return sendJSON(res, 200, {
      status: "ok",
      service: (configData?.health?.service) || "seraphim-core",
      version: (configData?.seraphim?.version) || "0.0.0",
      environment: (configData?.seraphim?.environment) || "unknown",
      config: {
        version: (configData?.seraphim?.version) || "0.0.0",
        environment: (configData?.seraphim?.environment) || "unknown",
        digest: configDigest,
        path: configPath,
      },
      binding: `127.0.0.1:${cfg.port}`,
      uptime_seconds: uptime,
      timestamp: Date.now() / 1000,
    });
  }

  if (method === "GET" && url.pathname === "/config/check") {
    const unsafePath = url.searchParams.get("path") || "";
    const { blocked, reason, resolved } = resolveWithinRoot(unsafePath);

    if (blocked) {
      return sendJSON(res, 403, {
        code: "FILE_ROOT_BLOCKED",
        message_key: "errors.file_root_blocked",
        component: "core.filesystem",
        blocked: true,
        reason,
        requested_path: unsafePath,
        resolved_path: resolved,
        retryable: false,
        user_action_required: false,
        details_ref: require("crypto").randomUUID(),
      });
    }

    try {
      const stat = fs.statSync(resolved);
      if (stat.isFile()) {
        const content = fs.readFileSync(resolved, "utf-8");
        return sendJSON(res, 200, { exists: true, path: resolved, size: stat.size, content_type: "text/yaml", content });
      } else {
        return sendJSON(res, 200, { exists: true, path: resolved, is_directory: true });
      }
    } catch (err) {
      return sendJSON(res, 404, {
        code: "FILE_NOT_FOUND",
        message_key: "errors.file_not_found",
        component: "core.filesystem",
        requested_path: resolved,
        retryable: false,
        user_action_required: false,
        details_ref: require("crypto").randomUUID(),
      });
    }
  }

  if (method === "POST" && url.pathname === "/proc/spawn") {
    let body;
    try { body = JSON.parse(await readBody(req)); } catch { return sendJSON(res, 400, { code: "BAD_JSON" }); }
    const { cmd, args = [], timeout_ms = 5000 } = body;
    try {
      const result = await spawnChild(cmd, args, timeout_ms);
      return sendJSON(res, 200, {
        code: "PROCESS_STARTED",
        message_key: "proc.started",
        status: "completed",
        exit_code: result.code,
        output: result.stdout?.toString() || "",
      });
    } catch (err) {
      return sendJSON(res, 500, {
        code: "PROC_SPAWN_FAILED",
        message_key: "errors.proc_spawn_failed",
        component: "core.process",
        error: err.message,
        retryable: true,
        user_action_required: false,
        details_ref: require("crypto").randomUUID(),
      });
    }
  }

  if (method === "POST" && url.pathname === "/shutdown") {
    sendJSON(res, 200, { code: "SHUTDOWN_INITIATED" });
    setTimeout(() => server.close(), 100);
    return;
  }

  sendJSON(res, 404, {
    code: "ENDPOINT_NOT_FOUND",
    message_key: "errors.endpoint_not_found",
    component: "core.http",
    retryable: false,
    user_action_required: false,
    details_ref: require("crypto").randomUUID(),
  });
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
// Read config
try {
  const text = fs.readFileSync(configPath, "utf-8");
  configData = parseMinimalYaml(text);
  configDigest = require("crypto").createHash("sha256").update(text).digest("hex").slice(0, 16);
} catch (err) {
  configDigest = `ERROR: ${err.message}`;
}

server.listen(cfg.port, "127.0.0.1", () => {
  console.log(`SERAPHIM backend (Node) listening on 127.0.0.1:${cfg.port}`);
  console.log(`Config root: ${root}`);
  console.log(`Token: ${cfg.token}`);
  console.log(`Config: ${configPath} (digest: ${configDigest})`);

  // Write port file
  if (cfg.portFile) {
    fs.mkdirSync(path.dirname(cfg.portFile), { recursive: true });
    fs.writeFileSync(cfg.portFile, String(cfg.port), "utf-8");
  }
});
