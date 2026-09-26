// `npm run start`: start the Python backend and Vite together. A backend already on the port is stopped
// and replaced so it always runs the current code. Ctrl+C stops both.
// BIM_PYTHON picks an interpreter (e.g. a venv); BIM_NO_BACKEND=1 skips the backend; BIM_REUSE_BACKEND=1 keeps a running one.
import { execSync, spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = join(root, "..", "backend");
const backendUrl = process.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8765";
const children = [];

async function backendAlive() {
  try {
    const r = await fetch(`${backendUrl}/health`, { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch {
    return false;
  }
}

function killBackend() {
  const port = new URL(backendUrl).port || "8765";
  try {
    if (process.platform === "win32") {
      const out = execSync(`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue).OwningProcess"`).toString();
      for (const pid of new Set(out.split(/\s+/).filter((s) => /^\d+$/.test(s)))) {
        execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
        console.log(`[backend] stopped previous backend (pid ${pid})`);
      }
    } else {
      execSync(`lsof -ti tcp:${port} | xargs -r kill`, { stdio: "ignore" });
      console.log("[backend] stopped previous backend");
    }
  } catch (err) {
    console.log(`[backend] could not stop the previous backend: ${err.message}`);
  }
}

function run(name, cmd, args, cwd) {
  const child = spawn(cmd, args, { cwd, stdio: "inherit", shell: process.platform === "win32" });
  child.on("exit", (code) => {
    console.log(`[${name}] exited (${code})`);
    if (name === "backend" && code !== 0 && code !== null) {
      console.log(`[backend] failed to start — run "python main.py" in backend/ to see the error, and check backend/.env`);
    }
  });
  children.push(child);
  return child;
}

if (process.env.BIM_NO_BACKEND) {
  console.log("[backend] skipped (BIM_NO_BACKEND)");
} else if (process.env.BIM_REUSE_BACKEND && (await backendAlive())) {
  console.log(`[backend] already running at ${backendUrl}, reusing it (BIM_REUSE_BACKEND)`);
} else {
  if (await backendAlive()) killBackend();
  console.log(`[backend] starting python main.py in ${backendDir}`);
  run("backend", process.env.BIM_PYTHON ?? "python", ["main.py"], backendDir);
}

run("vite", "npx", ["vite"], root);

const stop = () => {
  for (const c of children) c.kill();
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
