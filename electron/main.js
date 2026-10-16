const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

// Chromium's SUID chrome-sandbox is usually unconfigured in an npm checkout.
if (process.platform === "linux") {
  app.commandLine.appendSwitch("no-sandbox");
}

let mainWindow = null;
let sidecar = null;
let buffer = "";
let nextId = 1;
const pending = new Map();
const timedOut = new Set();
// connect: reclaim (~16–32s) + 4×(drop_stale 6s + Bleak 20s + backoff) can exceed 130s.
const CONNECT_IPC_TIMEOUT_MS = 180000;
const SCAN_IPC_TIMEOUT_MS = 90000;
const DEFAULT_IPC_TIMEOUT_MS = 30000;

function sidecarPython() {
  const venv = path.join(__dirname, "..", "sidecar", ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python3";
}

function sendToSidecar(payload) {
  return new Promise((resolve, reject) => {
    if (!sidecar || !sidecar.stdin.writable) {
      reject(new Error("Sidecar is not running"));
      return;
    }
    const id = nextId;
    nextId += 1;
    pending.set(id, { resolve, reject, cmd: payload.cmd });
    sidecar.stdin.write(`${JSON.stringify({ id, ...payload })}\n`);
    const timeoutMs =
      payload.cmd === "connect"
        ? CONNECT_IPC_TIMEOUT_MS
        : payload.cmd === "scan"
          ? SCAN_IPC_TIMEOUT_MS
          : DEFAULT_IPC_TIMEOUT_MS;
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        timedOut.add(id);
        reject(new Error(`Sidecar timeout for ${payload.cmd}`));
      }
    }, timeoutMs);
  });
}

function emitToRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

function handleSidecarLine(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    emitToRenderer("sidecar:log", { level: "error", message: `Bad sidecar JSON: ${line}` });
    return;
  }
  if (message.id != null && pending.has(message.id)) {
    const { resolve } = pending.get(message.id);
    pending.delete(message.id);
    timedOut.delete(message.id);
    resolve(message);
    return;
  }
  if (message.id != null && timedOut.has(message.id)) {
    timedOut.delete(message.id);
    // Late connect success after IPC timeout: sync UI so GATT is not orphaned.
    if (message.ok && message.result && Object.hasOwn(message.result, "has_fff0")) {
      emitToRenderer("sidecar:status", {
        event: "status",
        connected: true,
        address: message.result.address ?? null,
        name: message.result.name ?? null,
      });
    }
    return;
  }
  if (message.event === "status") {
    emitToRenderer("sidecar:status", message);
  } else if (message.event === "packet") {
    emitToRenderer("sidecar:packet", message);
  } else if (message.event) {
    emitToRenderer("sidecar:event", message);
  }
}

function startSidecar() {
  const sidecarDir = path.join(__dirname, "..", "sidecar");
  sidecar = spawn(sidecarPython(), ["-m", "osmo_sidecar", "serve"], {
    cwd: sidecarDir,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: sidecarDir,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });

  sidecar.stdout.setEncoding("utf8");
  sidecar.stdout.on("data", (chunk) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) {
        handleSidecarLine(line.trim());
      }
    }
  });

  sidecar.stderr.setEncoding("utf8");
  sidecar.stderr.on("data", (chunk) => {
    emitToRenderer("sidecar:log", { level: "info", message: chunk.trim() });
  });

  sidecar.on("exit", (code) => {
    emitToRenderer("sidecar:log", {
      level: "error",
      message: `Sidecar exited (${code ?? "null"}). Run npm run sidecar:setup.`,
    });
    sidecar = null;
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 980,
    height: 760,
    minWidth: 800,
    minHeight: 640,
    backgroundColor: "#16181d",
    title: "Osmo Remote",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  mainWindow.setMenuBarVisibility(false);


  const startUrl = process.env.ELECTRON_START_URL;
  if (startUrl) {
    mainWindow.loadURL(startUrl);
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "renderer", "index.html"));
  }
}

ipcMain.handle("sidecar:request", async (_event, payload) => sendToSidecar(payload));

ipcMain.handle("window:alwaysOnTop", (_event, enabled) => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return false;
  }
  mainWindow.setAlwaysOnTop(Boolean(enabled), "floating");
  return mainWindow.isAlwaysOnTop();
});

ipcMain.handle("window:compact", (_event, enabled) => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return false;
  }
  if (enabled) {
    mainWindow.setMinimumSize(320, 460);
    mainWindow.setSize(380, 620);
  } else {
    mainWindow.setMinimumSize(640, 520);
    mainWindow.setSize(980, 760);
  }
  return Boolean(enabled);
});

app.whenReady().then(() => {
  startSidecar();
  createWindow();
});

async function stopSidecar() {
  const child = sidecar;
  if (!child) {
    return;
  }
  try {
    await sendToSidecar({ cmd: "shutdown" });
  } catch {
    // Sidecar may already be gone.
  }
  try {
    child.stdin.end();
  } catch {
    // ignore
  }
  child.kill("SIGTERM");
  sidecar = null;
}

app.on("window-all-closed", () => {
  stopSidecar().finally(() => {
    app.quit();
  });
});
