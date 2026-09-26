// Electron main process: window, app:// protocol for the built UI, file dialogs,
// and (optionally) launching the Python backend.
const { app, BrowserWindow, dialog, ipcMain, net, protocol } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const DEV_URL = process.env.VITE_DEV_SERVER_URL; // set by `npm run dev`
const BACKEND_URL = process.env.BIM_BACKEND_URL || "http://127.0.0.1:8765";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");
const DIST_DIR = path.resolve(__dirname, "..", "dist");
const SMOKE_PNG = process.env.BIM_SMOKE; // screenshot path: load, capture, quit

// fetch(), WASM streaming and module workers need a real origin, not file://.
protocol.registerSchemesAsPrivileged([
  { scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } },
]);

let backend = null;

async function backendAlive() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(800) });
    return res.ok;
  } catch {
    return false;
  }
}

async function startBackend() {
  if (process.env.BIM_NO_BACKEND || (await backendAlive())) return;
  const venvPython = path.join(BACKEND_DIR, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python = fs.existsSync(venvPython) ? venvPython : "python";
  backend = spawn(python, ["main.py"], { cwd: BACKEND_DIR, stdio: "inherit", windowsHide: true });
  backend.on("exit", (code) => {
    console.log(`[backend] exited (${code})`);
    backend = null;
  });
}

function rendererQuery() {
  // Smoke-test hooks, forwarded to the renderer as query params.
  const q = new URLSearchParams();
  if (process.env.BIM_AUTOLOAD) q.set("autoload", process.env.BIM_AUTOLOAD);
  if (process.env.BIM_PROMPT) q.set("prompt", process.env.BIM_PROMPT);
  const s = q.toString();
  return s ? `?${s}` : "";
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1500,
    height: 920,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: "#0f1115",
    title: "Generative BIM",
    show: !SMOKE_PNG,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setMenuBarVisibility(false);

  if (DEV_URL) await win.loadURL(DEV_URL + rendererQuery());
  else await win.loadURL("app://bundle/index.html" + rendererQuery());

  if (SMOKE_PNG) runSmoke(win);
}

async function runSmoke(win) {
  const deadline = Date.now() + 120_000;
  let state = null;
  while (Date.now() < deadline) {
    state = await win.webContents.executeJavaScript("window.__bim && JSON.stringify(window.__bim)").catch(() => null);
    const parsed = state && JSON.parse(state);
    if (parsed && (parsed.status === "ready" || parsed.status === "error")) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  await new Promise((r) => setTimeout(r, 1500)); // let the last frames render
  const image = await win.webContents.capturePage();
  fs.writeFileSync(SMOKE_PNG, image.toPNG());
  console.log(`[smoke] state=${state}`);
  console.log(`[smoke] screenshot -> ${SMOKE_PNG}`);
  app.quit();
}

ipcMain.handle("ifc:open", async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    title: "Open IFC",
    filters: [{ name: "IFC", extensions: ["ifc"] }],
    properties: ["openFile"],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const file = result.filePaths[0];
  return { name: path.basename(file), data: fs.readFileSync(file) };
});

ipcMain.handle("ifc:save", async (event, { name, data }) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showSaveDialog(win, {
    title: "Save IFC",
    defaultPath: name,
    filters: [{ name: "IFC", extensions: ["ifc"] }],
  });
  if (result.canceled || !result.filePath) return null;
  fs.writeFileSync(result.filePath, Buffer.from(data));
  return result.filePath;
});

app.whenReady().then(async () => {
  protocol.handle("app", (request) => {
    const { pathname } = new URL(request.url);
    const file = path.normalize(path.join(DIST_DIR, decodeURIComponent(pathname)));
    if (!file.startsWith(DIST_DIR)) return new Response("forbidden", { status: 403 });
    return net.fetch(pathToFileURL(file).toString());
  });
  await startBackend();
  await createWindow();
  app.on("activate", () => BrowserWindow.getAllWindows().length === 0 && createWindow());
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("will-quit", () => {
  if (backend) backend.kill();
});
