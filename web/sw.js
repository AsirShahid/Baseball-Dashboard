/* Offline support (served at /sw.js; the route prepends `const CONFIG = {...}`).
 *
 * Pages: network first. Every page that loads is saved; with no connection (or no
 * answer within NAV_TIMEOUT, or a 5xx while the site restarts) the saved copy is
 * served with data-saved on <html>, which app.js turns into a banner. A page never
 * opened shows a list of the saved ones instead.
 * Static files are versioned (?v=): cache first, all of them stored on install.
 * Images: cache first. Chart data: network first, saved copy offline.
 * Search: the server when online; offline it searches the titles of saved pages.
 * Sign-in redirects are never saved. Sign-in navigations (/oauth2/) are answered with
 * the navigation preload response (or, without preload, one request) so each reaches
 * the gateway exactly once.
 *
 * The full offline copy (web/offline.py, static/offline/): a device that downloaded it
 * holds the database and the site's code. With no connection a page then opens in a
 * shell (shellPage) whose worker runs that code; the site runs in a frame inside it, and
 * every request the frame makes that the server cannot answer is passed to the shell
 * (local). A page saved from the server after the copy was last confirmed current is still preferred.
 * A redirect for the frame (the sign-in gateway) is not followed there: sign-in pages refuse
 * to open in a frame, so the whole window loads the address instead (leaveShell).
 * The same file runs on basketball.asir.dev and baseball.asir.dev.
 */
"use strict";

const STATIC = "static";
const PAGES = "pages-v1";
const IMAGES = "images-v1";
const DATA = "data-v1";
const META = "meta-v1";
const PHOTOS = "photos-v1";            // this season's players' photos, kept by the offline copy (sync.js)
const RUNTIME = "offline-rt-";          // caches holding the offline copy's Python (sync.js)
const ACTIVE = "/__offline/manifest";  // in META: the offline copy this device holds
const LIMITS = { [PAGES]: 300, [IMAGES]: 800, [DATA]: 80 };
const NAV_TIMEOUT = 8000;
const LOCAL_TIMEOUT = 5000;            // with an offline copy to fall back on, wait less
const NET_REST = 30000;                // after the server did not answer, do not ask it for this long
const WARM_EVERY = 60 * 60 * 1000;
const SKIP = ["/oauth2/", "/healthz", "/sw.js", "/manifest.webmanifest", "/offline/manifest.json", "/offline/chunk/"];
let netDown = 0;                       // when the server last failed to answer a framed page
let shellId = "";                      // the window that is the offline shell, once found
let leftShell = 0;                     // when a framed page last sent its window back to the server

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
    const keep = new Set([STATIC, PAGES, IMAGES, DATA, META, PHOTOS]);
    for (const name of await caches.keys()) {
      if (!keep.has(name) && !name.startsWith(RUNTIME)) await caches.delete(name);
    }
    // Drop older versions of static files. Pages saved under an older version
    // still find the current file through the ignoreSearch fallback in asset().
    const current = new Set(CONFIG.static.map(url => new URL(url, self.location.origin).href));
    const cache = await caches.open(STATIC);
    for (const request of await cache.keys()) {
      if (!current.has(request.url)) await cache.delete(request);
    }
    // Navigation preload saves the worker's start-up time on each page. Not in Firefox:
    // there a preload that fails (server unreachable) fails the whole navigation, and the
    // saved page or the offline copy is never shown ("Problem loading page").
    const preload = self.registration.navigationPreload;
    if (preload) await (/Firefox\/\d/.test(self.navigator.userAgent || "") ? preload.disable() : preload.enable());
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
  if (SKIP.some(prefix => url.pathname.startsWith(prefix))) {
    // Never saved, but a navigation still has to be answered here: navigation preload
    // has already sent it, and passing it through sends it again, which replays the
    // one-time code in /oauth2/callback (the gateway's 500 or 403 page after sign-in).
    if (request.mode === "navigate") event.respondWith(preloaded(event));
    return;
  }
  if (url.pathname.startsWith("/offline/rt/")) return event.respondWith(runtime(request));
  if (request.mode === "navigate") {
    const inFrame = request.destination === "iframe" || request.destination === "frame";
    return event.respondWith(inFrame ? framed(event) : page(event));
  }
  if (url.pathname.startsWith("/static/")) return event.respondWith(asset(request));
  if (CONFIG.imagePaths.some(prefix => url.pathname.startsWith(prefix))) return event.respondWith(image(request, false));
  if (url.pathname === "/api/search") return event.respondWith(search(request, url));
  if (CONFIG.dataPaths.some(prefix => url.pathname.startsWith(prefix))) return event.respondWith(data(request));
});

