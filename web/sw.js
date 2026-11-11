/* Offline support (served at /sw.js; the route prepends `const CONFIG = {...}`).
 *
 * Pages: network first. Every page that loads is saved; with no connection (or no
 * answer within NAV_TIMEOUT, or a 5xx while the site restarts) the saved copy is
 * served with data-saved on <html>, which app.js turns into a banner. A page never
 * opened shows a list of the saved ones instead.
 * Static files are versioned (?v=): cache first, all of them stored on install.
 * Images: cache first. Chart data: network first, saved copy offline.
 * Search: the server when online; offline it searches the titles of saved pages.
 * Sign-in redirects pass straight through and are never saved.
 * The same file runs on basketball.asir.dev and baseball.asir.dev.
 */
"use strict";

const STATIC = "static";
const PAGES = "pages-v1";
const IMAGES = "images-v1";
const DATA = "data-v1";
const META = "meta-v1";
const LIMITS = { [PAGES]: 300, [IMAGES]: 800, [DATA]: 80 };
const NAV_TIMEOUT = 8000;
const WARM_EVERY = 60 * 60 * 1000;
const SKIP = ["/oauth2/", "/healthz", "/sw.js", "/manifest.webmanifest"];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC);
    await Promise.all(CONFIG.static.map(async url => {
      if (await cache.match(url)) return;
      const response = await fetch(url, { redirect: "manual" });
      if (!response.ok) throw new Error(`precache ${url}: ${response.status}`);
      await cache.put(url, response);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keep = new Set([STATIC, PAGES, IMAGES, DATA, META]);
    for (const name of await caches.keys()) {
      if (!keep.has(name)) await caches.delete(name);
    }
    // Drop older versions of static files. Pages saved under an older version
    // still find the current file through the ignoreSearch fallback in asset().
    const current = new Set(CONFIG.static.map(url => new URL(url, self.location.origin).href));
    const cache = await caches.open(STATIC);
    for (const request of await cache.keys()) {
      if (!current.has(request.url)) await cache.delete(request);
    }
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
    await self.clients.claim();
  })());
});

self.addEventListener("message", event => {
  if (event.data === "warm") event.waitUntil(warm());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    if (request.destination === "image" && CONFIG.imageHosts.includes(url.hostname)) {
      event.respondWith(image(request, true));
    }
    return;
  }
  if (SKIP.some(prefix => url.pathname.startsWith(prefix))) return;
  if (request.mode === "navigate") return event.respondWith(page(event));
  if (url.pathname.startsWith("/static/")) return event.respondWith(asset(request));
  if (CONFIG.imagePaths.some(prefix => url.pathname.startsWith(prefix))) return event.respondWith(image(request, false));
  if (url.pathname === "/api/search") return event.respondWith(search(request, url));
  if (CONFIG.dataPaths.some(prefix => url.pathname.startsWith(prefix))) return event.respondWith(data(request));
});

// ------------------------------------------------------------------ pages

function pageKey(href) {
  const url = new URL(href);
  url.hash = "";
  return url.href;
}

function isPage(response) {
  return Boolean(response) && response.status === 200 && response.type === "basic"
    && (response.headers.get("content-type") || "").includes("text/html");
}

async function savePage(cache, key, response) {
  const text = await response.text();
  const match = /<title>([^<]*)<\/title>/i.exec(text);
  const title = match ? decodeEntities(match[1]).replace(` · ${CONFIG.site}`, "").trim() : "";
  const headers = new Headers({
    "content-type": response.headers.get("content-type") || "text/html; charset=utf-8",
    "x-title": encodeURIComponent(title),
    "x-saved": new Date(response.headers.get("date") || Date.now()).toISOString(),
  });
  await cache.put(key, new Response(text, { status: 200, headers }));
  await trim(cache, LIMITS[PAGES]);
}

async function page(event) {
  const request = event.request;
  const key = pageKey(request.url);
  const cache = await caches.open(PAGES);
  const saved = await cache.match(key, { ignoreVary: true });
  const preload = event.preloadResponse || Promise.resolve(undefined);
  if (!self.navigator.onLine && saved) {
    event.waitUntil(preload.catch(() => undefined));
    return savedCopy(saved);
  }
  const network = preload.then(response => response || fetch(request));
  event.waitUntil(network.then(response => isPage(response) ? savePage(cache, key, response.clone()) : undefined)
    .catch(() => undefined));
  try {
    const response = saved ? await withTimeout(network, NAV_TIMEOUT) : await network;
    if (response.status >= 500 && saved) return savedCopy(saved);
    return response;
  } catch (error) {
    return saved ? savedCopy(saved) : offlinePage(request.url);
  }
}

