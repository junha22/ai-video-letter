// 웹(Next.js) + API(FastAPI) + 작업 워커를 한 번에 실행한다: npm run dev:all
// backend/.env가 TTS_PROVIDER=wemeet이면 TTS 서버(C:\WE_MEET\tts_server)도 같이 띄운다. 이미 떠 있으면 그대로 쓴다
// 포트 바꾸기: WEB_PORT=3001 API_PORT=8001 npm run dev:all
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const webPort = process.env.WEB_PORT || "3000";
const apiPort = process.env.API_PORT || "8000";

// 활성화된 conda 환경(conda activate ai-video-letter) → backend/.venv → 시스템 python 순서로 찾는다
const condaEnv = process.env.CONDA_DEFAULT_ENV;
const condaPython =
  process.env.CONDA_PREFIX && condaEnv !== "base"
    ? [join(process.env.CONDA_PREFIX, "python.exe"), join(process.env.CONDA_PREFIX, "bin", "python")].find(existsSync)
    : undefined;
const venvPython = [join(backend, ".venv", "Scripts", "python.exe"), join(backend, ".venv", "bin", "python")].find(existsSync);
if (condaPython) {
  console.log(`[dev] conda 환경 '${condaEnv}'의 python을 씁니다.`);
} else if (!venvPython) {
  console.warn("[dev] conda 환경도 backend/.venv도 없어서 시스템 python을 씁니다. README의 백엔드 설치 단계를 먼저 진행하세요.");
}
const python = condaPython || venvPython || "python";

// 백엔드와 같은 규칙으로 설정을 읽는다: 이미 있는 환경 변수가 backend/.env보다 우선
function readEnvFile(path) {
  const out = {};
  if (!existsSync(path)) return out;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m) out[m[1]] = m[2].replace(/\s+#.*$/, "").replace(/^(['"])(.*)\1$/, "$2");
  }
  return out;
}
const backendEnv = readEnvFile(join(backend, ".env"));
const setting = (name, fallback) => process.env[name] ?? backendEnv[name] ?? fallback;

// 포트가 이미 쓰이고 있으면 next dev는 바로 죽어서 나머지도 같이 꺼지고,
// uvicorn은 Windows에서 같은 포트에 겹쳐 떠서 요청이 다른 서버로 갈 수 있다. 그래서 띄우기 전에 확인한다
function portFree(port, host) {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", (e) => resolve(e.code !== "EADDRINUSE" && e.code !== "EACCES"));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen({ port: Number(port), host, exclusive: true });
  });
}
const busy = [];
for (const [name, port] of [["웹", webPort], ["API", apiPort]]) {
  if (!(await portFree(port, "127.0.0.1")) || !(await portFree(port, "::"))) busy.push(`${name} ${port}`);
}

// TTS 서버: 이 PC 주소일 때만 띄운다. 시작에 약 15초, VRAM 약 3.2GB를 쓰므로 이미 떠 있으면 다시 띄우지 않는다
const ttsUrl = new URL(setting("WEMEET_TTS_URL", "http://127.0.0.1:8100"));
const ttsPort = ttsUrl.port || "80";
const ttsDir = process.env.WEMEET_TTS_DIR || join(root, "..", "tts_server");
const ttsScript = join(ttsDir, "run_server.ps1");
const ttsHealthy = () =>
  fetch(`${ttsUrl.origin}/health`, { signal: AbortSignal.timeout(2000) })
    .then((r) => r.ok)
    .catch(() => false);
let startTts = false;
if (setting("TTS_PROVIDER", "local") === "wemeet") {
  if (!["127.0.0.1", "localhost"].includes(ttsUrl.hostname)) {
    console.log(`[dev] TTS 서버(${ttsUrl.origin})가 다른 머신에 있어서 여기서 띄우지 않습니다.`);
  } else if (await ttsHealthy()) {
    console.log(`[dev] TTS 서버가 이미 떠 있어서 그대로 씁니다 (${ttsUrl.origin}).`);
  } else if (process.platform !== "win32" || !existsSync(ttsScript)) {
    console.warn(`[dev] ${ttsScript}가 없어서 TTS 서버를 띄우지 않습니다. WEMEET_TTS_DIR로 위치를 알려 주세요.`);
  } else if (!(await portFree(ttsPort, "127.0.0.1"))) {
    busy.push(`TTS ${ttsPort} (응답 없는 다른 프로그램)`);
  } else {
    startTts = true;
  }
}

