// SERAPHIM S02 — Electron main process
// Spawns the Python backend, opens webview, measures round-trip.
const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const fs = require("fs");

const PORT_FILE = path.join(__dirname, "..", "backend-py", ".s02-port");
const PORT_DEFAULT = 1421;
const PROTOTYPE_ROOT = path.join(__dirname, "..", "shared", "testroot");

let mainWindow;
let backendProc = null;
let backendPort = PORT_DEFAULT;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    minWidth: 600,
    minHeight: 400,
    frame: false,
    title: "SERAPHIM S02 Prototype — Electron",
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });

  mainWindow.loadFile(path.join(PROTOTYPE_ROOT, "index.html"));

  // Expose port to renderer via IPC
  ipcMain.on("get-port", (evt) => {
    evt.reply("port", String(backendPort));
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function startBackend() {
  return new Promise((resolve, reject) => {
    console.log("Starting Python backend...");
    backendProc = spawn(
      "python",
      [
        "server.py",
        "--root",
        PROTOTYPE_ROOT,
        "--config",
        "config/health.yaml",
        "--port-file",
        PORT_FILE,
        "--token",
        "s02-test",
      ],
      {
        cwd: path.join(__dirname, "..", "backend-py"),
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      }
    );

    backendProc.stdout.on("data", (data) => {
      const txt = data.toString().trim();
      console.log(`[backend] ${txt}`);
      // Parse port from output
      const m = txt.match(/127\.0\.0\.1:(\d+)/);
      if (m) {
        backendPort = parseInt(m[1], 10);
      }
    });

    backendProc.stderr.on("data", (data) => {
      console.error(`[backend err] ${data.toString().trim()}`);
    });

    backendProc.on("error", (err) => {
      console.error(`Backend failed to start: ${err.message}`);
      reject(err);
    });

    backendProc.on("exit", (code) => {
      if (code !== 0) {
        console.error(`Backend exited with code ${code}`);
      }
    });

    // Wait for port file to appear
    let attempts = 0;
    const interval = setInterval(() => {
      attempts++;
      if (attempts > 60) {
        clearInterval(interval);
        reject(new Error("Backend did not start within 30s"));
        return;
      }
      if (fs.existsSync(PORT_FILE)) {
        const p = fs.readFileSync(PORT_FILE, "utf-8").trim();
        backendPort = parseInt(p, 10);
        console.log(`Backend started on port ${backendPort}`);
        clearInterval(interval);
        resolve();
      }
    }, 500);
  });
}

async function main() {
  await app.whenReady();

  try {
    await startBackend();
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }

  createWindow();

  // Wait for window to load, then measure RTT
  mainWindow.webContents.on("did-finish-load", async () => {
    console.log("Window loaded, measuring RTT...");
    try {
      const t0 = Date.now();
      const resp = await fetch(`http://127.0.0.1:${backendPort}/health`, {
        headers: { "X-Seraphim-Token": "s02-test" },
      });
      const rtt = Date.now() - t0;
      const data = await resp.json();
      console.log(`[electron] RTT: ${rtt}ms, health: ${JSON.stringify(data).slice(0, 120)}`);
    } catch (e) {
      console.error(`[electron] RTT failed: ${e.message}`);
    }
  });
}

app.on("window-all-closed", () => {
  if (backendProc) backendProc.kill();
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

main().catch(console.error);
