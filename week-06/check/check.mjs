// week-06 확인 도구
// 쓰는 법:  node week-06/check/check.mjs                 ← 내 컴퓨터에서 GitHub Pages 와 같은 주소 모양으로 확인
//          node week-06/check/check.mjs <배포 주소>      ← 올린 뒤 진짜 GitHub Pages 주소로 확인
// 확인용 학교는 우리 학교가 아니라 아무 학교 하나(서울 B10 / 7132131)를 쓴다.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, sleep } from "./cdp.mjs";

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");
const TEST = "office=B10&school=7132131";
const WEEKDAY = "20261113"; // 급식이 있었던 평일

/* ---------- 내 컴퓨터용 작은 웹 서버 (GitHub Pages 와 같은 /QUEST-TRACK-2/week-06/ 주소) ---------- */
const PREFIX = "/QUEST-TRACK-2/week-06/";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml" };
function startServer() {
  return new Promise((ok) => {
    const server = createServer(async (req, res) => {
      let path = decodeURIComponent(new URL(req.url, "http://x").pathname);
      if (!path.startsWith(PREFIX)) { res.writeHead(404); return res.end(); }
      path = path.slice(PREFIX.length) || "index.html";
      if (path.includes("..") || path.startsWith("check/")) { res.writeHead(404); return res.end(); }
      try {
        const body = await readFile(join(APP_DIR, path));
        res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream" });
        res.end(body);
      } catch { res.writeHead(404); res.end(); }
    });
    server.listen(0, "127.0.0.1", () => ok(server));
  });
}

/* ---------- 결과 기록 ---------- */
let pass = 0, fail = 0;
function check(name, ok, detail = "") {
  ok ? pass++ : fail++;
  console.log(`${ok ? "  통과" : "✗ 실패"}  ${name}${detail ? "  — " + detail : ""}`);
}

const server = process.argv[2] ? null : await startServer();
const BASE = process.argv[2] ? process.argv[2].replace(/\/?$/, "/") : `http://127.0.0.1:${server.address().port}${PREFIX}`;
console.log("확인할 주소:", BASE, "\n");

const b = await launch();
const text = () => b.evaluate("document.getElementById('mealBox').innerText");
const menus = () => b.evaluate("[...document.querySelectorAll('.menu li')].map(li => li.firstChild.textContent)");

