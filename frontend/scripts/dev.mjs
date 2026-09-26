// `npm run dev`: start Vite, then launch Electron pointed at it.
import { spawn } from "node:child_process";
import { createServer } from "vite";
import electron from "electron";

const server = await createServer({ configFile: "vite.config.ts" });
await server.listen();
const url = server.resolvedUrls.local[0];
console.log(`vite ready at ${url}`);

const app = spawn(electron, ["."], {
  stdio: "inherit",
  env: { ...process.env, VITE_DEV_SERVER_URL: url },
});
app.on("exit", async (code) => {
  await server.close();
  process.exit(code ?? 0);
});
