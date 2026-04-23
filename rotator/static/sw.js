const CACHE = "key-rotator-v1";
const SHELL = ["/", "/manifest.json", "/icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

// Network-first for API calls, cache-first for shell
self.addEventListener("fetch", e => {
  if (e.request.url.includes("/api/") || e.request.url.includes("/ws/")) return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