try {
  /* 1. 설치할 수 있는 앱인지 */
  await b.goto(BASE + "?" + TEST + "&date=" + WEEKDAY, 500);
  await b.waitFor("document.querySelector('.menu li') || document.querySelector('.notice')");
  const man = await b.send("Page.getAppManifest");
  check("manifest 를 찾음", !!man.url && man.errors.length === 0, man.errors.map((e) => e.message).join(", "));
  const m = JSON.parse(man.data || "{}");
  check("manifest: 이름·standalone·시작 주소", m.name === "오늘 급식" && m.display === "standalone" && m.start_url === "./");
  const iconOk = await b.evaluate(`Promise.all(${JSON.stringify(m.icons.map((i) => i.src))}.map(s => fetch(s).then(r => r.ok && r.headers.get('content-type').includes('png'))))`);
  check("아이콘 파일 " + iconOk.length + "개를 받을 수 있음", iconOk.every(Boolean));
  check("아이콘 192·512·maskable 있음",
    m.icons.some((i) => i.sizes === "192x192") && m.icons.some((i) => i.sizes === "512x512" && i.purpose === "any") && m.icons.some((i) => i.purpose === "maskable"));

  const swReady = await b.waitFor("navigator.serviceWorker && navigator.serviceWorker.getRegistration().then(r => !!(r && r.active))", 15000);
  check("서비스 워커가 켜짐", swReady);
  await b.goto(BASE + "?" + TEST + "&date=" + WEEKDAY, 500);
  await b.waitFor("document.querySelector('.menu li')");
  check("서비스 워커가 앱을 맡음", await b.evaluate("!!navigator.serviceWorker.controller"));
  const inst = await b.send("Page.getInstallabilityErrors");
  check("크롬이 '설치 가능'으로 판단", inst.installabilityErrors.length === 0,
    inst.installabilityErrors.map((e) => e.errorId).join(", "));

  /* 2. 급식 보여 주기 */
  const list = await menus();
  check("평일 급식 메뉴가 나옴", list.length > 0, list.join(" / "));
  check("메뉴에 <br/>·괄호 번호가 없음", list.every((n) => !/[<>]|[(（]\s*\d+(\.\d+)*\s*[)）]/.test(n)));
  check("알레르기 번호가 작게 붙음", await b.evaluate("document.querySelectorAll('.menu .allergy').length > 0"));

  /* 3. 폰 화면 폭 */
  for (const w of [320, 360, 414]) {
    await b.send("Emulation.setDeviceMetricsOverride", { width: w, height: 760, deviceScaleFactor: 2, mobile: true });
    await sleep(300);
    const over = await b.evaluate("document.documentElement.scrollWidth - window.innerWidth");
    check(`폭 ${w}px 에서 옆으로 넘치지 않음`, over <= 0, over > 0 ? over + "px 넘침" : "");
  }
  await b.send("Emulation.clearDeviceMetricsOverride");

  /* 4. 인터넷이 끊겼을 때 */
  const offline = (on) => b.send("Network.emulateNetworkConditions", { offline: on, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await offline(true);
  await b.goto(BASE + "?" + TEST + "&date=" + WEEKDAY, 500);
  const opened = await b.waitFor("document.querySelector('.offline') || document.querySelector('.notice')");
  check("인터넷 없이도 앱이 열림", opened);
  const t1 = await text();
  check("마지막으로 받아 온 정보라고 알려 줌", t1.includes("마지막으로 받아 온 정보"));
  check("언제 받은 정보인지 보여 줌", /\d+월 \d+일.*\d+:\d\d에 받은 정보/.test(t1), (t1.match(/.*에 받은 정보예요\./) || [""])[0]);
  check("까닭을 보여 줌", t1.includes("까닭: 인터넷에 연결돼 있지 않아요"));
  check("저장해 둔 메뉴가 나옴", (await menus()).length === list.length);

  await b.goto(BASE + "?" + TEST + "&date=20261116", 500);
  await b.waitFor("document.querySelector('.offline')");
  check("다른 날 정보면 '오늘 급식이 아니에요'라고 알려 줌", (await text()).includes("오늘 급식이 아니에요"));

  await b.evaluate("localStorage.clear()");
  await b.goto(BASE + "?" + TEST + "&date=" + WEEKDAY, 500);
  await b.waitFor("document.querySelector('.notice')");
  const t2 = await text();
  check("저장된 정보도 없으면 빈 화면 대신 까닭을 보여 줌", t2.includes("정보를 받아 오지 못했어요") && t2.includes("인터넷"), t2.replace(/\s+/g, " ").trim());

  await offline(false);
  await b.goto(BASE + "?" + TEST + "&date=" + WEEKDAY, 500);
  check("인터넷이 돌아오면 다시 받아 옴", await b.waitFor("document.querySelector('.menu li') && !document.querySelector('.offline')"));

  /* 5. 급식 없는 날, 틀린 학교 코드 */
  await b.goto(BASE + "?" + TEST + "&date=20261115", 500);
  await b.waitFor("document.querySelector('.notice')");
  check("급식 없는 날은 '오늘은 급식이 없습니다'", (await text()).includes("오늘은 급식이 없습니다"));
  await b.goto(BASE + "?office=ZZZ&school=0&date=" + WEEKDAY, 500);
  await b.waitFor("document.querySelector('.notice')");
  check("틀린 학교 코드는 까닭을 보여 줌", (await text()).includes("학교를 찾을 수 없어요"));
} catch (e) {
  check("확인 도중 오류", false, e.message);
} finally {
  await b.close();
  server && server.close();
}

console.log(`\n결과: 통과 ${pass} · 실패 ${fail}`);
process.exit(fail ? 1 : 0);
