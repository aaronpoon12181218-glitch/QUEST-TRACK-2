// 크롬을 몰래(창 없이) 띄워 조종하는 작은 도구. 따로 설치할 것 없음 (Node 22 이상).
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME_PATHS = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
];

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch() {
  const exe = CHROME_PATHS.find(existsSync);
  if (!exe) throw new Error("크롬이나 엣지를 찾지 못했어요.");
  const profile = mkdtempSync(join(tmpdir(), "week06-check-"));
  const port = 9300 + Math.floor(Math.random() * 500);
  const proc = spawn(exe, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });

  let target;
  for (let i = 0; i < 50 && !target; i++) {
    await sleep(200);
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = list.find((t) => t.type === "page");
    } catch {}
  }
  if (!target) throw new Error("크롬과 연결하지 못했어요.");

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
  let id = 0;
  const waiting = new Map();
  const listeners = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) {
      const { ok, bad } = waiting.get(m.id);
      waiting.delete(m.id);
      m.error ? bad(new Error(m.error.message)) : ok(m.result);
    } else if (m.method) listeners.forEach((f) => f(m));
  };
  const send = (method, params = {}) => new Promise((ok, bad) => {
    const n = ++id;
    waiting.set(n, { ok, bad });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "스크립트 오류");
    return r.result.value;
  };
  const goto = async (url, waitMs = 1500) => {
    await send("Page.navigate", { url });
    await sleep(waitMs);
  };
  const waitFor = async (expr, timeout = 15000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      try { if (await evaluate(expr)) return true; } catch {}
      await sleep(200);
    }
    return false;
  };
  const close = async () => {
    try { ws.close(); } catch {}
    proc.kill();
    await sleep(500);
    try { rmSync(profile, { recursive: true, force: true }); } catch {}
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  return { send, evaluate, goto, waitFor, close, onEvent: (f) => listeners.push(f) };
}