// ------------------------------------------------------------------ pages

// The navigation preload response, or one network request when there is none.
async function preloaded(event) {
  const response = await Promise.resolve(event.preloadResponse).catch(() => undefined);
  return response || fetch(event.request);
}

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
  const copy = await offlineCopy();
  const preload = event.preloadResponse || Promise.resolve(undefined);
  // The shell just handed this window back (leaveShell): the server answered a moment
  // ago, so wait for it rather than open the shell again.
  const patient = Date.now() - leftShell < NET_REST;
  if (!self.navigator.onLine && (saved || copy) && !patient) {
    event.waitUntil(preload.catch(() => undefined));
    return copy ? shellPage() : savedCopy(saved);
  }
  const network = preload.then(response => response || fetch(request));
  event.waitUntil(network.then(response => isPage(response) ? savePage(cache, key, response.clone()) : undefined)
    .catch(() => undefined));
  try {
    const response = (saved || copy) && !patient
      ? await withTimeout(network, copy ? LOCAL_TIMEOUT : NAV_TIMEOUT) : await network;
    if (response.status >= 500 && (saved || copy)) return saved ? savedCopy(saved) : shellPage();
    return response;
  } catch (error) {
    return copy ? shellPage() : saved ? savedCopy(saved) : offlinePage(request.url);
  }
}

// ------------------------------------------------------------------ the full offline copy

// { built, checked } when this device holds an offline copy, else null. built is its
// data's time; checked is when the server last confirmed it as the newest (sync.js).
async function offlineCopy() {
  if (!CONFIG.offline) return null;
  const saved = await (await caches.open(META)).match(ACTIVE);
  if (!saved) return null;
  try {
    return { built: (await saved.json()).built_at || "", checked: Date.parse(saved.headers.get("x-checked") || "") || 0 };
  } catch (error) {
    return null;
  }
}

// The shell: a frame for the site and the worker that answers its requests (shell.js).
function shellPage() {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#0a0e15">
<title>${escapeHtml(CONFIG.site)}</title>
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<style>
html,body{margin:0;height:100%;background:#0a0e15;color:#e6e9ef;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
#view{position:fixed;inset:0;width:100%;height:100%;border:0;background:#0a0e15}
#boot{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:24px;text-align:center;background:#0a0e15}
#boot[hidden]{display:none}#boot b{font-size:17px}#boot span{color:#8b95a7;max-width:34em}
#boot i{width:26px;height:26px;border:3px solid #263042;border-top-color:#f97316;border-radius:50%;animation:turn .9s linear infinite}
#boot.failed i{display:none}@keyframes turn{to{transform:rotate(360deg)}}
</style></head><body>
<iframe id="view" title="${escapeHtml(CONFIG.site)}"></iframe>
<div id="boot" role="status"><i></i><b>Opening the offline copy</b><span id="boot-step">Starting...</span></div>
<script src="${escapeHtml(CONFIG.offline.shell)}" data-engine="${escapeHtml(CONFIG.offline.engine)}" defer></script>
</body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}

// Ask a window something over its own channel; null when it does not answer in time.
function ask(client, message, ms) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve(null), ms);
    channel.port1.onmessage = event => { clearTimeout(timer); resolve(event.data); };
    client.postMessage(message, [channel.port2]);
  });
}

// The window that is the shell, if one is open.
async function shell() {
  const known = shellId && await self.clients.get(shellId);
  if (known) return known;
  shellId = "";
  for (const client of await self.clients.matchAll({ type: "window" })) {
    if (client.frameType !== "top-level") continue;
    const answer = await ask(client, { type: "offline-shell?" }, 500);
    if (answer && answer.shell) {
      shellId = client.id;
      return client;
    }
  }
  return null;
}