if (busy.length) {
  console.error(`[dev] 포트가 이미 사용 중입니다: ${busy.join(", ")}`);
  console.error("[dev] 그 포트를 쓰는 프로그램을 끄거나 다른 포트로 띄우세요: $env:WEB_PORT=3001; $env:API_PORT=8001; npm run dev:all");
  process.exit(1);
}

const env = {
  ...process.env,
  BACKEND_URL: `http://127.0.0.1:${apiPort}`,
  PUBLIC_BASE_URL: process.env.PUBLIC_BASE_URL || `http://localhost:${webPort}`,
  PYTHONIOENCODING: "utf-8",
  PYTHONUNBUFFERED: "1",
};

// TTS 서버는 자기 conda 환경(Wemeet-cb)의 python을 쓴다. 이 conda 환경의 DLL을 먼저 찾지 않도록 PATH에서 뺀다
function ttsEnv() {
  const out = { ...env };
  delete out.CONDA_PREFIX;
  delete out.CONDA_DEFAULT_ENV;
  const prefix = process.env.CONDA_PREFIX?.toLowerCase();
  const pathKey = Object.keys(out).find((k) => k.toUpperCase() === "PATH");
  if (prefix && pathKey) {
    out[pathKey] = out[pathKey].split(";").filter((p) => !p.toLowerCase().startsWith(prefix)).join(";");
  }
  return out;
}

const procs = [
  { name: "api", color: 36, cmd: python, args: ["-m", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--port", apiPort], cwd: backend },
  { name: "worker", color: 35, cmd: python, args: ["-m", "app.worker"], cwd: backend, afterTts: startTts },
  { name: "web", color: 33, cmd: process.execPath, args: [join(root, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", webPort], cwd: root },
];
if (startTts) {
  procs.unshift({
    name: "tts",
    color: 32,
    cmd: "powershell",
    args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ttsScript, "-Port", ttsPort],
    cwd: ttsDir,
    env: ttsEnv(),
  });
}

const children = [];
let stopping = false;

function start({ name, color, cmd, args, cwd, env: procEnv }) {
  const child = spawn(cmd, args, { cwd, env: procEnv || env, stdio: ["ignore", "pipe", "pipe"] });
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
  children.push(child);
}

// 워커는 시작하자마자 TTS 서버 연결을 확인하므로, 같이 띄울 때는 TTS 서버가 준비된 뒤에 띄운다
async function startAfterTts(proc) {
  const deadline = Date.now() + 180_000; // 처음 실행하는 PC는 원본 모델(약 3GB)을 내려받느라 오래 걸린다
  while (!stopping && Date.now() < deadline && !(await ttsHealthy())) {
    await new Promise((r) => setTimeout(r, 1000));
  }
  if (stopping) return;
  if (await ttsHealthy()) console.log("[dev] TTS 서버 준비 완료, 워커를 띄웁니다.");
  else console.warn("[dev] TTS 서버가 3분 안에 뜨지 않았습니다. 워커는 먼저 띄우고, 영상 만들 때 다시 연결합니다.");
  start(proc);
}

for (const proc of procs) {
  if (proc.afterTts) startAfterTts(proc);
  else start(proc);
}

function shutdown() {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    // uvicorn --reload, next dev, run_server.ps1은 자식 프로세스를 만들어서, Windows에서는 트리째 종료해야 포트가 풀린다
    if (process.platform === "win32") spawn("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill();
  }
  setTimeout(() => process.exit(0), 800);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

console.log(`[dev] 웹 http://localhost:${webPort}  ·  API http://127.0.0.1:${apiPort}/docs`);
if (startTts) console.log(`[dev] TTS 서버 ${ttsUrl.origin} 띄우는 중 (약 15초). 준비되면 워커가 뜹니다.`);
