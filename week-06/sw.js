// 오늘 급식 서비스 워커
// - 앱 화면(파일)은 저장해 두었다가 인터넷이 끊겨도 열리게 한다.
// - 인터넷이 될 때는 항상 새 파일을 먼저 받아서, 고친 내용이 바로 보이게 한다.
// - 급식 정보(나이스 API)는 여기서 건드리지 않는다. 마지막 급식은 앱이 직접 저장한다.
const CACHE = "lunch-app-v1";
const FILES = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-512.png",
  "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req, { ignoreSearch: true }).then((hit) =>
          hit || (req.mode === "navigate" ? caches.match("./index.html") : Response.error())
        )
      )
  );
});