async function savedCopy(saved) {
  const text = await saved.text();
  const stamp = escapeHtml(saved.headers.get("x-saved") || "");
  return new Response(text.replace(/<html\b/i, `<html data-saved="${stamp}"`), {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

async function savedPages() {
  const cache = await caches.open(PAGES);
  const out = [];
  for (const request of (await cache.keys()).reverse()) {
    const response = await cache.match(request);
    if (!response) continue;
    const url = new URL(request.url);
    out.push({
      path: url.pathname + url.search,
      title: decodeURIComponent(response.headers.get("x-title") || "") || url.pathname,
      saved: response.headers.get("x-saved") || "",
    });
  }
  return out;
}

const GROUPS = [
  ["Main pages", path => CONFIG.pages.includes(path)],
  ["Players", path => path.startsWith("/player/")],
  ["Teams", path => path.startsWith("/team/")],
  ["Games", path => path.startsWith("/game/")],
  ["Other", () => true],
];

async function offlinePage(href) {
  const pages = await savedPages();
  const sections = GROUPS.map(([name]) => [name, []]);
  for (const item of pages) {
    const index = GROUPS.findIndex(([, test]) => test(item.path));
    sections[index][1].push(item);
  }
  const list = sections.filter(([, items]) => items.length).map(([name, items]) => {
    const rows = items.map(item => `<li><a href="${escapeHtml(item.path)}">${escapeHtml(item.title)}</a>`
      + `<small>${escapeHtml(item.path)}</small></li>`).join("");
    return `<h2>${escapeHtml(name)} <span>${items.length}</span></h2><ul>${rows}</ul>`;
  }).join("");
  const path = new URL(href).pathname;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0a0e15"><title>Offline · ${escapeHtml(CONFIG.site)}</title>
<link rel="stylesheet" href="${escapeHtml(CONFIG.css)}">
<style>
.off{max-width:720px;margin:0 auto;padding:28px 16px 48px}
.off h1{font-size:22px;margin:0 0 6px}.off p{color:var(--dim);margin:0 0 18px}
.off h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:22px 0 6px}
.off h2 span{color:var(--dim)}.off ul{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.off li{display:flex;justify-content:space-between;gap:12px;padding:10px 12px;border-top:1px solid var(--line-soft);background:var(--surface)}
.off li:first-child{border-top:0}.off li a{color:var(--text);text-decoration:none}.off li small{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.off .again{display:inline-block;margin-right:14px;color:var(--accent)}
</style></head><body><main class="off">
<h1>You're offline</h1>
<p>${escapeHtml(path)} hasn't been saved on this device yet. Every page you open is kept for offline use, and the main pages refresh about once an hour while you're online.</p>
<a class="again" href="${escapeHtml(path)}">Try again</a><a class="again" href="/">Home</a>
${list || "<p>No pages saved yet.</p>"}
</main></body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}

// Refresh the main pages so they are recent when the connection drops.
async function warm() {
  const meta = await caches.open(META);
  const last = await meta.match("/__warm");
  if (last && Date.now() - Number(await last.text()) < WARM_EVERY) return;
  await meta.put("/__warm", new Response(String(Date.now())));
  const cache = await caches.open(PAGES);
  for (const path of CONFIG.pages) {
    try {
      const response = await fetch(path, { redirect: "manual", cache: "no-cache" });
      if (isPage(response)) {
        await savePage(cache, pageKey(new URL(path, self.location.origin).href), response);
      } else if (response.type === "opaqueredirect") {
        await meta.delete("/__warm");   // signed out: try again after the next sign-in
        return;
      }
    } catch (error) {
      await meta.delete("/__warm");
      return;
    }
  }
}

// ------------------------------------------------------------------ the rest

async function asset(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request, { ignoreVary: true });
  if (hit) return hit;
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic" && new URL(request.url).searchParams.has("v")) {
      await cache.put(request.url, response.clone());
    }
    return response;
  } catch (error) {
    const older = await cache.match(request, { ignoreSearch: true, ignoreVary: true });
    if (older) return older;
    throw error;
  }
}

async function image(request, crossOrigin) {
  const cache = await caches.open(IMAGES);
  const hit = await cache.match(request.url, { ignoreVary: true });
  if (hit) return hit;
  try {
    // Cross-origin photos are fetched with CORS (MLB's image host allows it), so
    // the cache stores a readable response rather than a padded opaque one.
    const response = await fetch(crossOrigin ? new Request(request.url, { mode: "cors", credentials: "omit" }) : request);
    if (response.ok) {
      await cache.put(request.url, response.clone());
      await trim(cache, LIMITS[IMAGES]);
    }
    return response;
  } catch (error) {
    if (crossOrigin) return Response.error();
    return new Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
      { headers: { "content-type": "image/svg+xml" } });
  }
}

async function data(request) {
  const cache = await caches.open(DATA);
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic") {
      await cache.put(request.url, response.clone());
      await trim(cache, LIMITS[DATA]);
    }
    return response;
  } catch (error) {
    const hit = await cache.match(request.url, { ignoreVary: true });
    if (hit) return hit;
    return json({ error: "offline" }, 503);
  }
}

async function search(request, url) {
  try {
    return await fetch(request);
  } catch (error) {
    const words = fold(url.searchParams.get("q") || "").split(/\s+/).filter(Boolean);
    const seen = new Set();
    const results = [];
    for (const item of await savedPages()) {
      const kind = item.path.startsWith("/team/") ? "team" : item.path.startsWith("/player/") ? "player" : "";
      const name = fold(item.title);
      if (!kind || seen.has(item.title) || !words.length || !words.every(word => name.includes(word))) continue;
      seen.add(item.title);
      results.push({ kind, label: item.title, sub: "Saved for offline", url: item.path });
      if (results.length >= 10) break;
    }
    return json(results, 200);
  }
}

// ------------------------------------------------------------------ helpers

async function trim(cache, limit) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - limit; i += 1) await cache.delete(keys[i]);
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then(value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); });
  });
}

function json(value, status) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function fold(text) {
  return String(text).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function decodeEntities(text) {
  return text.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (_m, name) =>
    ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'" })[name]);
}
