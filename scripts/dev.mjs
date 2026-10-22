// 웹(Next.js) + API(FastAPI) + 작업 워커를 한 번에 실행한다: npm run dev:all
// 포트 바꾸기: WEB_PORT=3001 API_PORT=8001 npm run dev:all
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const webPort = process.env.WEB_PORT || "3000";
const apiPort = process.env.API_PORT || "8000";

const venvPython = [join(backend, ".venv", "Scripts", "python.exe"), join(backend, ".venv", "bin", "python")].find(existsSync);
if (!venvPython) {
  console.warn("[dev] backend/.venv가 없어서 시스템 python을 씁니다. README의 백엔드 설치 단계를 먼저 진행하세요.");
}
const python = venvPython || "python";

const env = {
  ...process.env,
  BACKEND_URL: `http://127.0.0.1:${apiPort}`,
  PUBLIC_BASE_URL: process.env.PUBLIC_BASE_URL || `http://localhost:${webPort}`,
  PYTHONIOENCODING: "utf-8",
  PYTHONUNBUFFERED: "1",
};

const procs = [
  { name: "api", color: 36, cmd: python, args: ["-m", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--port", apiPort], cwd: backend },
  { name: "worker", color: 35, cmd: python, args: ["-m", "app.worker"], cwd: backend },
  { name: "web", color: 33, cmd: process.execPath, args: [join(root, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", webPort], cwd: root },
];

const children = procs.map(({ name, color, cmd, args, cwd }) => {
  const child = spawn(cmd, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) out.write(prefix + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    console.log(`${prefix}종료 (code ${code})`);
    shutdown();
  });
  return child;
});

let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    // uvicorn --reload와 next dev는 자식 프로세스를 만들어서, Windows에서는 트리째 종료해야 포트가 풀린다
    if (process.platform === "win32") spawn("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill();
  }
  setTimeout(() => process.exit(0), 800);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

console.log(`[dev] 웹 http://localhost:${webPort}  ·  API http://127.0.0.1:${apiPort}/docs`);
