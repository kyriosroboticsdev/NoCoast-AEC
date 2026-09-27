// `npm run start`: start the Python backend (unless one already answers on its port) and Vite together.
// Ctrl+C stops both. Set BIM_PYTHON to pick an interpreter (e.g. a venv), BIM_NO_BACKEND=1 to skip it.
import { spawn } from "node:child_process";
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
} else if (await backendAlive()) {
  console.log(`[backend] already running at ${backendUrl}, reusing it`);
} else {
  console.log(`[backend] starting python main.py in ${backendDir}`);
  run("backend", process.env.BIM_PYTHON ?? "python", ["main.py"], backendDir);
}

run("vite", "npm", ["run", "vite:dev"], root);

const stop = () => {
  for (const c of children) c.kill();
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