// The page as the offline copy on this device renders it, or null without a shell.
async function local(request) {
  if (!CONFIG.offline) return null;
  const client = await shell();
  if (!client) return null;
  const answer = await ask(client, { type: "offline-request", method: "GET", url: request.url }, 120000);
  if (!answer || !answer.status) return null;
  const headers = new Headers();
  for (const [name, value] of answer.headers || []) {
    if (!/^(content-length|content-encoding|transfer-encoding|connection|set-cookie)$/i.test(name)) headers.append(name, value);
  }
  const location = headers.get("location");
  if ([301, 302, 303, 307, 308].includes(answer.status) && location) {
    return Response.redirect(new URL(location, request.url).href, answer.status);
  }
  if ([204, 205, 304].includes(answer.status)) return new Response(null, { status: answer.status, headers });
  let body = answer.body;
  if ((headers.get("content-type") || "").includes("text/html")) {
    const copy = await offlineCopy();
    body = new TextDecoder().decode(body).replace(/<html\b/i, `<html data-local="${escapeHtml(copy ? copy.built : "")}"`);
  }
  return new Response(body, { status: answer.status, headers });
}

// A page inside the shell's frame. Online it still comes from the server (and is saved);
// otherwise the offline copy renders it, unless a copy saved from the server is newer.
async function framed(event) {
  const request = event.request;
  const key = pageKey(request.url);
  const cache = await caches.open(PAGES);
  const preload = event.preloadResponse || Promise.resolve(undefined);
  if (self.navigator.onLine && Date.now() - netDown > NET_REST) {
    const network = preload.then(response => response || fetch(request));
    event.waitUntil(network.then(response => isPage(response) ? savePage(cache, key, response.clone()) : undefined)
      .catch(() => undefined));
    try {
      const response = await withTimeout(network, LOCAL_TIMEOUT);
      // A redirect is the sign-in gateway (or the site's own). A sign-in page refuses to
      // open in a frame (id.asir.dev: frame-ancestors 'none'), and the shell cannot read
      // another site's page, so the shell would wait for ever: the window goes itself.
      if (isRedirect(response)) return leaveShell(request.url);
      if (response.status < 500) return response;
    } catch (error) { /* fall through to this device's copy */ }
    netDown = Date.now();
  } else {
    event.waitUntil(preload.catch(() => undefined));
  }
  // A page the server sent after it last confirmed this device's copy may show newer data.
  const saved = await cache.match(key, { ignoreVary: true });
  const copy = await offlineCopy();
  if (saved && copy && Date.parse(saved.headers.get("x-saved") || "") > copy.checked) return savedCopy(saved);
  return (await local(request)) || (saved ? savedCopy(saved) : offlinePage(request.url));
}

function isRedirect(response) {
  return response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400);
}

// A page for the shell's frame that loads its address in the whole window instead, out
// of the shell and back to the server (page() then waits for the server's answer).
function leaveShell(href) {
  leftShell = Date.now();
  const target = JSON.stringify(href).replace(/</g, "\\u003c");
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${escapeHtml(CONFIG.site)}</title>
<script>top.location.replace(${target});</script></head><body style="background:#0a0e15"></body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}

// Pyodide and its wheels: from the cache sync.js filled, so the engine starts with no connection.
async function runtime(request) {
  for (const name of await caches.keys()) {
    if (!name.startsWith(RUNTIME)) continue;
    const hit = await (await caches.open(name)).match(request.url, { ignoreVary: true });
    if (hit) return hit;
  }
  return fetch(request);
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
  // A request without ?v= (a font named in the stylesheet, a worker's import) gets this
  // deploy's file: every static file is stored on install.
  const versioned = new URL(request.url).searchParams.has("v");
  const hit = await cache.match(request, { ignoreVary: true, ignoreSearch: !versioned });
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
  const hit = await cache.match(request.url, { ignoreVary: true })
    || (CONFIG.offline && await (await caches.open(PHOTOS)).match(request.url, { ignoreVary: true }));
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
    const here = await local(request);
    if (here && here.ok) return here;
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
    const here = await local(request);
    if (here && here.ok) return here;
    const hit = await cache.match(request.url, { ignoreVary: true });
    if (hit) return hit;
    return json({ error: "offline" }, 503);
  }
}

async function search(request, url) {
  try {
    return await fetch(request);
  } catch (error) {
    const here = await local(request);      // the offline copy searches everything
    if (here && here.ok) return here;
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
